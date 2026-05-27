import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlunparse

# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from bs4 import BeautifulSoup

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property
from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper, AnibisParseError
from immo_ne_collector.scrapers.http_fetcher import (
    ScraperHTTPError,
    ScraperTimeoutError,
    fetch_html_to_cache,
)
from immo_ne_collector.scrapers.lookmove import LookmoveCachedHtmlScraper, LookmoveParseError
from immo_ne_collector.scrapers.safety import SafetyConfig
from immo_ne_collector.services.anibis_filters import FilterStats, filter_collection_batch
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.deduplication import (
    ListingCandidate,
    MatchOutcome,
    decide_property_match,
)
from immo_ne_collector.services.exports import export_all_csv
from immo_ne_collector.services.persistence import PersistenceResult, persist_collection_batch
from immo_ne_collector.services.quality import export_quality_report_csv

DEFAULT_ANIBIS_NE_SALE_URL = (
    "https://www.anibis.ch/fr/q/immobilier-neuchatel-appartements-maisons-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZKpYXBhcnRtZW50pWhvdXNlkqlwcmljZVR5cGWjQlVZwMCRk6hsb2NhdGlv"
    "brRnZW8tY2FudG9uLW5ldWNoYXRlbMA?sorting=newest&page=1"
)
DEFAULT_LOOKMOVE_NE_SALE_URL = (
    "https://www.lookmove.ch/fr/immobilier/acheter/"
    "appartements-maisons%2C3/neuchatel-ne%2C100013"
)
MAX_ALLOWED_PAGES = 10


@dataclass(frozen=True)
class SourceRunResult:
    name: str
    cache_path: Path
    stats: FilterStats
    persistence: PersistenceResult


@dataclass(frozen=True)
class SourceFetchResult:
    name: str
    cache_paths: list[Path]
    pages_fetched: int
    notes: list[str]


def _set_query_param(url: str, *, key: str, value: str) -> str:
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params[key] = value
    return urlunparse(parsed._replace(query=urlencode(params)))


def _build_anibis_page_urls(base_url: str, max_pages: int) -> list[str]:
    return [_set_query_param(base_url, key="page", value=str(page)) for page in range(1, max_pages + 1)]


def _extract_lookmove_next_page_url(html_text: str, current_url: str) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")
    for selector in ("link[rel='next'][href]", "a[rel='next'][href]"):
        node = soup.select_one(selector)
        if node and node.get("href"):
            return urljoin(current_url, node["href"].strip())

    current_page = 1
    parsed_current = urlparse(current_url)
    values = parse_qs(parsed_current.query).get("page")
    if values:
        try:
            current_page = int(values[0])
        except ValueError:
            current_page = 1

    candidates: list[tuple[int, str]] = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        abs_href = urljoin(current_url, href)
        parsed = urlparse(abs_href)
        page_values = parse_qs(parsed.query).get("page")
        if not page_values:
            continue
        try:
            page_num = int(page_values[0])
        except ValueError:
            continue
        candidates.append((page_num, abs_href))

    target_page = current_page + 1
    for page_num, abs_href in candidates:
        if page_num == target_page:
            return abs_href
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collecte multi-source contrôlée Anibis+Lookmove vente NE.",
    )
    parser.add_argument("--max-listings", type=int, default=None, help="Nombre max d'annonces par source après filtres.")
    parser.add_argument("--max-pages", type=int, default=1, help="Nombre max de pages par source (défaut: 1).")

    parser.add_argument("--skip-fetch-anibis", action="store_true", help="Réutiliser un cache Anibis existant.")
    parser.add_argument("--anibis-cache-path", type=Path, default=None, help="Chemin cache Anibis requis si --skip-fetch-anibis.")

    parser.add_argument("--skip-fetch-lookmove", action="store_true", help="Réutiliser un cache Lookmove existant.")
    parser.add_argument("--lookmove-cache-path", type=Path, default=None, help="Chemin cache Lookmove requis si --skip-fetch-lookmove.")

    parser.add_argument("--anibis-url", default=DEFAULT_ANIBIS_NE_SALE_URL, help="URL Anibis (défaut: vente NE).")
    parser.add_argument("--lookmove-url", default=DEFAULT_LOOKMOVE_NE_SALE_URL, help="URL Lookmove (défaut: vente NE).")

    parser.add_argument("--no-export", action="store_true", help="Ne pas générer les exports CSV.")
    parser.add_argument("--timeout", type=float, default=None, help="Timeout HTTP en secondes (optionnel).")
    parser.add_argument("--retries", type=int, default=None, help="Nombre de retries HTTP (optionnel).")
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_listings is not None and args.max_listings < 1:
        raise ValueError("--max-listings must be >= 1")
    if args.max_pages < 1:
        raise ValueError("--max-pages must be >= 1")
    if args.max_pages > MAX_ALLOWED_PAGES:
        raise ValueError(f"--max-pages must be <= {MAX_ALLOWED_PAGES}")
    if args.skip_fetch_anibis and args.anibis_cache_path is None:
        raise ValueError("--skip-fetch-anibis requires --anibis-cache-path")
    if args.skip_fetch_lookmove and args.lookmove_cache_path is None:
        raise ValueError("--skip-fetch-lookmove requires --lookmove-cache-path")
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


