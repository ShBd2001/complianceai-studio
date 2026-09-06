"""Connecteur CSRD alternatif : texte consolide de la directive comptable
(2013/34/UE) via l'API Cellar d'EUR-Lex, plutot que le texte brut de la
directive modificative CSRD elle-meme.

Pourquoi un second connecteur pour CSRD
----------------------------------------
Le connecteur generique (eurlex.py) recupere et analyse le texte HTML brut
de la directive CSRD (2022/2464), qui ne porte elle-meme aucune obligation
directe : elle se contente de dire "la directive 2013/34/UE est modifiee
comme suit". Les vraies obligations (article 19 bis sur le rapport de
durabilite, 29 bis sur le rapport consolide, etc.) sont imbriquees a
l'interieur de cette description de modification, sous une mise en forme
que l'heuristique HTML generique ne detecte pas de facon fiable : verifie
le 06/09/2026, elle n'en recuperait que 5 sur une bonne vingtaine, dont pas
l'article 19 bis lui-meme — l'obligation la plus centrale du texte.

L'API Cellar expose directement le texte CONSOLIDE de la directive
2013/34/UE (la directive comptable, telle que modifiee par le CSRD et les
textes suivants), au format Formex XML, avec une vraie balise
<ARTICLE IDENTIFIER="019A"> par article insere et son intitule humain
("Article 19 bis") en clair dans <TI.ART>. Plus besoin de deviner qu'un
article a ete insere depuis sa mise en forme : la structure XML le dit
explicitement.

Ne remplace pas le connecteur generique (encore utilise par RGPD, NIS2,
DORA, AI Act) : ce module est specifique a CSRD, dont la nature de
directive modificative rend le texte consolide plus pertinent que le texte
brut de la directive elle-meme.

Chaine de recuperation (sans inscription, verifiee le 06/09/2026) :
  1. SPARQL sur le point d'acces public Cellar : CELEX -> URI de "work".
  2. Notice "branch" du work (negociation de contenu) -> URL de la
     manifestation Formex (fmx4) en francais.
  3. Cette URL renvoie une notice RDF pointant vers l'item reel (DOC_1).
  4. L'item est une archive zip contenant le XML Formex.

EUR-Lex limite les acces automatises (reponses 202 intermittentes, deja
constate sur le connecteur generique) : une copie locale du XML deja
extrait peut etre fournie via `fichier` pour rendre l'ingestion
reproductible sans dependre du reseau, comme pour les autres referentiels.
"""

from __future__ import annotations

import logging
import re
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx

from app.ingestion.base import Connector, IngestionResult, RawRequirement
from app.models.enums import Pillar, RequirementKind

logger = logging.getLogger(__name__)

CODE = "csrd"
CELEX_CSRD = "32022L2464"
LICENSE = "Decision 2011/833/UE - reutilisation autorisee avec citation de la source"

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
SPARQL_CELEX_TO_WORK = (
    'PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n'
    'PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n'
    'SELECT ?work WHERE {{\n'
    '  ?work cdm:resource_legal_id_celex "{celex}"^^xsd:string .\n'
    '}} LIMIT 1\n'
)

