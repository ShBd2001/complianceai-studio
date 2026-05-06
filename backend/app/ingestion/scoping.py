"""Determination du perimetre auditable d'un referentiel.

Tous les articles d'un texte reglementaire ne sont pas auditables chez un
client. Le RGPD consacre ses articles 51 a 99 aux autorites de controle, aux
voies de recours et aux dispositions finales : ils s'adressent aux Etats
membres et a la CNIL, pas au responsable du traitement. Confronter la politique
de confidentialite d'une PME a l'article 68 (comite europeen de la protection
des donnees) ne produirait que du bruit.

Deux mecanismes, dans cet ordre :

1. Une liste blanche curatee par referentiel. C'est un choix editorial assume,
   documente article par article, et c'est la couche a valeur ajoutee du
   produit : savoir ce qui doit etre audite fait partie du metier d'auditeur.
2. A defaut de correspondance dans la liste, une detection lexicale du
   destinataire de l'obligation, qui sert de filet pour un referentiel dont la
   structure evoluerait.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Audience(str, Enum):
    """Destinataire de l'obligation."""

    ENTITY = "entity"          # l'organisation auditee
    MEMBER_STATE = "member_state"
    AUTHORITY = "authority"
    COMMISSION = "commission"
    STRUCTURAL = "structural"  # objet, champ d'application, definitions


@dataclass(frozen=True, slots=True)
class Scope:
    auditable: bool
    audience: Audience


# --------------------------------------------------------------------------
# Listes blanches curatees
# --------------------------------------------------------------------------
# RGPD : chapitres II a V. Obligations pesant sur le responsable du traitement
# et le sous-traitant.
#   5-11  principes, liceite, consentement, donnees sensibles
#   12-23 droits des personnes concernees
#   24-43 obligations du responsable et du sous-traitant, securite, AIPD, DPO
#   44-49 transferts hors Union
RGPD_AUDITABLE = set(range(5, 50))
RGPD_STRUCTURAL = {1, 2, 3, 4}

# NIS 2 : la quasi-totalite du texte organise la gouvernance etatique. Seules
# ces dispositions creent des obligations directes pour une entite.
#   20 gouvernance         21 mesures de gestion des risques
#   23 obligations de notification   24 schemas de certification
#   27 enregistrement      28 base de donnees des noms de domaine
#   29 partage d'informations        30 notification volontaire
NIS2_AUDITABLE = {20, 21, 23, 24, 27, 28, 29, 30}
NIS2_STRUCTURAL = {1, 2, 3, 4, 5, 6}

# CSRD : directive modificative. Les obligations reelles sont portees par les
# articles inseres dans la directive comptable 2013/34/UE, reconnaissables a
# leur suffixe ordinal latin.
CSRD_INSERTED_SUFFIXES = ("bis", "ter", "quater", "quinquies", "sexies", "septies")

WHITELISTS: dict[str, tuple[set[int], set[int]]] = {
    "rgpd": (RGPD_AUDITABLE, RGPD_STRUCTURAL),
    "nis2": (NIS2_AUDITABLE, NIS2_STRUCTURAL),
}

# --------------------------------------------------------------------------
# Detection lexicale du destinataire (filet de securite)
# --------------------------------------------------------------------------
ENTITY_MARKERS = re.compile(
    r"\b(le responsable du traitement|les responsables du traitement|"
    r"le sous-traitant|les sous-traitants|"
    r"les entites essentielles|les entites importantes|"
    r"l'entreprise|les entreprises|l'organisation)\b",
    re.IGNORECASE,
)
MEMBER_STATE_MARKERS = re.compile(
    r"\b(les etats membres|l'etat membre|chaque etat membre)\b", re.IGNORECASE
)
AUTHORITY_MARKERS = re.compile(
    r"\b(l'autorite de controle|les autorites de controle|le comite|"
    r"le controleur europeen|l'autorite competente|les autorites competentes|"
    r"le groupe de cooperation|le reseau des csirt)\b",
    re.IGNORECASE,
)
COMMISSION_MARKERS = re.compile(r"\bla commission\b", re.IGNORECASE)

