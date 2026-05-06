#!/usr/bin/env python3
"""
Tests des garde-fous. À exécuter en CI avant toute mise en production.

Ces tests ne mesurent pas la qualité du modèle : ils vérifient que le système
reste sûr même si le modèle se comporte mal. Un modèle qui hallucine, qui
affirme sans preuve ou qui invente une dérogation ne doit pas pouvoir produire
un verdict de conformité.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.evaluateur import Evaluateur  # noqa: E402
from evaluation.schemas import Verdict  # noqa: E402
from evaluation.scoring import calculer_score  # noqa: E402
from evaluation.verificateur import verifier_citation  # noqa: E402
from referentiel.articles import article  # noqa: E402

DOCUMENT = """POLITIQUE INTERNE

SECURITE
Les accès sont nominatifs et chaque connexion est journalisée dans un registre
technique conservé six mois. Les données sont chiffrées au repos.

GOUVERNANCE
La direction a désigné un référent informatique chargé du suivi des incidents.
"""

VERT, ROUGE, NEUTRE = "\033[92m", "\033[91m", "\033[0m"
resultats: list[tuple[str, bool, str]] = []


def verifier(nom: str, condition: bool, detail: str = "") -> None:
    resultats.append((nom, condition, detail))
    marque = f"{VERT}PASS{NEUTRE}" if condition else f"{ROUGE}ÉCHEC{NEUTRE}"
    print(f"  [{marque}] {nom}" + (f"\n           {detail}" if detail and not condition else ""))


class ClientMenteur:
    """Simule un modèle qui affirme la conformité en fabriquant ses citations."""

    def __init__(self, mode: str) -> None:
        self.mode = mode

    def __call__(self, systeme: str, utilisateur: str) -> str:
        if "CONDITION D'APPLICABILITÉ DE L'ARTICLE" in utilisateur:
            return json.dumps({"applicable": True, "citation": None, "justification": "test"})

        if "DÉROGATIONS POSSIBLES" in utilisateur:
            if self.mode == "derogation_inventee":
                return json.dumps({
                    "reference": "9(2)(z)",
                    "citation": "le cabinet bénéficie d'une exemption générale de conformité",
                    "justification": "dérogation fictive",
                })
            if self.mode == "derogation_non_citee":
                return json.dumps({
                    "reference": "9(2)(h)", "citation": None,
                    "justification": "affirmée sans preuve",
                })
            return json.dumps({"reference": None, "citation": None, "justification": "aucune"})

        import re
        cles = re.findall(r'cle="([^"]+)"', utilisateur)
        if self.mode == "citation_fabriquee":
            faux = ("Le responsable de traitement tient un registre complet des activités "
                    "de traitement, mis à jour trimestriellement et validé par la direction.")
            return json.dumps({"elements": [
                {"cle": c, "satisfait": True, "citation": faux, "commentaire": "inventé"}
                for c in cles
            ]})
        if self.mode == "sans_citation":
            return json.dumps({"elements": [
                {"cle": c, "satisfait": True, "citation": None, "commentaire": "affirmé"}
                for c in cles
            ]})
        if self.mode == "citation_trop_courte":
            return json.dumps({"elements": [
                {"cle": c, "satisfait": True, "citation": "SECURITE", "commentaire": "tronqué"}
                for c in cles
            ]})
        if self.mode == "reponse_invalide":
            return "je ne peux pas répondre en JSON désolé"
        return json.dumps({"elements": []})


def main() -> int:
    print("=" * 74)
    print("TESTS DES GARDE-FOUS")
    print("=" * 74)

    # -- 1. vérificateur de citations ------------------------------------
    print("\n1. Vérificateur de citations")
    verifier(
        "Une citation littérale est acceptée",
        verifier_citation("Les données sont chiffrées au repos", DOCUMENT).valide,
    )
    verifier(
        "Une reformulation mineure est tolérée",
        verifier_citation("les donnees sont chiffrees au repos.", DOCUMENT).valide,
    )
    verifier(
        "Une citation fabriquée est rejetée",
        verifier_citation(
            "Le responsable tient un registre complet mis à jour trimestriellement", DOCUMENT
        ).rejetee,
    )
    verifier(
        "Une citation trop courte est rejetée",
        verifier_citation("chiffrées", DOCUMENT).rejetee,
    )
    verifier("Une citation vide est rejetée", verifier_citation("", DOCUMENT).rejetee)

    # -- 2. verdict par défaut -------------------------------------------
    print("\n2. Verdict par défaut et rejet des affirmations non prouvées")
    art30 = article("30")

    for mode, libelle in [
        ("citation_fabriquee", "Citations fabriquées → manquement, jamais conforme"),
        ("sans_citation", "Conformité affirmée sans citation → manquement"),
        ("citation_trop_courte", "Citation trop courte → manquement"),
        ("reponse_invalide", "Réponse illisible du modèle → manquement, pas de plantage"),
    ]:
        ev = Evaluateur(client=ClientMenteur(mode), reessais=0)
        from rag.chunking import decouper

        v = ev.evaluer_article(art30, decouper(DOCUMENT), DOCUMENT)
        verifier(libelle, v.verdict is Verdict.MANQUEMENT, f"obtenu : {v.verdict.value}")

    ev = Evaluateur(client=ClientMenteur("citation_fabriquee"), reessais=0)
    from rag.chunking import decouper

    v = ev.evaluer_article(art30, decouper(DOCUMENT), DOCUMENT)
    verifier(
        "Une preuve rejetée fait basculer en revue humaine",
        v.revue_humaine_requise,
        f"confiance={v.confiance:.2f}",
    )
    verifier(
        "Le motif de rejet est tracé dans le rapport",
        any(p.motif_rejet for p in v.preuves),
    )

    # -- 3. dérogations ---------------------------------------------------
    print("\n3. Passe de vérification des dérogations")
    art9 = article("9")

    ev = Evaluateur(client=ClientMenteur("derogation_inventee"), reessais=0)
    v = ev.evaluer_article(art9, decouper(DOCUMENT), DOCUMENT)
    verifier(
        "Une dérogation inexistante est ignorée",
        v.derogation is None and v.verdict is not Verdict.HORS_PERIMETRE,
        f"obtenu : {v.verdict.value}",
    )

    ev = Evaluateur(client=ClientMenteur("derogation_non_citee"), reessais=0)
    v = ev.evaluer_article(art9, decouper(DOCUMENT), DOCUMENT)
    verifier(
        "Une dérogation réelle mais non citée est écartée",
        v.derogation is None,
        "une dérogation sans preuve textuelle ne doit jamais écarter un manquement",
    )
    verifier(
        "Les 10 dérogations de l'article 9(2) sont au référentiel",
        len(art9.derogations) == 10,
        f"trouvées : {len(art9.derogations)}",
    )
    verifier(
        "La dérogation 9(2)(h) — soins — est présente",
        any(d.reference == "9(2)(h)" for d in art9.derogations),
    )

    # -- 4. scoring -------------------------------------------------------
    print("\n4. Score")
    from evaluation.schemas import Preuve, VerdictArticle

    hors = VerdictArticle("37", "DPO", 3, Verdict.HORS_PERIMETRE)
    conf = VerdictArticle("32", "Sécurité", 5, Verdict.CONFORME)
    score_a, detail_a = calculer_score([conf, hors])
    score_b, _ = calculer_score([conf])
    verifier(
        "Un article hors périmètre est exclu du dénominateur, pas compté conforme",
        score_a == score_b == 100.0,
        f"avec exclusion={score_a}, sans={score_b}",
    )

    partiel = VerdictArticle(
        "30", "Registre", 4, Verdict.MANQUEMENT,
        preuves=[
            Preuve("a", "A", "cit", True, verifiee=True),
            Preuve("b", "B", None, False),
            Preuve("c", "C", None, False),
            Preuve("d", "D", None, False),
        ],
    )
    total = VerdictArticle(
        "30", "Registre", 4, Verdict.MANQUEMENT,
        preuves=[Preuve(k, k, None, False) for k in "abcd"],
    )
    s_partiel, _ = calculer_score([partiel])
    s_total, _ = calculer_score([total])
    verifier(
        "Un manquement partiel score plus qu'un manquement total",
        s_partiel > s_total,
        f"partiel={s_partiel}, total={s_total}",
    )
    verifier(
        "Un manquement ne dépasse jamais 50 % du crédit",
        s_partiel <= 50.0,
        f"obtenu : {s_partiel}",
    )
    verifier(
        "Le détail du score est explicable ligne par ligne",
        "formule" in detail_a and detail_a["lignes"],
    )

    # -- 5. chunking ------------------------------------------------------
    print("\n5. Découpage")
    passages = decouper(DOCUMENT)
    verifier("Le document produit plusieurs passages", len(passages) > 1, f"{len(passages)}")
    verifier(
        "Chaque passage est rattaché à une section",
        all(p.section for p in passages),
    )
    verifier(
        "Les offsets permettent de retrouver le texte source",
        all(DOCUMENT[p.debut : p.fin] == p.texte for p in passages),
    )

    # -- synthèse ---------------------------------------------------------
    echecs = [n for n, ok, _ in resultats if not ok]
    print("\n" + "=" * 74)
    print(f"{len(resultats) - len(echecs)}/{len(resultats)} tests réussis")
    if echecs:
        print(f"{ROUGE}ÉCHECS :{NEUTRE}")
        for n in echecs:
            print(f"  - {n}")
        return 1
    print(f"{VERT}Tous les garde-fous sont opérants.{NEUTRE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
