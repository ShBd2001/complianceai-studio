#!/usr/bin/env python3
"""
Comparaison des retrievers sur un corpus identique.

    python -m validation.comparer_retrievers --corpus corpus \
           --verite corpus/verite_terrain.json

Une seule variable change entre les trois exécutions : la fonction de retrieval.
Le reste — grille, prompts, vérification, scoring — est strictement identique.
C'est ce qui rend la comparaison exploitable.

Ajouter --lexical-seul pour vérifier le harnais sans installer torch.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    for candidat in (Path.cwd() / ".env", Path.cwd() / "backend" / ".env"):
        if candidat.exists():
            load_dotenv(candidat)
            break
except ImportError:
    pass

from evaluation.evaluateur import Evaluateur, retriever_lexical  # noqa: E402
from validation.harnais import (  # noqa: E402
    Metriques,
    charger_verite_terrain,
    comparer,
)


def mesurer(nom, retriever, cas_liste, corpus, client) -> dict:
    evaluateur = Evaluateur(client=client, retriever=retriever)
    m = Metriques()
    debut = time.time()
    fautifs: dict[str, int] = {}

    print(f"\n{'=' * 74}\n{nom}\n{'=' * 74}")
    for cas in cas_liste:
        chemin = corpus / cas.fichier
        if not chemin.exists():
            continue
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        rapport = evaluateur.evaluer_document(
            texte, nom=cas.fichier, tenant_id="comparaison"
        )
        ecarts = comparer(cas, rapport, m)
        for e in ecarts:
            if "art." in e:
                art = e.split("art.")[1].split()[0]
                fautifs[art] = fautifs.get(art, 0) + 1
        marque = "OK " if not ecarts else f"{len(ecarts)} écart(s)"
        print(f"  {cas.fichier:<40} {rapport.score:>6.1f}  {marque}")

    duree = time.time() - debut
    print(
        f"\n  exactitude {m.exactitude:.1%} | précision {m.precision:.1%} | "
        f"rappel {m.rappel:.1%} | F1 {m.f1:.1%}"
    )
    print(
        f"  faux positifs {m.faux_positifs} | faux négatifs {m.faux_negatifs} | "
        f"exclusions abusives {len(m.exclusions_abusives)} | {duree:.0f}s"
    )
    if fautifs:
        pires = sorted(fautifs.items(), key=lambda x: -x[1])[:4]
        print("  articles erronés : " + ", ".join(f"art.{a} ×{n}" for a, n in pires))

    return {
        "retriever": nom,
        "exactitude": round(m.exactitude, 4),
        "precision": round(m.precision, 4),
        "rappel": round(m.rappel, 4),
        "f1": round(m.f1, 4),
        "faux_positifs": m.faux_positifs,
        "faux_negatifs": m.faux_negatifs,
        "exclusions_abusives": len(m.exclusions_abusives),
        "articles_erronés": fautifs,
        "duree_s": round(duree, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--verite", required=True)
    ap.add_argument("--sortie", default="comparaison_retrievers.json")
    ap.add_argument("--lexical-seul", action="store_true",
                    help="n'exécute que le lexical (pas besoin de torch)")
    ap.add_argument("--hors-ligne", action="store_true")
    args = ap.parse_args()

    cas_liste = charger_verite_terrain(args.verite)
    corpus = Path(args.corpus)

    if args.hors_ligne:
        from validation.client_factice import ClientFactice

        client = ClientFactice()
    else:
        from evaluation.client_llm import ClientGroq

        client = ClientGroq(cache_actif=True)  # cache utile ici : mêmes prompts

    resultats = [mesurer("LEXICAL (référence)", retriever_lexical, cas_liste, corpus, client)]

    if not args.lexical_seul:
        from rag.retriever_semantique import RetrieverHybride, RetrieverLocal

        print("\nChargement du modèle d'embedding (première fois : téléchargement)…")
        semantique = RetrieverLocal()
        resultats.append(mesurer("SÉMANTIQUE", semantique, cas_liste, corpus, client))
        resultats.append(
            mesurer("HYBRIDE (lexical + sémantique)",
                    RetrieverHybride(semantique), cas_liste, corpus, client)
        )

    print(f"\n{'=' * 74}\nSYNTHÈSE\n{'=' * 74}")
    print(f"  {'retriever':<32}{'exact.':>9}{'préc.':>9}{'rappel':>9}{'FP':>6}{'FN':>5}")
    for r in resultats:
        print(
            f"  {r['retriever']:<32}{r['exactitude']:>8.1%}{r['precision']:>9.1%}"
            f"{r['rappel']:>9.1%}{r['faux_positifs']:>6}{r['faux_negatifs']:>5}"
        )

    if len(resultats) > 1:
        base = resultats[0]["exactitude"]
        meilleur = max(resultats, key=lambda r: r["exactitude"])
        gain = 100 * (meilleur["exactitude"] - base)
        print(f"\n  Meilleur : {meilleur['retriever']} ({gain:+.1f} points vs lexical)")
        if abs(gain) < 2:
            print(
                "  Écart inférieur à 2 points : non significatif sur 210 articles. "
                "Conserver le lexical, plus simple et sans dépendance lourde."
            )

    Path(args.sortie).write_text(
        json.dumps(resultats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  Résultats écrits dans {args.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
