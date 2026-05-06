"""
Découpage des documents audités.

Corrige la cause racine du symptôme « Passages par document : 1 » : un document
entier soumis en un seul bloc dilue l'attention du modèle sur 18 articles, ce
qui produit des verdicts de complaisance.

Stratégie : découpage par frontières sémantiques (titres, sections, paragraphes)
puis regroupement jusqu'à une taille cible, avec recouvrement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Approximation robuste pour le français : ~4 caractères par token.
# Suffisant pour du chunking ; ne pas utiliser pour de la facturation.
CARACTERES_PAR_TOKEN = 4

TAILLE_CIBLE_TOKENS = 500
TAILLE_MAX_TOKENS = 650
RECOUVREMENT_RATIO = 0.15

# Titres de section : "1. Sécurité", "ARTICLE 3 —", "## Registre", "SÉCURITÉ :"
MOTIF_TITRE = re.compile(
    r"^\s*(?:"
    r"#{1,6}\s+\S"                       # markdown
    r"|(?:\d+(?:\.\d+)*)[.)]\s+\S"       # 1. / 1.2) numérotation
    r"|[A-ZÀ-Ý][A-ZÀ-Ý\s'’\-]{3,60}\s*:?\s*$"  # LIGNE EN CAPITALES
    r"|(?:Article|ARTICLE|Section|SECTION|Partie|Chapitre)\s+\S"
    r")",
    re.MULTILINE,
)


def estimer_tokens(texte: str) -> int:
    return max(1, len(texte) // CARACTERES_PAR_TOKEN)


@dataclass(frozen=True)
class Passage:
    """Un fragment de document, traçable jusqu'à sa position d'origine."""

    identifiant: str
    texte: str
    section: str
    debut: int
    fin: int
    tokens: int = field(default=0)

    def __post_init__(self) -> None:
        if not self.tokens:
            object.__setattr__(self, "tokens", estimer_tokens(self.texte))

    def apercu(self, n: int = 90) -> str:
        plat = " ".join(self.texte.split())
        return plat[:n] + ("…" if len(plat) > n else "")


def _blocs_par_section(texte: str) -> list[tuple[str, str, int]]:
    """Découpe le texte en (section, contenu, offset) selon les titres détectés."""
    positions = [m.start() for m in MOTIF_TITRE.finditer(texte)]
    if not positions or positions[0] > 0:
        positions.insert(0, 0)

    blocs: list[tuple[str, str, int]] = []
    for i, debut in enumerate(positions):
        fin = positions[i + 1] if i + 1 < len(positions) else len(texte)
        contenu = texte[debut:fin]
        if not contenu.strip():
            continue
        premiere_ligne = contenu.strip().split("\n", 1)[0].strip()
        section = premiere_ligne[:80] if MOTIF_TITRE.match(contenu) else "(préambule)"
        blocs.append((section, contenu, debut))
    return blocs


def _paragraphes(bloc: str, offset: int) -> list[tuple[str, int]]:
    """Découpe un bloc en paragraphes en conservant les offsets absolus."""
    morceaux: list[tuple[str, int]] = []
    curseur = 0
    for brut in re.split(r"\n\s*\n", bloc):
        if not brut.strip():
            curseur += len(brut) + 2
            continue
        pos = bloc.find(brut, curseur)
        if pos == -1:
            pos = curseur
        morceaux.append((brut, offset + pos))
        curseur = pos + len(brut)
    return morceaux


def decouper(
    texte: str,
    *,
    taille_cible: int = TAILLE_CIBLE_TOKENS,
    taille_max: int = TAILLE_MAX_TOKENS,
    recouvrement: float = RECOUVREMENT_RATIO,
    prefixe: str = "p",
) -> list[Passage]:
    """
    Découpe un document en passages de ~`taille_cible` tokens.

    Les frontières de section sont respectées en priorité : un passage ne
    chevauche jamais deux sections, ce qui évite d'attribuer à l'article 33 une
    phrase qui appartenait à la section sécurité.
    """
    if not texte or not texte.strip():
        return []

    passages: list[Passage] = []
    compteur = 0

    for section, bloc, offset in _blocs_par_section(texte):
        courant: list[tuple[str, int]] = []
        tokens_courant = 0

        def vider() -> None:
            nonlocal courant, tokens_courant, compteur
            if not courant:
                return
            debut = courant[0][1]
            fin = courant[-1][1] + len(courant[-1][0])
            contenu = texte[debut:fin]
            compteur += 1
            passages.append(
                Passage(
                    identifiant=f"{prefixe}{compteur:03d}",
                    texte=contenu,
                    section=section,
                    debut=debut,
                    fin=fin,
                )
            )
            # Recouvrement : on conserve la queue du passage pour le suivant.
            budget = int(taille_cible * recouvrement)
            queue: list[tuple[str, int]] = []
            acc = 0
            for para in reversed(courant):
                t = estimer_tokens(para[0])
                if acc + t > budget and queue:
                    break
                queue.insert(0, para)
                acc += t
            courant = queue
            tokens_courant = acc

        for para, pos in _paragraphes(bloc, offset):
            t = estimer_tokens(para)

            # Paragraphe seul plus grand que le maximum : découpage par phrases.
            if t > taille_max:
                vider()
                for morceau, mpos in _phrases_groupees(para, pos, taille_cible):
                    compteur += 1
                    passages.append(
                        Passage(
                            identifiant=f"{prefixe}{compteur:03d}",
                            texte=morceau,
                            section=section,
                            debut=mpos,
                            fin=mpos + len(morceau),
                        )
                    )
                continue

            if tokens_courant + t > taille_max and courant:
                vider()

            courant.append((para, pos))
            tokens_courant += t

            if tokens_courant >= taille_cible:
                vider()

        vider()

    return passages


def _phrases_groupees(para: str, offset: int, cible: int) -> list[tuple[str, int]]:
    phrases = re.split(r"(?<=[.!?;])\s+", para)
    sorties: list[tuple[str, int]] = []
    tampon: list[str] = []
    debut_local = 0
    curseur = 0
    acc = 0

    for ph in phrases:
        pos = para.find(ph, curseur)
        if pos == -1:
            pos = curseur
        if not tampon:
            debut_local = pos
        tampon.append(ph)
        acc += estimer_tokens(ph)
        curseur = pos + len(ph)
        if acc >= cible:
            sorties.append((para[debut_local:curseur], offset + debut_local))
            tampon, acc = [], 0

    if tampon:
        sorties.append((para[debut_local:curseur], offset + debut_local))
    return sorties


def diagnostic(passages: list[Passage]) -> str:
    if not passages:
        return "Aucun passage — document vide ou illisible."
    toks = [p.tokens for p in passages]
    sections = {p.section for p in passages}
    lignes = [
        f"{len(passages)} passages | {len(sections)} sections | "
        f"tokens min/moy/max = {min(toks)}/{sum(toks) // len(toks)}/{max(toks)}",
    ]
    if len(passages) == 1:
        lignes.append(
            "  ALERTE : un seul passage. Le document est trop court, ou le "
            "découpage n'a pas fonctionné. Vérifier avant d'évaluer."
        )
    return "\n".join(lignes)