ARTICLE_RE = re.compile(
    r'<ARTICLE IDENTIFIER="([^"]+)">'
    r'<TI\.ART>(.*?)</TI\.ART>'
    r'<STI\.ART>(.*?)</STI\.ART>'
    r'(.*?)</ARTICLE>',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
ENTITY_HEX_RE = re.compile(r"&#x([0-9A-Fa-f]+);")
FMX4_LINK_RE = re.compile(
    r'<EXPRESSION_USES_LANGUAGE type="concept">\s*'
    r'<URI>\s*<VALUE>[^<]*/FRA</VALUE>.*?'
    r'<EXPRESSION_MANIFESTED_BY_MANIFESTATION[^>]*>\s*<SAMEAS>\s*<URI>\s*'
    r'<VALUE>([^<]*\.FRA\.fmx4)</VALUE>',
    re.DOTALL,
)


def _nettoyer_texte(fragment: str) -> str:
    """Retire les balises XML, decode les entites, aplatit en texte lisible."""
    fragment = ENTITY_HEX_RE.sub(lambda m: chr(int(m.group(1), 16)), fragment)
    fragment = TAG_RE.sub(" ", fragment)
    fragment = fragment.replace("\xa0", " ").replace('"', "").replace("”", "")
    fragment = re.sub(r"\s+", " ", fragment).strip()
    return fragment


def parse_formex_articles(xml: str, source_url: str) -> list[RawRequirement]:
    """Un <ARTICLE IDENTIFIER="019A"> par article du texte consolide."""
    requirements: list[RawRequirement] = []
    for i, m in enumerate(ARTICLE_RE.finditer(xml), start=1):
        _identifiant, ti_art, sti_art, corps = m.groups()
        reference = _nettoyer_texte(ti_art)
        titre = _nettoyer_texte(sti_art)
        corps_propre = _nettoyer_texte(corps)
        if not reference or not corps_propre:
            continue
        requirements.append(
            RawRequirement(
                reference=reference,
                title=titre,
                body=corps_propre,
                kind=RequirementKind.ARTICLE,
                ordering=i,
                source_url=source_url,
            )
        )
    return requirements


class CsrdConsolideConnector(Connector):
    code = CODE

    def __init__(self, timeout: float = 60.0, fichier: "Path | None" = None) -> None:
        self.timeout = timeout
        self.fichier = Path(fichier) if fichier else None

    def _lire_xml_local(self) -> str:
        logger.info("Lecture de csrd (consolide) depuis %s", self.fichier)
        return self.fichier.read_text(encoding="utf-8", errors="replace")

    def _resoudre_work_uri(self, client: httpx.Client) -> str:
        query = SPARQL_CELEX_TO_WORK.format(celex=CELEX_CSRD)
        response = client.get(
            SPARQL_ENDPOINT,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
        )
        response.raise_for_status()
        bindings = response.json()["results"]["bindings"]
        if not bindings:
            raise RuntimeError(
                f"Cellar SPARQL n'a retourne aucun work pour le CELEX {CELEX_CSRD}."
            )
        return bindings[0]["work"]["value"]

    def _resoudre_url_fmx4(self, client: httpx.Client, work_uri: str) -> str:
        response = client.get(
            work_uri,
            headers={"Accept": "application/xml;notice=branch", "Accept-Language": "fra"},
        )
        response.raise_for_status()
        m = FMX4_LINK_RE.search(response.text)
        if m is None:
            raise RuntimeError(
                "Notice Cellar recuperee, mais aucune manifestation fmx4 francaise "
                "n'y a ete trouvee (structure de la notice a verifier)."
            )
        return m.group(1)

    def _telecharger_zip(self, client: httpx.Client, url_fmx4: str) -> bytes:
        # Cette URL renvoie une notice RDF pointant vers l'item reel.
        notice = client.get(url_fmx4)
        notice.raise_for_status()
        item_match = re.search(
            r'manifestation_has_item rdf:resource="([^"]+)"', notice.text
        )
        if item_match is None:
            raise RuntimeError(
                f"Manifestation fmx4 recuperee ({url_fmx4}), mais aucun item associe."
            )
        item = client.get(item_match.group(1))
        item.raise_for_status()
        return item.content

    def _telecharger(self) -> str:
        if self.fichier is not None:
            return self._lire_xml_local()

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            work_uri = self._resoudre_work_uri(client)
            url_fmx4 = self._resoudre_url_fmx4(client, work_uri)
            contenu_zip = self._telecharger_zip(client, url_fmx4)

        with zipfile.ZipFile(BytesIO(contenu_zip)) as archive:
            noms_xml = [
                n for n in archive.namelist()
                if n.lower().endswith(".xml") and "doc.xml" not in n.lower()
            ]
            if not noms_xml:
                raise RuntimeError("Archive Formex recuperee mais sans fichier XML de contenu.")
            return archive.read(noms_xml[0]).decode("utf-8", errors="replace")

    def fetch(self) -> IngestionResult:
        source_url = (
            f"https://eur-lex.europa.eu/legal-content/FR/TXT/HTML/?uri=CELEX:{CELEX_CSRD}"
        )
        logger.info("Recuperation de csrd (texte consolide) via Cellar")
        xml = self._telecharger()

        requirements = parse_formex_articles(xml, source_url)
        if not requirements:
            raise RuntimeError(
                "Aucun article extrait du texte consolide CSRD. La structure "
                "Formex a peut-etre change : verifier ARTICLE_RE dans "
                "app/ingestion/csrd_consolide.py."
            )
        logger.info("csrd (consolide) : %d articles extraits", len(requirements))

        return IngestionResult(
            code=CODE,
            name="Directive (UE) 2022/2464 sur la publication d'informations en matiere de durabilite"
                 " (texte consolide de la directive comptable 2013/34/UE)",
            pillar=Pillar.SUSTAINABILITY,
            authority="Parlement europeen et Conseil",
            source_url=source_url,
            license=LICENSE,
            celex_id=CELEX_CSRD,
            version_label="2022/2464 (consolide)",
            effective_date=date(2024, 1, 5),
            requirements=requirements,
            raw_text=xml,
        )
