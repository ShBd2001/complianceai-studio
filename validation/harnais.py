"""
Harnais de validation et de non-régression.

Différences avec le script d'origine :
  - la reproductibilité est mesurée cache DÉSACTIVÉ, sinon elle ne mesure rien ;
  - les exclusions abusives (obligation réelle écartée) sont un critère bloquant
    distinct, car c'est l'erreur la plus grave d'un outil d'audit ;
  - un intervalle de confiance accompagne l'exactitude : sur 66 articles, ±7
    points, ce qui interdit de conclure quoi que ce soit d'une variation de 3 points ;
  - des seuils bloquants font échouer le run en CI.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluation.schemas import RapportAudit, Verdict


@dataclass
class SeuilsCI:
    """Seuils bloquants. Un run qui les viole doit faire échouer la CI."""

    rappel_min: float = 0.90
    precision_min: float = 0.95
    exactitude_min: float = 0.90
    exclusions_abusives_max: int = 0
    score_hors_intervalle_max: int = 1
    verdicts_instables_max: float = 0.0
    taux_indetermines_max: float = 0.05


@dataclass
class CasDeTest:
    """Vérité terrain d'un document. Posée à la main, article par article."""

    fichier: str
    description: str
    score_attendu: tuple[float, float]
    # article -> "conforme" | "manquement" | "hors_perimetre"
    verdicts_attendus: dict[str, str]
    # Articles dont l'exclusion serait ABUSIVE : obligations réellement dues.
    # Les écarter est une faute grave, suivie séparément.
    jamais_exclure: list[str] = field(default_factory=list)

    @classmethod
    def depuis_dict(cls, d: dict[str, Any]) -> "CasDeTest":
        return cls(
            fichier=d["fichier"],
            description=d.get("description", ""),
            score_attendu=tuple(d["score_attendu"]),  # type: ignore[arg-type]
            verdicts_attendus=d["verdicts_attendus"],
            jamais_exclure=d.get("jamais_exclure", []),
        )


def charger_verite_terrain(chemin: str | Path) -> list[CasDeTest]:
    donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    return [CasDeTest.depuis_dict(d) for d in donnees["cas"]]


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------