async def _resolve_cache_file(
    *,
    skip_fetch: bool,
    cache_path: Path | None,
    url: str,
    source_name: str,
    timeout: float | None,
    retries: int | None,
) -> Path:
    if skip_fetch:
        assert cache_path is not None
        return cache_path

    result = await fetch_html_to_cache(
        url=url,
        cache_dir=ROOT / "data" / "cache" / "html",
        source=source_name,
        safety=_build_fetch_safety(timeout, retries),
    )
    print(f"[{source_name}] HTTP status: {result.status_code}")
    print(f"[{source_name}] Saved file size: {result.size_bytes} bytes")
    return result.file_path


async def _resolve_cache_files_for_source(
    *,
    name: str,
    skip_fetch: bool,
    cache_path: Path | None,
    url: str,
    source_name: str,
    timeout: float | None,
    retries: int | None,
    max_pages: int,
) -> SourceFetchResult:
    notes: list[str] = []
    if skip_fetch:
        assert cache_path is not None
        if max_pages > 1:
            notes.append(f"[{name}] --skip-fetch actif: une seule page cache sera parsée.")
        return SourceFetchResult(name=name, cache_paths=[cache_path], pages_fetched=0, notes=notes)

    if name == "anibis":
        cache_paths: list[Path] = []
        for page_url in _build_anibis_page_urls(url, max_pages):
            page_cache = await _resolve_cache_file(
                skip_fetch=False,
                cache_path=None,
                url=page_url,
                source_name=source_name,
                timeout=timeout,
                retries=retries,
            )
            cache_paths.append(page_cache)
        return SourceFetchResult(
            name=name,
            cache_paths=cache_paths,
            pages_fetched=len(cache_paths),
            notes=notes,
        )

    # Lookmove: detect pagination only if explicit in raw HTML.
    first_cache = await _resolve_cache_file(
        skip_fetch=False,
        cache_path=None,
        url=url,
        source_name=source_name,
        timeout=timeout,
        retries=retries,
    )
    cache_paths = [first_cache]
    pages_fetched = 1
    if max_pages == 1:
        return SourceFetchResult(name=name, cache_paths=cache_paths, pages_fetched=pages_fetched, notes=notes)

    current_url = url
    visited_urls = {current_url}
    current_html = first_cache.read_text(encoding="utf-8")
    while pages_fetched < max_pages:
        next_url = _extract_lookmove_next_page_url(current_html, current_url)
        if not next_url:
            notes.append("[lookmove] pagination non détectée proprement; arrêt prudent à 1 page.")
            break
        if next_url in visited_urls:
            notes.append("[lookmove] boucle pagination détectée; arrêt prudent.")
            break

        visited_urls.add(next_url)
        next_cache = await _resolve_cache_file(
            skip_fetch=False,
            cache_path=None,
            url=next_url,
            source_name=source_name,
            timeout=timeout,
            retries=retries,
        )
        cache_paths.append(next_cache)
        pages_fetched += 1
        current_url = next_url
        current_html = next_cache.read_text(encoding="utf-8")

    return SourceFetchResult(name=name, cache_paths=cache_paths, pages_fetched=pages_fetched, notes=notes)


def _combine_filter_stats(items: list[FilterStats]) -> FilterStats:
    tx = {"sale": 0, "rent": 0, "unknown": 0}
    excluded_examples: list[str] = []
    for row in items:
        tx["sale"] += row.transaction_counts.get("sale", 0)
        tx["rent"] += row.transaction_counts.get("rent", 0)
        tx["unknown"] += row.transaction_counts.get("unknown", 0)
        for example in row.excluded_examples:
            if len(excluded_examples) >= 5:
                break
            excluded_examples.append(example)
    return FilterStats(
        detected_total=sum(row.detected_total for row in items),
        transaction_counts=tx,
        kept_canton_count=sum(row.kept_canton_count for row in items),
        excluded_canton_count=sum(row.excluded_canton_count for row in items),
        excluded_examples=excluded_examples,
        filtered_count=sum(row.filtered_count for row in items),
    )


