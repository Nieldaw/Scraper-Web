"""Collecte quotidienne: orchestre la collecte vente multi-source par canton, la persistance,
les exports CSV et l'enregistrement du run dans `daily_runs`.

La logique de collecte vit dans `scripts/collect_sale_by_canton.py` (fetch prudent, cache HTML,
parsing, filtre canton, persistance). Ce job la reutilise telle quelle pour ne pas la dupliquer.

Usage:
    python -m immo_ne_collector.jobs.daily_collect                # Romandie, anibis+lookmove
    python -m immo_ne_collector.jobs.daily_collect --canton NE --max-pages 2 --no-export
Les options sont celles de `scripts/collect_sale_by_canton.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import DailyRun
from immo_ne_collector.services.run_diagnostics import build_source_detail, overall_status

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "collect_sale_by_canton.py"

DEFAULT_MAX_PAGES = 3


def _load_collect_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("collect_sale_by_canton", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parse_args(script: ModuleType, argv: list[str] | None) -> argparse.Namespace:
    parser = script._build_parser()
    parser.description = "Collecte quotidienne (vente) avec suivi dans daily_runs."
    parser.set_defaults(max_pages=DEFAULT_MAX_PAGES, use_cache=True)
    args = parser.parse_args(argv)
    if not args.canton and not args.all_romandie:
        args.all_romandie = True
    return args


async def _start_run() -> DailyRun:
    async with AsyncSessionLocal() as session:
        run = DailyRun(status="RUNNING", stats={})
        session.add(run)
        await session.commit()
        return run


async def _finish_run(run: DailyRun, *, status: str, stats: dict, error: str | None) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(DailyRun, run.id)
        if row is None:
            return
        row.status = status
        row.finished_at = datetime.now(UTC)
        row.stats = stats
        row.error = error
        await session.commit()


async def run_daily_collection(argv: list[str] | None = None) -> int:
    script = _load_collect_script()
    args = _parse_args(script, argv)
    try:
        script._validate_args(args)
        sources = script.parse_sources_csv(args.sources)
        cantons = script._resolve_cantons(args)
    except ValueError as exc:
        print(str(exc))
        return 2

    run = await _start_run()
    print(f"Daily run {run.id} started: cantons={','.join(cantons)} sources={','.join(sources)}")

    summaries_by_canton: dict[str, list] = {}
    details: list[dict] = []
    hard_errors: list[str] = []
    export_errors: list[str] = []
    status = "SUCCESS"
    fatal: str | None = None

    try:
        for canton in cantons:
            summaries, errors = await script._run_canton(canton=canton, sources=sources, args=args)
            summaries_by_canton[canton] = summaries
            details.extend(build_source_detail(canton, s) for s in summaries)
            hard_errors.extend(errors)
            for summary in summaries:
                script._print_source_summary(canton=canton, summary=summary)

            if args.no_export:
                continue
            try:
                await script._generate_exports_by_canton(canton=canton)
            except Exception as exc:  # un echec d'export ne doit pas perdre la collecte
                export_errors.append(f"{canton}: {exc}")
                print(f"Export error for canton {canton}: {exc}")
    except Exception as exc:
        status = "FAILED"
        fatal = f"{exc}\n{traceback.format_exc()}"
        print(f"Daily run aborted: {exc}")

    all_summaries = [s for group in summaries_by_canton.values() for s in group]
    failures = sum(1 for s in all_summaries if s.source_status == "FAIL")
    warnings = sum(1 for s in all_summaries if s.source_status == "WARNING")
    status = overall_status(
        fatal=status == "FAILED",
        failures=failures,
        warnings=warnings,
        export_errors=len(export_errors),
    )

    stats = {
        "cantons": cantons,
        "sources": sources,
        "pages_fetched": sum(s.fetched_pages for s in all_summaries),
        "pages_from_cache": sum(s.loaded_from_cache_pages for s in all_summaries),
        "pages_parsed": sum(s.parsed_pages for s in all_summaries),
        "detected": sum(s.detected_total for s in all_summaries),
        "collected": sum(s.collected_count for s in all_summaries),
        "created": sum(s.created_count for s in all_summaries),
        "updated": sum(s.updated_count for s in all_summaries),
        "unchanged": sum(s.unchanged_count for s in all_summaries),
        "source_warnings": warnings,
        "source_failures": failures,
        "details": details,
        "options": {
            "max_pages": args.max_pages,
            "max_listings": args.max_listings,
            "enrich_details": getattr(args, "enrich_details", None),
            "max_details": getattr(args, "max_details", None),
        },
        "errors": [*hard_errors, *[e for s in all_summaries for e in s.errors], *export_errors][
            :50
        ],
    }
    await _finish_run(run, status=status, stats=stats, error=fatal)

    print(
        f"Daily run {run.id} {status}: collected={stats['collected']} created={stats['created']} "
        f"updated={stats['updated']} unchanged={stats['unchanged']} "
        f"warnings={warnings} failures={failures}"
    )
    return 0 if status in {"SUCCESS", "WARNING"} else 1


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(run_daily_collection(argv)))


if __name__ == "__main__":
    main()
