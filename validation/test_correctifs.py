#!/usr/bin/env python3
"""
Tests des correctifs issus du premier run Groq.

Chaque test correspond à une erreur réellement observée en validation.
Ils empêchent la régression de ces quatre défauts précis.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.evaluateur import Evaluateur  # noqa: E402
from evaluation.schemas import Verdict  # noqa: E402
from rag.chunking import decouper  # noqa: E402
from referentiel.articles import article  # noqa: E402

VERT, ROUGE, NEUTRE = "\033[92m", "\033[91m", "\033[0m"
resultats: list[tuple[str, bool, str]] = []

DOC_AVEC_PRESTATAIRES = """POLITIQUE DE CONFIDENTIALITÉ

DESTINATAIRES
Les données peuvent être transmises à notre cabinet comptable, à notre assureur
décennal et à notre prestataire informatique, tous établis en France.

SECURITE
Les données sont chiffrées au repos et les accès sont nominatifs.
"""


def verifier(nom: str, condition: bool, detail: str = "") -> None:
    resultats.append((nom, condition, detail))
    marque = f"{VERT}PASS{NEUTRE}" if condition else f"{ROUGE}ÉCHEC{NEUTRE}"
    print(f"  [{marque}] {nom}" + (f"\n           {detail}" if detail and not condition else ""))


class ClientExclusion:
    """Simule le comportement observé : le modèle écarte l'article du périmètre."""

    def __init__(self, mode: str) -> None:
        self.mode = mode

    def __call__(self, systeme: str, utilisateur: str) -> str:
        if "CONDITION D'APPLICABILITÉ DE L'ARTICLE" in utilisateur:
            if self.mode == "exclusion_sans_preuve":
                return json.dumps({
                    "applicable": False, "condition_remplie": False, "citation": None,
                    "justification": "le document ne mentionne pas de prestataires tiers",
                })
            if self.mode == "exclusion_citation_fausse":
                return json.dumps({
                    "applicable": False, "condition_remplie": False,
                    "citation": "l'organisme n'a recours à aucun prestataire extérieur",
                    "justification": "aucun sous-traitant",
                })
            if self.mode == "exclusion_prouvee":
                return json.dumps({
                    "applicable": False, "condition_remplie": False,
                    "citation": "tous établis en France",
                    "justification": "aucun transfert hors UE",
                })
            return json.dumps({"applicable": True, "condition_remplie": True,
                               "citation": None, "justification": "ok"})

        if "DÉROGATIONS POSSIBLES" in utilisateur:
            return json.dumps({"reference": None, "citation": None, "justification": "aucune"})

        cles = re.findall(r'cle="([^"]+)"', utilisateur)
        return json.dumps({"elements": [
            {"cle": c, "satisfait": False, "citation": None, "commentaire": "absent"}
            for c in cles
        ]})