def _combine_persistence(items: list[PersistenceResult]) -> PersistenceResult:
    return PersistenceResult(
        daily_run_id=items[0].daily_run_id,
        collected_count=sum(row.collected_count for row in items),
        created_count=sum(row.created_count for row in items),
        updated_count=sum(row.updated_count for row in items),
        unchanged_count=sum(row.unchanged_count for row in items),
        errors=[error for row in items for error in row.errors],
    )


async def _collect_source(
    *,
    name: str,
    cache_path: Path,
    max_listings: int | None,
) -> SourceRunResult:
    if name == "anibis":
        scraper = AnibisCachedHtmlScraper(html_path=cache_path, source="anibis_cached")
        parse_error_type = AnibisParseError
    elif name == "lookmove":
        scraper = LookmoveCachedHtmlScraper(html_path=cache_path, source="lookmove_cached")
        parse_error_type = LookmoveParseError
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported source: {name}")

    try:
        batch = await collect_and_normalize(scraper)
    except parse_error_type as exc:
        raise RuntimeError(f"{name} parse error: {exc}") from exc

    filtered_batch, stats = filter_collection_batch(
        batch,
        max_listings=max_listings,
        transaction_type="sale",
        canton="NE",
    )
    persistence = await persist_collection_batch(filtered_batch)
    return SourceRunResult(name=name, cache_path=cache_path, stats=stats, persistence=persistence)


def _property_candidate(row: Property) -> ListingCandidate:
    return ListingCandidate(
        title=row.title,
        property_type=row.property_type,
        city=row.city,
        price_chf=row.price_chf,
        rooms=row.rooms,
        living_area_m2=row.living_area_m2,
        address_full=row.address_full,
    )


async def _print_dedup_summary() -> None:
    async with AsyncSessionLocal() as session:
        properties = (
            await session.execute(select(Property).options(selectinload(Property.listings)))
        ).scalars().all()

    total_properties = len(properties)
    total_source_listings = sum(len(row.listings) for row in properties)

    def listing_sources(row: Property) -> set[str]:
        return {item.source for item in row.listings if item.source}

    multi_source = [row for row in properties if len(listing_sources(row)) > 1]

    def has_anibis(row: Property) -> bool:
        return any(source.startswith("anibis") for source in listing_sources(row))

    def has_lookmove(row: Property) -> bool:
        return any(source.startswith("lookmove") for source in listing_sources(row))

    anibis_only = [row for row in properties if has_anibis(row) and not has_lookmove(row)]
    lookmove_only = [row for row in properties if has_lookmove(row) and not has_anibis(row)]

    print("Dedup summary:")
    print(f"- Total Property: {total_properties}")
    print(f"- Total SourceListing: {total_source_listings}")
    print(f"- Property multi-source: {len(multi_source)}")
    print(f"- Property Anibis-only: {len(anibis_only)}")
    print(f"- Property Lookmove-only: {len(lookmove_only)}")

    if multi_source:
        print("- Multi-source examples:")
        for row in multi_source[:5]:
            srcs = sorted(listing_sources(row))
            print(f"  - {row.id} | sources={srcs} | title={row.title or ''} | city={row.city or ''}")

    # Optional simple diagnostic: potentially close non-merged candidates.
    close_candidates: list[str] = []
    lookmove_candidates = [(row.id, _property_candidate(row)) for row in lookmove_only]
    for anibis_row in anibis_only:
        decision = decide_property_match(_property_candidate(anibis_row), lookmove_candidates)
        if decision.decision in {MatchOutcome.MATCH, MatchOutcome.AMBIGUOUS}:
            close_candidates.append(
                (
                    f"{anibis_row.id} -> score={decision.score} "
                    f"decision={decision.decision} reasons={decision.reasons}"
                )
            )

    if close_candidates:
        print("- Potentially close non-merged candidates:")
        for line in close_candidates[:5]:
            print(f"  - {line}")


