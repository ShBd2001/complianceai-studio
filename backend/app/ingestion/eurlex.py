"""Connecteur EUR-Lex.

Les textes de l'Union sont accessibles par identifiant CELEX au format HTML.
Leur reutilisation est autorisee par la decision 2011/833/UE sous reserve de
citer la source.

Le decoupage suit la structure juridique (article par article) et non une
fenetre de N tokens : un article est l'unite semantique naturelle du droit, et
le couper en deux degraderait a la fois la recherche et la citation.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from app.ingestion.base import Connector, IngestionResult, RawRequirement
from app.models.enums import Pillar, RequirementKind

logger = logging.getLogger(__name__)

BASE_URL = "https://eur-lex.europa.eu/legal-content/FR/TXT/HTML/?uri=CELEX:{celex}"
LICENSE = "Decision 2011/833/UE - reutilisation autorisee avec citation de la source"

# Un article commence par "Article N" ou "Article premier".
ARTICLE_RE = re.compile(
    r"^\s*Article\s+(premier|\d+(?:\s*(?:bis|ter|quater))?)\s*$",
    re.IGNORECASE,
)
CHAPTER_RE = re.compile(r"^\s*(CHAPITRE|TITRE)\s+([IVXLC]+|\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class EurLexSource:
    code: str
    name: str
    pillar: Pillar
    celex: str
    authority: str
    version_label: str
    effective_date: date | None


SOURCES: dict[str, EurLexSource] = {
    "rgpd": EurLexSource(
        code="rgpd",
        name="Reglement general sur la protection des donnees (UE) 2016/679",
        pillar=Pillar.PRIVACY,
        celex="32016R0679",
        authority="Parlement europeen et Conseil",
        version_label="2016/679",
        effective_date=date(2018, 5, 25),
    ),
    "nis2": EurLexSource(
        code="nis2",
        name="Directive (UE) 2022/2555 dite NIS 2",
        pillar=Pillar.CYBERSECURITY,
        celex="32022L2555",
        authority="Parlement europeen et Conseil",
        version_label="2022/2555",
        effective_date=date(2024, 10, 18),
    ),
    "csrd": EurLexSource(
        code="csrd",
        name="Directive (UE) 2022/2464 sur la publication d'informations en matiere de durabilite",
        pillar=Pillar.SUSTAINABILITY,
        celex="32022L2464",
        authority="Parlement europeen et Conseil",
        version_label="2022/2464",
        effective_date=date(2024, 1, 5),
    ),
    # Reglement, et non directive : directement applicable sans transposition,
    # ce qui le rend opposable a une organisation et donc auditable en l'etat.
    "ai_act": EurLexSource(
        code="ai_act",
        name="Reglement (UE) 2024/1689 etablissant des regles harmonisees concernant l'intelligence artificielle",
        pillar=Pillar.AI_GOVERNANCE,
        celex="32024R1689",
        authority="Parlement europeen et Conseil",
        version_label="2024/1689",
        effective_date=date(2024, 8, 1),
    ),
    # Reglement egalement : la resilience operationnelle du secteur financier.
    # Recoupe NIS2 sur la gestion du risque informatique, mais y ajoute deux
    # dimensions propres : la surveillance des prestataires tiers critiques et
    # les tests de resilience.
    "dora": EurLexSource(
        code="dora",
        name="Reglement (UE) 2022/2554 sur la resilience operationnelle numerique du secteur financier",
        pillar=Pillar.OPERATIONAL_RESILIENCE,
        celex="32022R2554",
        authority="Parlement europeen et Conseil",
        version_label="2022/2554",
        effective_date=date(2025, 1, 17),
    ),
}


def html_to_lines(html: str) -> list[str]:
    """Extraction texte sans dependance de parsing lourde.

    EUR-Lex sert un HTML tres balise mais lineaire : supprimer les scripts,
    convertir les fins de bloc en sauts de ligne et retirer les balises suffit
    a obtenir un texte exploitable.
    """
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)</(p|div|br|tr|h[1-6]|li)\s*>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)

    replacements = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&rsquo;": "'", "&laquo;": '"',
        "&raquo;": '"', "&eacute;": "e", "&egrave;": "e", "&agrave;": "a",
        "&ccedil;": "c", "&ocirc;": "o", "&ecirc;": "e", "&ugrave;": "u",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"&#\d+;", " ", text)

    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.split("\n")]
    return [ln for ln in lines if ln]


def parse_articles(lines: list[str], source_url: str) -> list[RawRequirement]:
    """Regroupe les lignes en articles.

    Heuristique : une ligne qui ne contient qu'un en-tete d'article ouvre une
    nouvelle exigence ; la ligne suivante est son intitule ; tout ce qui suit
    est son corps, jusqu'au prochain en-tete.
    """
    requirements: list[RawRequirement] = []
    current_ref: str | None = None
    current_title: str = ""
    buffer: list[str] = []
    chapter: str | None = None
    order = 0

    def flush() -> None:
        nonlocal current_ref, current_title, buffer, order
        if current_ref is None:
            return
        body = "\n".join(buffer).strip()
        if body or current_title:
            order += 1
            requirements.append(
                RawRequirement(
                    reference=current_ref,
                    title=current_title[:400] or current_ref,
                    body=body or current_title,
                    kind=RequirementKind.ARTICLE,
                    ordering=order,
                    parent_reference=chapter,
                    source_url=source_url,
                )
            )
        current_ref, current_title, buffer = None, "", []

    for i, line in enumerate(lines):
        chapter_match = CHAPTER_RE.match(line)
        if chapter_match:
            chapter = f"{chapter_match.group(1).capitalize()} {chapter_match.group(2)}"
            continue

        match = ARTICLE_RE.match(line)
        if match:
            flush()
            number = match.group(1).lower()
            current_ref = "Article 1" if number == "premier" else f"Article {match.group(1)}"
            # L'intitule est la ligne suivante si elle n'est pas elle-meme un en-tete.
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            current_title = nxt if nxt and not ARTICLE_RE.match(nxt) else current_ref
            continue

        if current_ref is not None:
            if line == current_title:
                continue
            buffer.append(line)

    flush()
    return _deduplicate(requirements)


def _deduplicate(requirements: list[RawRequirement]) -> list[RawRequirement]:
    """Ecarte les references en double, en conservant la premiere occurrence.

    Un acte europeen suit toujours le meme ordre : le dispositif d'abord, les
    dispositions modificatives ensuite. Ces dernieres citent les en-tetes des
    textes qu'elles modifient, ce qui reintroduit des "Article 4", "Article 5"
    appartenant a d'autres actes.

    Verifie sur la directive NIS 2 : 73 en-tetes extraits, dont les 46 premiers
    forment la sequence complete et ordonnee des articles reels ; les 27
    suivants sont des citations issues des articles 44 a 46.

    Conserver la premiere occurrence est donc plus fiable que conserver la plus
    longue, qui restait un pari sur la taille relative des deux textes.
    """
    kept: list[RawRequirement] = []
    seen: set[str] = set()

    for requirement in requirements:
        if requirement.reference in seen:
            continue
        seen.add(requirement.reference)
        kept.append(requirement)

    dropped = len(requirements) - len(kept)
    if dropped:
        logger.info(
            "%d en-tete(s) en double ecarte(s) : citations issues des "
            "dispositions modificatives.", dropped,
        )

    for position, requirement in enumerate(kept, start=1):
        requirement.ordering = position
    return kept


class EurLexConnector(Connector):
    def __init__(self, code: str, timeout: float = 60.0, fichier: "Path | None" = None) -> None:
        if code not in SOURCES:
            raise ValueError(f"Source EUR-Lex inconnue : {code}")
        self.source = SOURCES[code]
        self.code = code
        self.timeout = timeout
        # Copie locale du texte. EUR-Lex limite les acces automatises et repond
        # alors 202 sans servir le contenu ; l'ingestion depuis un fichier
        # enregistre depuis un navigateur contourne cette limite et rend la
        # procedure reproductible, notamment en demonstration.
        self.fichier = Path(fichier) if fichier else None

    @property
    def url(self) -> str:
        return BASE_URL.format(celex=self.source.celex)

    # EUR-Lex repond 202 Accepted, et non 200, lorsqu'il juge le client
    # automatise : le corps renvoye est alors une page d'attente sans article.
    # Deux consequences a traiter. D'une part `raise_for_status` ne leve rien
    # sous 400, si bien que cette page etait transmise au parseur, qui concluait
    # a tort a un changement de structure du site. D'autre part un agent
    # utilisateur annoncant un robot declenche presque systematiquement ce 202.
    NAVIGATEUR = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }
    TENTATIVES = 4
    ATTENTE_INITIALE = 3.0

    def _telecharger(self) -> str:
        """Recupere le HTML, en attendant que la ressource soit prete.

        Le 202 signifie que la generation est en cours cote EUR-Lex : on
        patiente puis on reessaie, avec une attente doublee a chaque tour.
        """
        if self.fichier is not None:
            logger.info("Lecture de %s depuis %s", self.code, self.fichier)
            html = self.fichier.read_text(encoding="utf-8", errors="replace")
            if len(html) < 20_000:
                raise RuntimeError(
                    f"Le fichier {self.fichier} ne contient que {len(html)} caracteres. "
                    f"Enregistrer la page complete depuis le navigateur "
                    f"(Ctrl+S, « page web complete » ou « page HTML seule »)."
                )
            return html

        attente = self.ATTENTE_INITIALE
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.NAVIGATEUR,
        ) as client:
            for tentative in range(1, self.TENTATIVES + 1):
                response = client.get(self.url)
                response.raise_for_status()

                if response.status_code == 200 and len(response.text) > 20_000:
                    return response.text

                logger.warning(
                    "EUR-Lex a repondu %s pour %s (tentative %d/%d), "
                    "nouvel essai dans %.0f s.",
                    response.status_code, self.code, tentative, self.TENTATIVES, attente,
                )
                if tentative < self.TENTATIVES:
                    time.sleep(attente)
                    attente *= 2

        raise RuntimeError(
            f"EUR-Lex n'a pas servi le texte de {self.code} apres "
            f"{self.TENTATIVES} tentatives (dernier code : {response.status_code}). "
            f"Le service limite les acces automatises. Reessayer plus tard, ou "
            f"ingerer depuis une copie locale : "
            f"python -m app.ingestion.cli --only {self.code} --fichier chemin.html"
        )

    def fetch(self) -> IngestionResult:
        logger.info("Telechargement de %s depuis %s", self.code, self.url)
        html = self._telecharger()

        lines = html_to_lines(html)
        requirements = parse_articles(lines, self.url)

        if not requirements:
            raise RuntimeError(
                f"Aucun article extrait pour {self.code}. La structure HTML "
                f"d'EUR-Lex a probablement change : verifier les expressions "
                f"regulieres dans app/ingestion/eurlex.py."
            )

        logger.info("%s : %d articles extraits", self.code, len(requirements))

        return IngestionResult(
            code=self.source.code,
            name=self.source.name,
            pillar=self.source.pillar,
            authority=self.source.authority,
            source_url=self.url,
            license=LICENSE,
            celex_id=self.source.celex,
            version_label=self.source.version_label,
            effective_date=self.source.effective_date,
            requirements=requirements,
            raw_text="\n".join(lines),
        )
