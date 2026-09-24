"""Cout mesure des analyses terminees, par referentiel.

    python -m scripts.cout_analyses          # toutes les campagnes terminees
    python -m scripts.cout_analyses --framework rgpd

A lancer depuis le dossier backend/, avec DATABASE_URL pointant vers la base
a mesurer (locale ou production). Les chiffres proviennent uniquement des
campagnes deja executees APRES la migration 0016 (audits.duration_seconds
non nul) : une campagne plus ancienne, jamais rejouee depuis, n'a pas ces
compteurs et est ignoree plutot que comptee pour zero.

Alimente les chiffres du memoire et du business plan (nombre d'appels,
jetons, duree, cout estime) -- voir AuditOut.estimated_llm_cost_usd et le
TODO sur LLM_PRICE_INPUT_PER_MTOK_USD / LLM_PRICE_OUTPUT_PER_MTOK_USD dans
app/core/config.py : sans ce tarif rempli, le cout estime reste a None.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from statistics import mean

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.audit import Audit
from app.models.enums import AuditStatus, Framework


def _cout_estime(prompt_tokens: int, completion_tokens: int) -> float | None:
    if not settings.LLM_PRICE_INPUT_PER_MTOK_USD and not settings.LLM_PRICE_OUTPUT_PER_MTOK_USD:
        return None
    return round(
        prompt_tokens / 1_000_000 * settings.LLM_PRICE_INPUT_PER_MTOK_USD
        + completion_tokens / 1_000_000 * settings.LLM_PRICE_OUTPUT_PER_MTOK_USD,
        6,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Cout mesure des analyses, par referentiel.")
    parser.add_argument("--framework", choices=[f.value for f in Framework], help="limiter a un referentiel")
    args = parser.parse_args()

    with SessionLocal() as db:
        stmt = select(Audit).where(
            Audit.status == AuditStatus.COMPLETED,
            Audit.duration_seconds.is_not(None),
        )
        if args.framework:
            stmt = stmt.where(Audit.framework == args.framework)
        audits = list(db.scalars(stmt))

    if not audits:
        print("Aucune campagne mesuree (duration_seconds non renseigne : executer une analyse "
              "apres la migration 0016 pour produire des chiffres).")
        return 0

    par_framework: dict[str, list[Audit]] = defaultdict(list)
    for audit in audits:
        par_framework[audit.framework.value].append(audit)

    print(f"{len(audits)} campagne(s) mesuree(s), sur {len(par_framework)} referentiel(s).\n")

    for framework, lot in sorted(par_framework.items()):
        calls = [a.llm_calls or 0 for a in lot]
        tokens = [(a.llm_prompt_tokens or 0) + (a.llm_completion_tokens or 0) for a in lot]
        durees = [a.duration_seconds or 0.0 for a in lot]
        couts = [
            _cout_estime(a.llm_prompt_tokens or 0, a.llm_completion_tokens or 0)
            for a in lot
        ]
        couts_connus = [c for c in couts if c is not None]

        print(f"=== {framework.upper()} ({len(lot)} campagne(s)) ===")
        print(f"  Appels au modele   : moyenne {mean(calls):.1f}, max {max(calls)}")
        print(f"  Jetons totaux      : moyenne {mean(tokens):.0f}, max {max(tokens)}")
        print(f"  Duree              : moyenne {mean(durees):.1f}s, max {max(durees):.1f}s")
        if couts_connus:
            print(f"  Cout estime (USD)  : moyenne ${mean(couts_connus):.4f}, max ${max(couts_connus):.4f}")
        else:
            print("  Cout estime (USD)  : non disponible (LLM_PRICE_* non renseigne, voir config.py)")
        degradees = sum(1 for a in lot if a.degraded)
        if degradees:
            print(f"  Mode degrade       : {degradees}/{len(lot)} campagne(s)")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
