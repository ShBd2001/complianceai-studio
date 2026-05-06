"""Structures de données de la chaîne d'évaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    CONFORME = "conforme"
    MANQUEMENT = "manquement"
    HORS_PERIMETRE = "hors_perimetre"
    # Rendu quand la chaîne n'a pas pu conclure de façon fiable (erreur modèle,
    # JSON invalide après réessais). N'est jamais présenté comme un résultat
    # d'audit : il déclenche une revue humaine.
    INDETERMINE = "indetermine"


@dataclass
class Preuve:
    element: str
    intitule: str
    citation: str | None
    satisfait: bool
    verifiee: bool = False
    motif_rejet: str = ""
    similarite: float = 0.0
    bloquant: bool = True

    @property
    def retenue(self) -> bool:
        """Une preuve ne compte que si le modèle l'affirme ET que le code la valide."""
        return self.satisfait and self.verifiee


@dataclass
class DerogationRetenue:
    reference: str
    intitule: str
    citation: str | None
    justification: str
    verifiee: bool = False


@dataclass
class VerdictArticle:
    article: str
    intitule: str
    criticite: int
    verdict: Verdict
    preuves: list[Preuve] = field(default_factory=list)
    derogation: DerogationRetenue | None = None
    justification: str = ""
    confiance: float = 0.0
    revue_humaine_requise: bool = False
    motif_revue: str = ""
    passages_consultes: list[str] = field(default_factory=list)
    recommandations: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def elements_manquants(self) -> list[Preuve]:
        return [p for p in self.preuves if p.bloquant and not p.retenue]

    @property
    def compte_dans_le_score(self) -> bool:
        return self.verdict in (Verdict.CONFORME, Verdict.MANQUEMENT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": self.article,
            "intitule": self.intitule,
            "criticite": self.criticite,
            "verdict": self.verdict.value,
            "confiance": round(self.confiance, 3),
            "revue_humaine_requise": self.revue_humaine_requise,
            "motif_revue": self.motif_revue,
            "justification": self.justification,
            "derogation": (
                {
                    "reference": self.derogation.reference,
                    "intitule": self.derogation.intitule,
                    "citation": self.derogation.citation,
                    "justification": self.derogation.justification,
                }
                if self.derogation
                else None
            ),
            "preuves": [
                {
                    "element": p.element,
                    "intitule": p.intitule,
                    "citation": p.citation,
                    "retenue": p.retenue,
                    "verifiee": p.verifiee,
                    "motif_rejet": p.motif_rejet,
                    "bloquant": p.bloquant,
                }
                for p in self.preuves
            ],
            "recommandations": self.recommandations,
            "passages_consultes": self.passages_consultes,
        }


@dataclass
class RapportAudit:
    document: str
    tenant_id: str
    verdicts: list[VerdictArticle] = field(default_factory=list)
    score: float = 0.0
    detail_score: dict[str, Any] = field(default_factory=dict)
    metadonnees: dict[str, Any] = field(default_factory=dict)

    @property
    def manquements(self) -> list[VerdictArticle]:
        return [v for v in self.verdicts if v.verdict is Verdict.MANQUEMENT]

    @property
    def a_reviser(self) -> list[VerdictArticle]:
        return [v for v in self.verdicts if v.revue_humaine_requise]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "tenant_id": self.tenant_id,
            "score": round(self.score, 1),
            "detail_score": self.detail_score,
            "metadonnees": self.metadonnees,
            "synthese": {
                "articles_evalues": len(self.verdicts),
                "conformes": sum(1 for v in self.verdicts if v.verdict is Verdict.CONFORME),
                "manquements": len(self.manquements),
                "hors_perimetre": sum(
                    1 for v in self.verdicts if v.verdict is Verdict.HORS_PERIMETRE
                ),
                "indetermines": sum(
                    1 for v in self.verdicts if v.verdict is Verdict.INDETERMINE
                ),
                "a_reviser": len(self.a_reviser),
            },
            "verdicts": [v.to_dict() for v in self.verdicts],
        }