def main() -> int:
    print("=" * 74)
    print("TESTS DES CORRECTIFS — issus du run Groq du corpus de démonstration")
    print("=" * 74)

    art28 = article("28")
    passages = decouper(DOC_AVEC_PRESTATAIRES)

    print("\n1. Exclusion abusive du périmètre (observée sur l'article 28)")

    ev = Evaluateur(client=ClientExclusion("exclusion_sans_preuve"), reessais=0)
    v = ev.evaluer_article(art28, passages, DOC_AVEC_PRESTATAIRES)
    verifier(
        "Exclusion sans citation → article maintenu dans le périmètre",
        v.verdict is not Verdict.HORS_PERIMETRE,
        f"obtenu : {v.verdict.value}",
    )
    verifier(
        "Le refus d'exclusion est tracé dans les diagnostics",
        any("exclusion refusée" in d for d in v.diagnostics),
        f"diagnostics : {v.diagnostics}",
    )

    ev = Evaluateur(client=ClientExclusion("exclusion_citation_fausse"), reessais=0)
    v = ev.evaluer_article(art28, passages, DOC_AVEC_PRESTATAIRES)
    verifier(
        "Exclusion sur citation fabriquée → article maintenu dans le périmètre",
        v.verdict is not Verdict.HORS_PERIMETRE,
        f"obtenu : {v.verdict.value}",
    )

    ev = Evaluateur(client=ClientExclusion("exclusion_prouvee"), reessais=0)
    v = ev.evaluer_article(article("44-49"), passages, DOC_AVEC_PRESTATAIRES)
    verifier(
        "Exclusion sur citation vérifiée → hors périmètre accepté",
        v.verdict is Verdict.HORS_PERIMETRE,
        f"obtenu : {v.verdict.value} — une exclusion légitime doit rester possible",
    )

    print("\n2. Dérogations non appréciables lors d'un audit documentaire (article 34)")
    art34 = article("34")
    verifier(
        "Les dérogations 34(3) sont exclues de la passe",
        len(art34.derogations_ex_ante) == 0,
        f"proposées : {[d.reference for d in art34.derogations_ex_ante]}",
    )
    verifier(
        "Elles restent au référentiel à titre documentaire",
        len(art34.derogations) == 3,
    )
    art9 = article("9")
    verifier(
        "Les dérogations de l'article 9(2) restent appréciables sur pièces",
        len(art9.derogations_ex_ante) == 10,
        f"proposées : {len(art9.derogations_ex_ante)}/10",
    )

    print("\n3. Éléments exigeant une appréciation plutôt qu'une extraction")
    art5, art6 = article("5"), article("6")
    verifier(
        "Article 5 : la minimisation n'est plus bloquante",
        not next(e for e in art5.elements_attendus if e.cle == "minimisation").bloquant,
    )
    verifier(
        "Article 6 : la cohérence base/finalité n'est plus bloquante",
        not next(e for e in art6.elements_attendus if e.cle == "adequation").bloquant,
    )
    verifier(
        "Article 6 : la base légale identifiée reste bloquante",
        next(e for e in art6.elements_attendus if e.cle == "base_identifiee").bloquant,
    )

    print("\n4. Énumération des droits ≠ capacité à les honorer (article 15-22)")
    art1522 = article("15-22")
    intitules = " ".join(e.intitule for e in art1522.elements_attendus)
    verifier(
        "Les intitulés exigent un moyen d'honorer le droit, pas sa mention",
        "moyen" in intitules.lower(),
    )
    verifier(
        "Ils écartent explicitement la simple énumération du droit",
        "ne suffit pas" in intitules and "ÉNUMÉRATION" in intitules,
    )

    print("\n5. Citations partagées et multiples (observé sur art. 13, 30, 37)")
    import json as _json

    class ClientCitations:
        """Réutilise une même phrase pour plusieurs éléments, et en cumule deux."""

        def __call__(self, systeme: str, utilisateur: str) -> str:
            if "CONDITION D'APPLICABILITÉ DE L'ARTICLE" in utilisateur:
                return _json.dumps({"applicable": True, "condition_remplie": True,
                                    "citation": None, "justification": "ok"})
            if "DÉROGATIONS POSSIBLES" in utilisateur:
                return _json.dumps({"reference": None, "citation": None, "justification": ""})
            cles = re.findall(r'cle="([^"]+)"', utilisateur)
            partagee = ("Les données peuvent être transmises à notre cabinet comptable, "
                        "à notre assureur")
            sortie = []
            for i, c in enumerate(cles):
                if i == 0:
                    sortie.append({"cle": c, "satisfait": True,
                                   "citations": [partagee, "Les données sont chiffrées au repos"],
                                   "commentaire": "deux passages"})
                else:
                    sortie.append({"cle": c, "satisfait": True, "citation": partagee,
                                   "commentaire": "phrase partagée"})
            return _json.dumps({"elements": sortie}, ensure_ascii=False)

    ev = Evaluateur(client=ClientCitations(), reessais=0)
    v = ev.evaluer_article(article("28"), passages, DOC_AVEC_PRESTATAIRES)
    verifier(
        "Une même citation vaut pour plusieurs éléments",
        v.verdict is Verdict.CONFORME,
        f"obtenu : {v.verdict.value} — diagnostics {v.diagnostics}",
    )
    verifier(
        "Un élément accepte plusieurs citations vérifiées",
        v.preuves[0].retenue and " […] " in (v.preuves[0].citation or ""),
        f"citation : {v.preuves[0].citation}",
    )

    echecs = [n for n, ok, _ in resultats if not ok]
    print("\n" + "=" * 74)
    print(f"{len(resultats) - len(echecs)}/{len(resultats)} tests réussis")
    if echecs:
        print(f"{ROUGE}ÉCHECS :{NEUTRE}")
        for n in echecs:
            print(f"  - {n}")
        return 1
    print(f"{VERT}Les quatre correctifs sont opérants.{NEUTRE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
