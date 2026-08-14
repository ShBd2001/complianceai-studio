#!/usr/bin/env python3
"""
Validation et non-régression du moteur d'audit.

    python -m validation.run_validation --corpus ./corpus --verite verite_terrain.json
    python -m validation.run_validation --corpus ./corpus --verite vt.json --repetitions 3
    python -m validation.run_validation --corpus ./corpus --verite vt.json --ci

En mode --ci, le script sort avec le code 1 si un seuil bloquant est violé.
Le mode --repetitions vide le cache entre chaque exécution : c'est la seule
manière de mesurer une reproductibilité réelle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Permet l'exécution depuis n'importe quel répertoire
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv

    for candidat in (Path.cwd() / ".env", Path.cwd() / "backend" / ".env"):
        if candidat.exists():
            load_dotenv(candidat)
            break
except ImportError:
    pass

from evaluation.evaluateur import Evaluateur  # noqa: E402
from evaluation.scoring import niveau  # noqa: E402
from validation.harnais import (  # noqa: E402
    Metriques,
    SeuilsCI,
    charger_verite_terrain,
    comparer,
    mesurer_reproductibilite,
    rapport_texte,
    tous_seuils_ok,
)


def construire_client(hors_ligne: bool):
    if hors_ligne:
        from validation.client_factice import ClientFactice

        return ClientFactice()
    from evaluation.client_llm import ClientGroq

    return ClientGroq(cache_actif=False)  # cache désactivé pour la validation


def main() -> int:
    ap = argparse.ArgumentParser(description="Validation du moteur d'audit RGPD")
    ap.add_argument("--corpus", required=True, help="dossier des documents de test")
    ap.add_argument("--verite", required=True, help="fichier JSON de vérité terrain")
    ap.add_argument("--repetitions", type=int, default=1, help="exécutions par document")
    ap.add_argument("--sortie", default="rapport_validation.json")
    ap.add_argument("--ci", action="store_true", help="code de sortie 1 si seuil violé")
    ap.add_argument("--hors-ligne", action="store_true", help="client factice, sans appel API")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    cas_liste = charger_verite_terrain(args.verite)
    client = construire_client(args.hors_ligne)
    evaluateur = Evaluateur(client=client)

    metriques = Metriques()
    tous_rapports: dict[str, list] = {}
    sortie_json: dict = {"documents": [], "configuration": {}}

    print("=" * 74)
    print(f"VALIDATION — {len(cas_liste)} documents, {args.repetitions} exécution(s)")
    if args.repetitions > 1:
        print("Cache vidé entre chaque exécution.")
    print("=" * 74)

    for cas in cas_liste:
        chemin = corpus / cas.fichier
        if not chemin.exists():
            print(f"  MANQUANT : {chemin}")
            continue

        texte = chemin.read_text(encoding="utf-8", errors="replace")
        rapports = []

        for i in range(args.repetitions):
            if hasattr(client, "vider_cache"):
                client.vider_cache()
            rapports.append(
                evaluateur.evaluer_document(
                    texte, nom=cas.fichier, tenant_id="validation"
                )
            )

        principal = rapports[0]
        tous_rapports[cas.fichier] = rapports

        bas, haut = cas.score_attendu
        dans = "OK  " if bas <= principal.score <= haut else "ÉCART"

        print()
        print(f"{cas.fichier}  —  {cas.description}")
        print(f"  Passages   : {principal.metadonnees.get('passages')} "
              f"({principal.metadonnees.get('sections')} sections)")
        print(f"  Score      : {principal.score} (attendu {bas:g}-{haut:g})  [{dans}]")
        print(f"  Niveau     : {niveau(principal.score)}")

        ecarts = comparer(cas, principal, metriques)
        corrects = len(cas.verdicts_attendus) - len(
            [e for e in ecarts if "EXCLUSION ABUSIVE" not in e]
        )
        print(f"  Articles   : {corrects}/{len(cas.verdicts_attendus)} corrects")
        for ligne in ecarts:
            print(ligne)

        if principal.a_reviser:
            print(f"  À réviser  : {len(principal.a_reviser)} article(s) sous seuil de confiance")

        sortie_json["documents"].append(principal.to_dict())

    # La reproductibilité ne se mesure que sur des exécutions RÉPÉTÉES DU MÊME
    # document. Comparer des documents différents entre eux ne mesure rien.
    repro = (
        _repro_multi(tous_rapports)
        if args.repetitions >= 2
        else {
            "mesurable": False,
            "motif": "une seule exécution par document — relancer avec --repetitions 3",
        }
    )

    seuils = SeuilsCI()
    print()
    print(rapport_texte(metriques, repro, seuils))

    sortie_json["configuration"] = {
        "repetitions": args.repetitions,
        "client": type(client).__name__,
        **(client.versions() if hasattr(client, "versions") else {}),
    }
    sortie_json["metriques"] = {
        "exactitude": round(metriques.exactitude, 4),
        "precision": round(metriques.precision, 4),
        "rappel": round(metriques.rappel, 4),
        "f1": round(metriques.f1, 4),
        "faux_positifs": metriques.faux_positifs,
        "faux_negatifs": metriques.faux_negatifs,
        "exclusions_abusives": metriques.exclusions_abusives,
        "reproductibilite": repro,
    }
    Path(args.sortie).write_text(
        json.dumps(sortie_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nRapport détaillé écrit dans {args.sortie}")

    if args.ci and not tous_seuils_ok(metriques, repro, seuils):
        print("\nÉCHEC : au moins un seuil bloquant est violé.")
        return 1
    return 0


def _repro_multi(tous_rapports: dict[str, list]) -> dict:
    """Agrège la reproductibilité mesurée document par document."""
    from statistics import pstdev

    ecarts, instables, total_articles = [], [], 0
    for fichier, rapports in tous_rapports.items():
        if len(rapports) < 2:
            continue
        r = mesurer_reproductibilite(rapports)
        ecarts.append(r["ecart_type_score"])
        instables.extend(f"{fichier}:art.{a}" for a in r["articles_instables"])
        total_articles += len(rapports[0].verdicts)

    if not ecarts:
        return {"mesurable": False, "motif": "une seule exécution par document"}

    return {
        "mesurable": True,
        "executions": max(len(r) for r in tous_rapports.values()),
        "ecart_type_score": round(max(ecarts), 3),
        "ecart_type_moyen": round(sum(ecarts) / len(ecarts), 3),
        "articles_instables": instables,
        "taux_stabilite": round(1 - len(instables) / max(1, total_articles), 4),
    }


if __name__ == "__main__":
    raise SystemExit(main())