ARTICLE_NUMBER = re.compile(r"Article\s+(\d+)", re.IGNORECASE)


# --------------------------------------------------------------------------
# Dependances entre exigences
# --------------------------------------------------------------------------
# Certaines obligations n'existent que si une autre s'applique. L'article 39
# decrit les missions du delegue a la protection des donnees : si l'article 37
# n'impose pas d'en designer un, les articles 38 et 39 sont sans objet.
#
# Evalue isolement, un modele de langage ne peut pas voir ce lien : il repond
# "aucune mission de delegue n'est documentee" et produit une non-conformite
# majeure sur une obligation inexistante. Le rapport se contredit alors
# lui-meme, ce qu'un auditeur reperera immediatement.
#
# La regle est deterministe et n'a pas a etre confiee au modele.
DEPENDENCIES: dict[str, dict[int, int]] = {
    "rgpd": {
        38: 37,  # fonction du DPO       <- designation du DPO
        39: 37,  # missions du DPO       <- designation du DPO
        36: 35,  # consultation prealable <- analyse d'impact
        41: 40,  # suivi des codes       <- codes de conduite
        43: 42,  # organismes de certif. <- certification
        45: 44,  # decision d'adequation <- principe des transferts
        46: 44,  # garanties appropriees <- principe des transferts
        47: 44,  # regles contraignantes <- principe des transferts
        48: 44,  # divulgations          <- principe des transferts
        49: 44,  # derogations           <- principe des transferts
    },
    "nis2": {
        # Les obligations de notification (23) presupposent que l'entite est
        # dans le champ des mesures de gestion des risques (21).
        23: 21,
    },
}


def dependency_of(framework_code: str, reference: str) -> int | None:
    """Numero de l'article dont depend cette exigence, s'il existe."""
    number = _article_number(reference)
    if number is None:
        return None
    return DEPENDENCIES.get(framework_code, {}).get(number)


def _article_number(reference: str) -> int | None:
    match = ARTICLE_NUMBER.search(reference)
    return int(match.group(1)) if match else None


def _by_markers(body: str) -> Scope:
    """Filet : on tranche sur le destinataire dominant dans le corps du texte."""
    counts = {
        Audience.ENTITY: len(ENTITY_MARKERS.findall(body)),
        Audience.MEMBER_STATE: len(MEMBER_STATE_MARKERS.findall(body)),
        Audience.AUTHORITY: len(AUTHORITY_MARKERS.findall(body)),
        Audience.COMMISSION: len(COMMISSION_MARKERS.findall(body)),
    }
    dominant = max(counts, key=lambda k: counts[k])
    if counts[dominant] == 0:
        return Scope(auditable=False, audience=Audience.STRUCTURAL)
    return Scope(auditable=dominant is Audience.ENTITY, audience=dominant)


def classify(framework_code: str, reference: str, body: str) -> Scope:
    """Determine si une exigence est auditable chez un client."""

    if framework_code == "csrd":
        # Les articles inseres portent les obligations de publication.
        if any(suffix in reference.lower() for suffix in CSRD_INSERTED_SUFFIXES):
            return Scope(auditable=True, audience=Audience.ENTITY)
        return Scope(auditable=False, audience=Audience.MEMBER_STATE)

    whitelist = WHITELISTS.get(framework_code)
    number = _article_number(reference)

    if whitelist is not None and number is not None:
        auditable_numbers, structural_numbers = whitelist
        if number in auditable_numbers:
            return Scope(auditable=True, audience=Audience.ENTITY)
        if number in structural_numbers:
            return Scope(auditable=False, audience=Audience.STRUCTURAL)
        return Scope(auditable=False, audience=Audience.AUTHORITY)

    return _by_markers(body)