async def _run(args: argparse.Namespace) -> int:
    try:
        _validate_args(args)
    except ValueError as exc:
        print(str(exc))
        return 2

    try:
        anibis_fetch = await _resolve_cache_files_for_source(
            name="anibis",
            skip_fetch=args.skip_fetch_anibis,
            cache_path=args.anibis_cache_path,
            url=args.anibis_url,
            source_name="anibis_sale_ne",
            timeout=args.timeout,
            retries=args.retries,
            max_pages=args.max_pages,
        )
        lookmove_fetch = await _resolve_cache_files_for_source(
            name="lookmove",
            skip_fetch=args.skip_fetch_lookmove,
            cache_path=args.lookmove_cache_path,
            url=args.lookmove_url,
            source_name="lookmove_sale_ne",
            timeout=args.timeout,
            retries=args.retries,
            max_pages=args.max_pages,
        )
    except ScraperHTTPError as exc:
        print(f"HTTP error: {exc.status_code} for {exc.url}")
        return 1
    except ScraperTimeoutError as exc:
        print(f"Timeout error: {exc}")
        return 1
    except Exception as exc:
        print(f"Network or fetch error: {exc}")
        return 1

    async def collect_paginated(fetch: SourceFetchResult) -> tuple[SourceRunResult, int]:
        per_page_results: list[SourceRunResult] = []
        remaining = args.max_listings
        parsed_pages = 0
        for cache in fetch.cache_paths:
            if remaining is not None and remaining <= 0:
                break
            result = await _collect_source(
                name=fetch.name,
                cache_path=cache,
                max_listings=remaining,
            )
            per_page_results.append(result)
            parsed_pages += 1
            if remaining is not None:
                remaining = max(0, remaining - result.persistence.collected_count)

        if not per_page_results:
            # No page parsed because max-listings=0 is blocked at validation,
            # so this branch is only defensive.
            raise RuntimeError(f"{fetch.name} parse error: no cache page parsed")

        combined = SourceRunResult(
            name=fetch.name,
            cache_path=per_page_results[0].cache_path,
            stats=_combine_filter_stats([row.stats for row in per_page_results]),
            persistence=_combine_persistence([row.persistence for row in per_page_results]),
        )
        return combined, parsed_pages

    try:
        anibis_result, anibis_pages_parsed = await collect_paginated(anibis_fetch)
        lookmove_result, lookmove_pages_parsed = await collect_paginated(lookmove_fetch)
    except Exception as exc:
        print(str(exc))
        return 1

    print("Source summaries:")
    for result, fetch_meta, pages_parsed in [
        (anibis_result, anibis_fetch, anibis_pages_parsed),
        (lookmove_result, lookmove_fetch, lookmove_pages_parsed),
    ]:
        skip_fetch_for_source = (
            (result.name == "anibis" and args.skip_fetch_anibis)
            or (result.name == "lookmove" and args.skip_fetch_lookmove)
        )
        print(f"- [{result.name}] pages requested: {args.max_pages}")
        print(f"  pages fetched: {0 if skip_fetch_for_source else fetch_meta.pages_fetched}")
        print(f"  pages parsed: {pages_parsed}")
        print(f"  cache files ({len(fetch_meta.cache_paths)}):")
        for cache in fetch_meta.cache_paths:
            print(f"    - {cache}")
        for note in fetch_meta.notes:
            print(f"  {note}")
        print(
            f"  detected={result.stats.detected_total} "
            f"sale={result.stats.transaction_counts.get('sale', 0)} "
            f"rent={result.stats.transaction_counts.get('rent', 0)} "
            f"unknown={result.stats.transaction_counts.get('unknown', 0)}"
        )
        print(
            f"  kept_NE={result.stats.kept_canton_count} "
            f"excluded_outside_NE={result.stats.excluded_canton_count}"
        )
        print(
            f"  collected={result.persistence.collected_count} "
            f"created={result.persistence.created_count} "
            f"updated={result.persistence.updated_count} "
            f"unchanged={result.persistence.unchanged_count} "
            f"errors={len(result.persistence.errors)}"
        )

    if not args.no_export:
        output_dir = ROOT / "data" / "exports"
        export_results = await export_all_csv(output_dir=output_dir)
        async with AsyncSessionLocal() as session:
            quality_result = await export_quality_report_csv(
                session,
                output_dir / "quality_report.csv",
            )
        export_results.append(quality_result)

        print("Export files:")
        for item in export_results:
            print(f"- {item.name}: {item.path} ({item.row_count} rows)")

    await _print_dedup_summary()

    all_errors = [*anibis_result.persistence.errors, *lookmove_result.persistence.errors]
    return 0 if not all_errors else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
