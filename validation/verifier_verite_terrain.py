"""Verifie la STRUCTURE d'un fichier de verite terrain (meme format que
corpus/verite_terrain.json, Tache 7) -- pas son CONTENU. Ce script ne juge
jamais si un verdict pose par l'equipe est correct : seulement si le fichier
est bien forme et interne cohérent, pour attraper une faute de frappe avant
qu'elle ne fausse une mesure.

    python -m validation.verifier_verite_terrain --referentiel nis2
    python -m validation.verifier_verite_terrain --verite corpus/verite_terrain.json --corpus corpus

Sans --corpus, la coherence avec les fichiers .txt presents n'est pas
verifiee (seule la structure du JSON l'est).

Code de sortie 0 si aucune erreur (des avertissements peuvent subsister),
1 sinon.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

VERDICTS_VALIDES = {"conforme", "manquement", "hors_perimetre", "tolere"}
_CLE_ARTICLE_RE = re.compile(r"^\d+(-\d+)?$")


def _verifier_cle_article(cle: str) -> bool:
    """Un article seul ("5") ou un groupe ("15-22"), bornes croissantes."""
    if not _CLE_ARTICLE_RE.match(cle):
        return False
    if "-" in cle:
        debut, fin = (int(x) for x in cle.split("-"))
        return debut < fin
    return True


def verifier(donnees: dict, corpus_dir: pathlib.Path | None) -> tuple[list[str], list[str]]:
    """Renvoie (erreurs, avertissements). Ne modifie jamais `donnees`."""
    erreurs: list[str] = []
    avertissements: list[str] = []

    if "cas" not in donnees:
        erreurs.append("Cle racine 'cas' manquante.")
        return erreurs, avertissements
    cas_liste = donnees["cas"]
    if not isinstance(cas_liste, list):
        erreurs.append("'cas' doit etre une liste.")
        return erreurs, avertissements
    if not cas_liste:
        avertissements.append("'cas' est vide : squelette valide, mais aucun document annote pour l'instant.")

    fichiers_vus: set[str] = set()

    for i, cas in enumerate(cas_liste):
        prefixe = f"cas[{i}]"
        if not isinstance(cas, dict):
            erreurs.append(f"{prefixe} : doit etre un objet JSON.")
            continue

        fichier = cas.get("fichier")
        if not fichier or not isinstance(fichier, str):
            erreurs.append(f"{prefixe} : 'fichier' manquant ou vide.")
        else:
            if not fichier.endswith(".txt"):
                avertissements.append(f"{prefixe} ({fichier}) : ne se termine pas par .txt.")
            if fichier in fichiers_vus:
                erreurs.append(f"{prefixe} : '{fichier}' apparait plusieurs fois dans 'cas'.")
            fichiers_vus.add(fichier)
            if corpus_dir is not None and not (corpus_dir / fichier).exists():
                erreurs.append(f"{prefixe} ({fichier}) : absent de {corpus_dir}.")

        score_attendu = cas.get("score_attendu")
        if (
            not isinstance(score_attendu, list)
            or len(score_attendu) != 2
            or not all(isinstance(x, (int, float)) for x in score_attendu)
        ):
            erreurs.append(f"{prefixe} : 'score_attendu' doit etre [bas, haut].")
        else:
            bas, haut = score_attendu
            if not (0 <= bas <= haut <= 100):
                erreurs.append(
                    f"{prefixe} : score_attendu {score_attendu} invalide "
                    "(attendu 0 <= bas <= haut <= 100)."
                )

        verdicts = cas.get("verdicts_attendus")
        if not isinstance(verdicts, dict) or not verdicts:
            erreurs.append(f"{prefixe} : 'verdicts_attendus' manquant ou vide.")
            verdicts = {}
        else:
            for cle, verdict in verdicts.items():
                if not _verifier_cle_article(cle):
                    erreurs.append(
                        f"{prefixe} : cle d'article invalide '{cle}' "
                        "(attendu \"5\" ou \"15-22\", bornes croissantes)."
                    )
                if verdict not in VERDICTS_VALIDES:
                    erreurs.append(
                        f"{prefixe} : verdict invalide '{verdict}' pour '{cle}' "
                        f"(attendu l'un de {sorted(VERDICTS_VALIDES)})."
                    )

        jamais_exclure = cas.get("jamais_exclure", [])
        if not isinstance(jamais_exclure, list):
            erreurs.append(f"{prefixe} : 'jamais_exclure' doit etre une liste.")
        else:
            for cle in jamais_exclure:
                if cle not in verdicts:
                    erreurs.append(
                        f"{prefixe} : jamais_exclure reference '{cle}', "
                        "absent de verdicts_attendus."
                    )
                elif verdicts[cle] == "hors_perimetre":
                    erreurs.append(
                        f"{prefixe} : jamais_exclure contient '{cle}', dont le "
                        "verdict attendu est deja 'hors_perimetre' -- contradictoire."
                    )

    if corpus_dir is not None and corpus_dir.exists():
        for txt in sorted(corpus_dir.glob("*.txt")):
            if txt.name not in fichiers_vus:
                avertissements.append(
                    f"{txt.name} present dans {corpus_dir} mais absent de 'cas' "
                    "(document non annote -- il sera ignore par evaluate.py)."
                )

    return erreurs, avertissements


def main() -> int:
    from validation.evaluate import REFERENTIELS_NON_RGPD

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--referentiel", choices=sorted(REFERENTIELS_NON_RGPD),
        help="fixe --verite et --corpus a partir du referentiel (ex. nis2 -> "
             "corpus_nis2/verite_terrain.json et corpus_nis2/)",
    )
    parser.add_argument("--verite", type=pathlib.Path, help="fichier de verite terrain a verifier")
    parser.add_argument("--corpus", type=pathlib.Path,
                        help="dossier de documents .txt (verifie que chaque "
                             "'fichier' annote existe reellement)")
    args = parser.parse_args()

    if args.referentiel:
        defaut_corpus, defaut_verite = REFERENTIELS_NON_RGPD[args.referentiel]
        verite_path = args.verite or defaut_verite
        corpus_dir = args.corpus or defaut_corpus
    elif args.verite:
        verite_path = args.verite
        corpus_dir = args.corpus
    else:
        parser.error("preciser --referentiel ou --verite.")
        return 2  # pragma: no cover - argparse.error() n'atteint jamais ici

    if not verite_path.exists():
        print(f"Introuvable : {verite_path}", file=sys.stderr)
        return 1

    try:
        donnees = json.loads(verite_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"JSON invalide dans {verite_path} : {exc}", file=sys.stderr)
        return 1

    if not isinstance(donnees, dict):
        print(f"{verite_path} : la racine du JSON doit etre un objet.", file=sys.stderr)
        return 1

    erreurs, avertissements = verifier(donnees, corpus_dir)

    print(f"Verite terrain : {verite_path}")
    print(f"Corpus         : {corpus_dir if corpus_dir else '(non fourni, coherence avec les .txt non verifiee)'}")
    print(f"Cas annotes    : {len(donnees.get('cas', []))}\n")

    for a in avertissements:
        print(f"  [ATTENTION] {a}")
    for e in erreurs:
        print(f"  [ERREUR] {e}")

    if erreurs:
        print(f"\nÉCHEC : {len(erreurs)} erreur(s).")
        return 1
    print("\nOK : structure valide" + (f", {len(avertissements)} avertissement(s)." if avertissements else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