def wilson(succes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance de Wilson — fiable sur petits effectifs."""
    if total == 0:
        return 0.0, 0.0
    p = succes / total
    d = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / d
    demi = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / d
    return max(0.0, centre - demi), min(1.0, centre + demi)


@dataclass
class Metriques:
    articles_total: int = 0
    articles_corrects: int = 0
    vrais_positifs: int = 0   # manquement réel détecté
    faux_positifs: int = 0    # manquement annoncé à tort
    faux_negatifs: int = 0    # manquement réel non détecté
    exclusions_correctes: int = 0
    exclusions_attendues: int = 0
    exclusions_abusives: list[str] = field(default_factory=list)
    indetermines: int = 0
    scores_dans_intervalle: int = 0
    documents: int = 0
    ecarts_score: list[float] = field(default_factory=list)
    confusions: Counter = field(default_factory=Counter)
    articles_fautifs: Counter = field(default_factory=Counter)

    @property
    def exactitude(self) -> float:
        return self.articles_corrects / self.articles_total if self.articles_total else 0.0

    @property
    def precision(self) -> float:
        d = self.vrais_positifs + self.faux_positifs
        return self.vrais_positifs / d if d else 1.0

    @property
    def rappel(self) -> float:
        d = self.vrais_positifs + self.faux_negatifs
        return self.vrais_positifs / d if d else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.rappel
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def taux_indetermines(self) -> float:
        return self.indetermines / self.articles_total if self.articles_total else 0.0


def comparer(cas: CasDeTest, rapport: RapportAudit, m: Metriques) -> list[str]:
    """Confronte un rapport à sa vérité terrain. Renvoie les écarts lisibles."""
    ecarts: list[str] = []
    obtenus = {v.article: v for v in rapport.verdicts}

    for numero, attendu in cas.verdicts_attendus.items():
        v = obtenus.get(numero)
        if v is None:
            ecarts.append(f"    art. {numero:<8} ATTENDU {attendu:<15} NON ÉVALUÉ")
            m.articles_total += 1
            m.articles_fautifs[numero] += 1
            continue

        obtenu = v.verdict.value
        m.articles_total += 1

        if v.verdict is Verdict.INDETERMINE:
            m.indetermines += 1

        if obtenu == attendu:
            m.articles_corrects += 1
        else:
            m.confusions[(attendu, obtenu)] += 1
            m.articles_fautifs[numero] += 1
            ecarts.append(
                f"    art. {numero:<8} attendu {attendu:<15} obtenu {obtenu:<15}"
                + (f"  [{v.justification[:60]}]" if v.justification else "")
            )

        if attendu == "manquement":
            if obtenu == "manquement":
                m.vrais_positifs += 1
            else:
                m.faux_negatifs += 1
        elif obtenu == "manquement":
            m.faux_positifs += 1

        if attendu == "hors_perimetre":
            m.exclusions_attendues += 1
            if obtenu == "hors_perimetre":
                m.exclusions_correctes += 1

        if numero in cas.jamais_exclure and obtenu == "hors_perimetre":
            m.exclusions_abusives.append(f"{cas.fichier}:art.{numero}")
            ecarts.append(
                f"    art. {numero:<8} EXCLUSION ABUSIVE — obligation réelle écartée du périmètre"
            )

    bas, haut = cas.score_attendu
    if bas <= rapport.score <= haut:
        m.scores_dans_intervalle += 1
        ecart = 0.0
    else:
        ecart = min(abs(rapport.score - bas), abs(rapport.score - haut))
    m.ecarts_score.append(ecart)
    m.documents += 1

    return ecarts


def mesurer_reproductibilite(rapports: list[RapportAudit]) -> dict[str, Any]:
    """
    À n'appeler QUE sur des exécutions cache vidé.

    Un écart-type nul obtenu avec un cache actif ne mesure rien : il faut le
    déclarer explicitement dans le rapport pour ne pas se prévaloir d'un
    déterminisme fictif.
    """
    if len(rapports) < 2:
        return {"mesurable": False, "motif": "moins de deux exécutions"}

    scores = [r.score for r in rapports]
    par_article: dict[str, set[str]] = {}
    for r in rapports:
        for v in r.verdicts:
            par_article.setdefault(v.article, set()).add(v.verdict.value)

    instables = [a for a, s in par_article.items() if len(s) > 1]
    return {
        "mesurable": True,
        "executions": len(rapports),
        "ecart_type_score": round(statistics.pstdev(scores), 3),
        "amplitude_score": round(max(scores) - min(scores), 3),
        "articles_instables": instables,
        "taux_stabilite": round(1 - len(instables) / max(1, len(par_article)), 4),
    }


# ---------------------------------------------------------------------------
# Restitution
# ---------------------------------------------------------------------------

def rapport_texte(m: Metriques, repro: dict[str, Any], seuils: SeuilsCI) -> str:
    L = []
    sep = "=" * 74
    L.append(sep)
    L.append("MÉTRIQUES GLOBALES")
    L.append(sep)

    bas, haut = wilson(m.articles_corrects, m.articles_total)
    L.append(
        f"  Exactitude              : {m.exactitude:.1%} sur {m.articles_total} articles"
    )
    L.append(
        f"    IC 95 %               : [{bas:.1%} — {haut:.1%}]"
        f"   (largeur {100 * (haut - bas):.1f} pts)"
    )
    if haut - bas > 0.10:
        L.append(
            "    ATTENTION : intervalle trop large pour conclure. "
            "Élargir le corpus de validation."
        )

    L.append("")
    L.append("  Détection des manquements")
    L.append(f"    Précision             : {m.precision:.1%}  (un manquement annoncé est réel)")
    L.append(f"    Rappel                : {m.rappel:.1%}  (un manquement réel est détecté)")
    L.append(f"    F1                    : {m.f1:.1%}")
    L.append(f"    Faux positifs         : {m.faux_positifs}")
    L.append(f"    Faux négatifs         : {m.faux_negatifs}")

    L.append("")
    L.append("  Périmètre")
    taux_excl = (
        m.exclusions_correctes / m.exclusions_attendues if m.exclusions_attendues else 1.0
    )
    L.append(
        f"    Exclusions correctes  : {m.exclusions_correctes}/{m.exclusions_attendues} ({taux_excl:.1%})"
    )
    L.append(f"    Exclusions abusives   : {len(m.exclusions_abusives)}")
    for e in m.exclusions_abusives:
        L.append(f"        {e}")

    L.append("")
    L.append("  Score de conformité")
    L.append(f"    Dans l'intervalle     : {m.scores_dans_intervalle}/{m.documents} documents")
    moyen = sum(m.ecarts_score) / len(m.ecarts_score) if m.ecarts_score else 0.0
    L.append(f"    Écart moyen           : {moyen:.1f} points")
    if m.rappel < 0.90:
        L.append(
            "    Note : le rappel étant faible, les scores sont mécaniquement "
            "surévalués. Cet écart moyen est flatté et ne doit pas être mis en avant."
        )

    L.append("")
    L.append("  Reproductibilité")
    if not repro.get("mesurable"):
        L.append(f"    Non mesurée ({repro.get('motif', '')})")
    else:
        L.append(f"    Exécutions (cache vidé): {repro['executions']}")
        L.append(f"    Écart-type du score   : {repro['ecart_type_score']} points")
        L.append(f"    Verdicts stables      : {repro['taux_stabilite']:.1%}")
        if repro["articles_instables"]:
            L.append(f"    Articles instables    : {', '.join(repro['articles_instables'])}")

    if m.confusions:
        L.append("")
        L.append("  Confusions les plus fréquentes")
        for (att, obt), n in m.confusions.most_common(5):
            L.append(f"    {att:<15} → {obt:<15} ×{n}")

    if m.articles_fautifs:
        L.append("")
        L.append("  Articles les plus souvent erronés (à corriger en priorité)")
        for art, n in m.articles_fautifs.most_common(5):
            L.append(f"    art. {art:<10} {n} erreur(s)")

    L.append("")
    L.append(sep)
    L.append("SEUILS BLOQUANTS")
    L.append(sep)
    for libelle, ok, valeur, seuil in evaluer_seuils(m, repro, seuils):
        L.append(f"  [{'OK ' if ok else 'ÉCHEC'}] {libelle:<34} {valeur:<12} (seuil {seuil})")

    return "\n".join(L)


def evaluer_seuils(
    m: Metriques, repro: dict[str, Any], s: SeuilsCI
) -> list[tuple[str, bool, str, str]]:
    instables = 1 - repro.get("taux_stabilite", 1.0) if repro.get("mesurable") else 0.0
    return [
        ("Rappel", m.rappel >= s.rappel_min, f"{m.rappel:.1%}", f"≥ {s.rappel_min:.0%}"),
        ("Précision", m.precision >= s.precision_min, f"{m.precision:.1%}", f"≥ {s.precision_min:.0%}"),
        ("Exactitude", m.exactitude >= s.exactitude_min, f"{m.exactitude:.1%}", f"≥ {s.exactitude_min:.0%}"),
        (
            "Exclusions abusives",
            len(m.exclusions_abusives) <= s.exclusions_abusives_max,
            str(len(m.exclusions_abusives)),
            f"≤ {s.exclusions_abusives_max}",
        ),
        (
            "Scores hors intervalle",
            (m.documents - m.scores_dans_intervalle) <= s.score_hors_intervalle_max,
            str(m.documents - m.scores_dans_intervalle),
            f"≤ {s.score_hors_intervalle_max}",
        ),
        (
            "Verdicts instables",
            instables <= s.verdicts_instables_max,
            f"{instables:.1%}",
            f"≤ {s.verdicts_instables_max:.0%}",
        ),
        (
            "Taux d'indéterminés",
            m.taux_indetermines <= s.taux_indetermines_max,
            f"{m.taux_indetermines:.1%}",
            f"≤ {s.taux_indetermines_max:.0%}",
        ),
    ]


def tous_seuils_ok(m: Metriques, repro: dict[str, Any], s: SeuilsCI) -> bool:
    return all(ok for _, ok, _, _ in evaluer_seuils(m, repro, s))
