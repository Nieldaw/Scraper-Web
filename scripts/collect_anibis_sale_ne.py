import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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
MAX_ALLOWED_PAGES = 10


def _set_query_param(url: str, *, key: str, value: str) -> str:
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params[key] = value
    return urlunparse(parsed._replace(query=urlencode(params)))


def _build_anibis_page_urls(base_url: str, max_pages: int) -> list[str]:
    return [_set_query_param(base_url, key="page", value=str(page)) for page in range(1, max_pages + 1)]


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
    parser.add_argument("--max-pages", type=int, default=1, help="Nombre maximum de pages à parcourir (défaut: 1).")
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
    if args.max_pages < 1:
        raise ValueError("--max-pages must be >= 1")
    if args.max_pages > MAX_ALLOWED_PAGES:
        raise ValueError(f"--max-pages must be <= {MAX_ALLOWED_PAGES}")
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


async def _fetch_pages(args: argparse.Namespace) -> tuple[list[Path], int]:
    if args.skip_fetch:
        assert args.cache_path is not None
        if args.max_pages > 1:
            print("Info: --skip-fetch fourni, une seule page cache sera parsée.")
        return [args.cache_path], 0

    safety = _build_fetch_safety(args.timeout, args.retries)
    cache_paths: list[Path] = []
    page_urls = _build_anibis_page_urls(args.url, args.max_pages)
    for idx, page_url in enumerate(page_urls, start=1):
        result = await fetch_html_to_cache(
            url=page_url,
            cache_dir=ROOT / "data" / "cache" / "html",
            source="anibis_sale_ne",
            safety=safety,
        )
        print(f"Page {idx}: HTTP status={result.status_code} size={result.size_bytes} path={result.file_path}")
        cache_paths.append(result.file_path)
    return cache_paths, len(cache_paths)


async def _run(args: argparse.Namespace) -> int:
    try:
        _validate_args(args)
    except ValueError as exc:
        print(str(exc))
        return 2

    try:
        cache_paths, fetched_pages = await _fetch_pages(args)
    except ScraperHTTPError as exc:
        print(f"HTTP error: {exc.status_code} for {exc.url}")
        return 1
    except ScraperTimeoutError as exc:
        print(f"Timeout error: {exc}")
        return 1
    except Exception as exc:
        print(f"Network or fetch error: {exc}")
        return 1

    remaining = args.max_listings
    parsed_pages = 0
    total_detected = 0
    total_kept_ne = 0
    total_excluded = 0
    tx_sale = 0
    tx_rent = 0
    tx_unknown = 0

    total_collected = 0
    total_created = 0
    total_updated = 0
    total_unchanged = 0
    all_errors: list[str] = []

    for cache_path in cache_paths:
        if remaining is not None and remaining <= 0:
            break

        scraper = AnibisCachedHtmlScraper(html_path=cache_path, source="anibis_cached")
        try:
            batch = await collect_and_normalize(scraper)
        except AnibisParseError as exc:
            print(f"Parse error ({cache_path}): {exc}")
            return 1

        filtered_batch, stats = filter_collection_batch(
            batch,
            max_listings=remaining,
            transaction_type="sale",
            canton="NE",
        )
        persistence_result = await persist_collection_batch(filtered_batch)

        parsed_pages += 1
        total_detected += stats.detected_total
        total_kept_ne += stats.kept_canton_count
        total_excluded += stats.excluded_canton_count
        tx_sale += stats.transaction_counts.get("sale", 0)
        tx_rent += stats.transaction_counts.get("rent", 0)
        tx_unknown += stats.transaction_counts.get("unknown", 0)

        total_collected += persistence_result.collected_count
        total_created += persistence_result.created_count
        total_updated += persistence_result.updated_count
        total_unchanged += persistence_result.unchanged_count
        all_errors.extend(persistence_result.errors)

        if remaining is not None:
            remaining = max(0, remaining - filtered_batch.collected_count)

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
    print(f"- URL base: {args.url}")
    print(f"- Pages requested: {args.max_pages}")
    print(f"- Pages fetched: {fetched_pages if not args.skip_fetch else 0}")
    print(f"- Pages parsed: {parsed_pages}")
    print(f"- Cache files created/used: {len(cache_paths)}")
    for cache_path in cache_paths:
        print(f"  - {cache_path}")
    print(f"- Total listings detected: {total_detected}")
    print(f"- sale/rent/unknown detected: {tx_sale}/{tx_rent}/{tx_unknown}")
    print(f"- Kept by canton NE: {total_kept_ne}")
    print(f"- Excluded out of canton: {total_excluded}")
    print(f"- Collected: {total_collected}")
    print(f"- Created: {total_created}")
    print(f"- Updated: {total_updated}")
    print(f"- Unchanged: {total_unchanged}")
    print(f"- Errors: {len(all_errors)}")
    if all_errors:
        for error in all_errors:
            print(f"  - {error}")

    if export_paths:
        print("- Export files:")
        if "VENTES" in export_paths:
            print(f"  - ventes.csv: {export_paths['VENTES']}")
        if "MASTER" in export_paths:
            print(f"  - master.csv: {export_paths['MASTER']}")
        if "QUALITY_REPORT" in export_paths:
            print(f"  - quality_report.csv: {export_paths['QUALITY_REPORT']}")

    return 0 if not all_errors else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
