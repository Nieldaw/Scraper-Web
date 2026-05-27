import argparse
import asyncio
import sys
from pathlib import Path

# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper, AnibisParseError
from immo_ne_collector.scrapers.http_fetcher import (
    ScraperHTTPError,
    ScraperTimeoutError,
    fetch_html_to_cache,
)
from immo_ne_collector.scrapers.safety import SafetyConfig
from immo_ne_collector.services.anibis_filters import filter_collection_batch
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.exports import export_all_csv
from immo_ne_collector.services.persistence import persist_collection_batch
from immo_ne_collector.services.quality import export_quality_report_csv

DEFAULT_ANIBIS_NE_SALE_URL = (
    "https://www.anibis.ch/fr/q/immobilier-neuchatel-appartements-maisons-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZKpYXBhcnRtZW50pWhvdXNlkqlwcmljZVR5cGWjQlVZwMCRk6hsb2NhdGlv"
    "brRnZW8tY2FudG9uLW5ldWNoYXRlbMA?sorting=newest&page=1"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Flux contrôlé Anibis vente canton NE (fetch + parse + persist + exports)."
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_ANIBIS_NE_SALE_URL,
        help="URL Anibis à récupérer (défaut: vente NE actuelle).",
    )
    parser.add_argument("--max-listings", type=int, default=None, help="Limiter le nombre d'annonces traitées.")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Ne pas télécharger et réutiliser un cache local.",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=None,
        help="Chemin du cache HTML local (obligatoire si --skip-fetch).",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Collecter/persister uniquement, sans générer les exports CSV.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout HTTP fetch en secondes (optionnel).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=None,
        help="Nombre de retries HTTP fetch (optionnel).",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_listings is not None and args.max_listings < 1:
        raise ValueError("--max-listings must be >= 1")
    if args.skip_fetch and args.cache_path is None:
        raise ValueError("--skip-fetch requires --cache-path")
    if args.timeout is not None and args.timeout <= 0:
        raise ValueError("--timeout must be > 0")
    if args.retries is not None and args.retries < 0:
        raise ValueError("--retries must be >= 0")


def _build_fetch_safety(timeout: float | None, retries: int | None) -> SafetyConfig:
    return SafetyConfig(
        timeout_seconds=timeout if timeout is not None else 20.0,
        max_retries=retries if retries is not None else 1,
        min_interval_seconds=1.0,
    )


async def _resolve_cache_file(args: argparse.Namespace) -> Path:
    if args.skip_fetch:
        assert args.cache_path is not None
        return args.cache_path

    safety = _build_fetch_safety(args.timeout, args.retries)
    result = await fetch_html_to_cache(
        url=args.url,
        cache_dir=ROOT / "data" / "cache" / "html",
        source="anibis_sale_ne",
        safety=safety,
    )
    print(f"HTTP status: {result.status_code}")
    print(f"Saved file size: {result.size_bytes} bytes")
    return result.file_path


async def _run(args: argparse.Namespace) -> int:
    try:
        _validate_args(args)
    except ValueError as exc:
        print(str(exc))
        return 2

    try:
        cache_path = await _resolve_cache_file(args)
    except ScraperHTTPError as exc:
        print(f"HTTP error: {exc.status_code} for {exc.url}")
        return 1
    except ScraperTimeoutError as exc:
        print(f"Timeout error: {exc}")
        return 1
    except Exception as exc:
        print(f"Network or fetch error: {exc}")
        return 1

    scraper = AnibisCachedHtmlScraper(html_path=cache_path, source="anibis_cached")
    try:
        batch = await collect_and_normalize(scraper)
    except AnibisParseError as exc:
        print(f"Parse error: {exc}")
        return 1

    filtered_batch, stats = filter_collection_batch(
        batch,
        max_listings=args.max_listings,
        transaction_type="sale",
        canton="NE",
    )
    persistence_result = await persist_collection_batch(filtered_batch)

    export_paths: dict[str, Path] = {}
    if not args.no_export:
        output_dir = ROOT / "data" / "exports"
        export_results = await export_all_csv(output_dir=output_dir)
        async with AsyncSessionLocal() as session:
            quality_result = await export_quality_report_csv(
                session,
                output_dir / "quality_report.csv",
            )
        export_paths = {item.name: item.path for item in export_results}
        export_paths[quality_result.name] = quality_result.path

    print("Summary:")
    print(f"- URL used: {args.url}")
    print(f"- Cache file: {cache_path}")
    print(f"- Total listings detected: {stats.detected_total}")
    print(
        "- sale/rent/unknown: "
        f"{stats.transaction_counts.get('sale', 0)}/"
        f"{stats.transaction_counts.get('rent', 0)}/"
        f"{stats.transaction_counts.get('unknown', 0)}"
    )
    print(f"- Kept by canton NE: {stats.kept_canton_count}")
    print(f"- Excluded out of canton: {stats.excluded_canton_count}")
    if stats.excluded_examples:
        print("- Examples excluded:")
        for example in stats.excluded_examples:
            print(f"  - {example}")

    print(f"- Collected: {persistence_result.collected_count}")
    print(f"- Created: {persistence_result.created_count}")
    print(f"- Updated: {persistence_result.updated_count}")
    print(f"- Unchanged: {persistence_result.unchanged_count}")
    print(f"- Errors: {len(persistence_result.errors)}")
    if persistence_result.errors:
        for error in persistence_result.errors:
            print(f"  - {error}")

    if export_paths:
        print("- Export files:")
        if "VENTES" in export_paths:
            print(f"  - ventes.csv: {export_paths['VENTES']}")
        if "MASTER" in export_paths:
            print(f"  - master.csv: {export_paths['MASTER']}")
        if "QUALITY_REPORT" in export_paths:
            print(f"  - quality_report.csv: {export_paths['QUALITY_REPORT']}")

    return 0 if not persistence_result.errors else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
