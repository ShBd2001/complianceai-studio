"""Interface en ligne de commande de l'ingestion.

    python -m app.ingestion.cli --dry-run          # affiche sans ecrire
    python -m app.ingestion.cli                    # ingere les trois textes
    python -m app.ingestion.cli --only rgpd        # un seul referentiel
    python -m app.ingestion.cli --force            # recree meme si inchange
    python -m app.ingestion.cli --only rgpd --fichier rgpd.html   # copie locale

EUR-Lex limite les acces automatises et repond alors 202 Accepted sans servir le
texte. Enregistrer la page depuis un navigateur puis utiliser --fichier rend
l'ingestion reproductible, ce qui est preferable en demonstration.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.db.session import SessionLocal
from app.ingestion.crosswalks import seed_crosswalks
from app.ingestion.eurlex import SOURCES
from app.ingestion.runner import ingest_all

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")


def dry_run(codes: list[str], fichier=None) -> int:
    """Affiche ce qui serait extrait, sans toucher a la base.

    A utiliser au premier lancement : si EUR-Lex a modifie sa structure HTML,
    le probleme se voit immediatement ici plutot qu'apres une ecriture.
    """
    from app.ingestion.runner import _connector_for

    failures = 0
    for code in codes:
        connector = _connector_for(code, fichier)
        origine = getattr(connector, "url", "texte consolide (API Cellar)")
        print(f"\n{'=' * 70}\n{code.upper()} — {origine}\n{'=' * 70}")
        try:
            result = connector.fetch()
        except Exception as exc:
            print(f"  ECHEC : {exc}")
            failures += 1
            continue

        print(f"  Empreinte SHA-256 : {result.sha256}")
        print(f"  Articles extraits  : {len(result.requirements)}")
        print(f"  Longueur du texte  : {len(result.raw_text)} caracteres\n")
        for req in result.requirements[:5]:
            body = req.body.replace("\n", " ")[:110]
            print(f"  [{req.reference}] {req.title[:60]}")
            print(f"      {body}...")
        if len(result.requirements) > 5:
            print(f"  ... et {len(result.requirements) - 5} autres articles.")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestion des referentiels reglementaires.")
    parser.add_argument("--only", nargs="*", choices=sorted(SOURCES), help="referentiels cibles")
    parser.add_argument("--dry-run", action="store_true", help="afficher sans ecrire en base")
    parser.add_argument("--force", action="store_true", help="reingerer meme si inchange")
    parser.add_argument(
        "--fichier",
        help="copie locale du texte HTML, au lieu du telechargement depuis EUR-Lex",
    )
    parser.add_argument(
        "--crosswalks", action="store_true",
        help="peupler/actualiser les correspondances indicatives entre referentiels",
    )
    args = parser.parse_args()

    if args.crosswalks:
        with SessionLocal() as db:
            for message in seed_crosswalks(db):
                print(f" - {message}")
            db.commit()
        return 0

    codes = args.only or sorted(SOURCES)

    if args.dry_run:
        return 1 if dry_run(codes, fichier=args.fichier) else 0

    with SessionLocal() as db:
        reports = ingest_all(db, codes, force=args.force, fichier=args.fichier)
        db.commit()

    print()
    for report in reports:
        icon = {"created": "+", "updated": "~", "unchanged": "=", "failed": "!"}[report.status]
        print(
            f" {icon} {report.code:10} {report.status:10} "
            f"{report.requirements:4} exigences, {report.auditable:3} auditables"
        )
        if report.message:
            print(f"     {report.message}")

    return 1 if any(r.status == "failed" for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
