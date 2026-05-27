from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

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
from immo_ne_collector.scrapers.lookmove import LookmoveCachedHtmlScraper, LookmoveParseError
from immo_ne_collector.scrapers.safety import SafetyConfig
from immo_ne_collector.services.anibis_filters import FilterStats, filter_collection_batch
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.exports import ExportFileResult, export_all_csv
from immo_ne_collector.services.persistence import persist_collection_batch
from immo_ne_collector.services.quality import QualityExportResult, export_quality_report_csv
from immo_ne_collector.services.source_config import (
    build_canton_property_filter,
    get_sale_search_url,
    normalize_canton,
    parse_sources_csv,
)

MAX_ALLOWED_PAGES = 10


class SourceSummary(NamedTuple):
    source: str
    requested_pages: int
    fetched_pages: int
    loaded_from_cache_pages: int
    parsed_pages: int
    cache_files: list[Path]
    detected_total: int
    kept_canton_count: int
    excluded_canton_count: int
    tx_sale: int
    tx_rent: int
    tx_unknown: int
    collected_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    errors: list[str]
    notes: list[str]
    source_status: str
    stopped_at_page: int | None
    pagination_stopped_reason: str | None


def _set_query_param(url: str, *, key: str, value: str) -> str:
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params[key] = value
    return urlunparse(parsed._replace(query=urlencode(params)))


def _build_anibis_page_urls(base_url: str, max_pages: int) -> list[str]:
    return [_set_query_param(base_url, key="page", value=str(page)) for page in range(1, max_pages + 1)]


def _cache_lookup_key(url: str) -> tuple[str, str, str]:
    parsed = urlparse(url)
    domain = (parsed.netloc or "unknown").replace(":", "_").replace(".", "_")
    path = parsed.path.strip("/") or "root"
    path_slug = "_".join(part for part in path.split("/") if part)[:80]
    query_suffix = ""
    if parsed.query:
        import hashlib

        query_hash = hashlib.sha1(parsed.query.encode("utf-8")).hexdigest()[:8]
        query_suffix = f"_q{query_hash}"
    return domain, path_slug, query_suffix


def _find_fresh_cache_for_url(cache_dir: Path, url: str, *, max_age_hours: int) -> Path | None:
    domain, path_slug, query_suffix = _cache_lookup_key(url)
    pattern = f"*_{domain}_{path_slug}{query_suffix}.html"
    matches = sorted(cache_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        return None
    freshest = matches[0]
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    modified_at = datetime.fromtimestamp(freshest.stat().st_mtime, tz=UTC)
    if modified_at < cutoff:
        return None
    return freshest


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
        description="Collecte multi-source vente par canton configuré (URLs de recherche contrôlées).",
    )
    parser.add_argument("--canton", required=True, help="Canton cible (ex: NE).")
    parser.add_argument(
        "--sources",
        default="anibis,lookmove",
        help="Liste de sources séparées par des virgules (ex: anibis,lookmove).",
    )
    parser.add_argument("--max-pages", type=int, default=1, help="Nombre maximum de pages (défaut: 1).")
    parser.add_argument("--max-listings", type=int, default=None, help="Nombre max d'annonces par source.")
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Réutiliser le cache Lookmove récent quand disponible avant de refaire un fetch.",
    )
    parser.add_argument(
        "--cache-max-age-hours",
        type=int,
        default=24,
        help="Âge max du cache Lookmove en heures si --use-cache (défaut: 24).",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.0,
        help="Délai entre deux pages d'une même source (défaut: 1.0).",
    )
    parser.add_argument("--no-export", action="store_true", help="Ne pas générer les exports CSV.")
    parser.add_argument("--timeout", type=float, default=None, help="Timeout HTTP fetch en secondes.")
    parser.add_argument("--retries", type=int, default=None, help="Nombre de retries HTTP fetch.")
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_pages < 1:
        raise ValueError("--max-pages must be >= 1")
    if args.max_pages > MAX_ALLOWED_PAGES:
        raise ValueError(f"--max-pages must be <= {MAX_ALLOWED_PAGES}")
    if args.max_listings is not None and args.max_listings < 1:
        raise ValueError("--max-listings must be >= 1")
    if args.timeout is not None and args.timeout <= 0:
        raise ValueError("--timeout must be > 0")
    if args.retries is not None and args.retries < 0:
        raise ValueError("--retries must be >= 0")
    if args.delay_seconds < 0:
        raise ValueError("--delay-seconds must be >= 0")
    if args.cache_max_age_hours < 1:
        raise ValueError("--cache-max-age-hours must be >= 1")


def _build_fetch_safety(timeout: float | None, retries: int | None) -> SafetyConfig:
    return SafetyConfig(
        timeout_seconds=timeout if timeout is not None else 20.0,
        max_retries=retries if retries is not None else 1,
        min_interval_seconds=1.0,
    )


async def _fetch_pages_for_source(
    *,
    source: str,
    base_url: str,
    max_pages: int,
    timeout: float | None,
    retries: int | None,
    delay_seconds: float,
    use_cache: bool,
    cache_max_age_hours: int,
) -> tuple[list[Path], int, int, list[str], str, int | None, str | None]:
    cache_dir = ROOT / "data" / "cache" / "html"
    safety = _build_fetch_safety(timeout, retries)
    notes: list[str] = []

    loaded_from_cache_pages = 0
    fetched_pages = 0

    if source == "anibis":
        cache_paths: list[Path] = []
        page_urls = _build_anibis_page_urls(base_url, max_pages)
        for index, page_url in enumerate(page_urls, start=1):
            result = await fetch_html_to_cache(
                url=page_url,
                cache_dir=cache_dir,
                source=f"{source}_sale",
                safety=safety,
            )
            print(
                f"[{source}] Page {index}: "
                f"HTTP status={result.status_code} size={result.size_bytes} path={result.file_path}"
            )
            cache_paths.append(result.file_path)
            fetched_pages += 1
            if index < len(page_urls) and delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
        return cache_paths, fetched_pages, loaded_from_cache_pages, notes, "PASS", None, None

    source_status = "PASS"
    stopped_at_page: int | None = None
    stopped_reason: str | None = None
    if use_cache:
        cached = _find_fresh_cache_for_url(cache_dir, base_url, max_age_hours=cache_max_age_hours)
    else:
        cached = None

    if cached is not None:
        cache_paths = [cached]
        loaded_from_cache_pages += 1
        print(f"[{source}] Page 1: loaded from cache path={cached}")
    else:
        first_result = await fetch_html_to_cache(
            url=base_url,
            cache_dir=cache_dir,
            source=f"{source}_sale",
            safety=safety,
        )
        print(
            f"[{source}] Page 1: "
            f"HTTP status={first_result.status_code} size={first_result.size_bytes} path={first_result.file_path}"
        )
        cache_paths = [first_result.file_path]
        fetched_pages += 1
    if max_pages == 1:
        return cache_paths, fetched_pages, loaded_from_cache_pages, notes, source_status, stopped_at_page, stopped_reason

    current_url = base_url
    visited_urls = {current_url}
    current_html = cache_paths[0].read_text(encoding="utf-8")
    while len(cache_paths) < max_pages:
        next_url = _extract_lookmove_next_page_url(current_html, current_url)
        if not next_url:
            notes.append(
                "[lookmove] pagination non détectée proprement dans le HTML brut; arrêt prudent à 1 page."
            )
            break
        if next_url in visited_urls:
            notes.append("[lookmove] boucle pagination détectée; arrêt prudent.")
            break

        visited_urls.add(next_url)
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        if use_cache:
            next_cached = _find_fresh_cache_for_url(cache_dir, next_url, max_age_hours=cache_max_age_hours)
        else:
            next_cached = None
        if next_cached is not None:
            cache_paths.append(next_cached)
            loaded_from_cache_pages += 1
            print(f"[{source}] Page {len(cache_paths)}: loaded from cache path={next_cached}")
            current_url = next_url
            current_html = next_cached.read_text(encoding="utf-8")
            continue
        try:
            next_result = await fetch_html_to_cache(
                url=next_url,
                cache_dir=cache_dir,
                source=f"{source}_sale",
                safety=safety,
            )
        except ScraperHTTPError as exc:
            source_status = "WARNING"
            stopped_at_page = len(cache_paths) + 1
            stopped_reason = f"HTTP_{exc.status_code}"
            notes.append(
                f"Lookmove blocked pagination at page {stopped_at_page}: HTTP {exc.status_code}, use cache or retry later."
            )
            break
        except ScraperTimeoutError:
            source_status = "WARNING"
            stopped_at_page = len(cache_paths) + 1
            stopped_reason = "TIMEOUT"
            notes.append(
                f"Lookmove blocked pagination at page {stopped_at_page}: TIMEOUT, use cache or retry later."
            )
            break
        except Exception as exc:
            source_status = "WARNING"
            stopped_at_page = len(cache_paths) + 1
            stopped_reason = "NETWORK_ERROR"
            notes.append(
                f"Lookmove blocked pagination at page {stopped_at_page}: NETWORK_ERROR ({exc}), use cache or retry later."
            )
            break
        fetched_pages += 1
        print(
            f"[{source}] Page {len(cache_paths) + 1}: "
            f"HTTP status={next_result.status_code} size={next_result.size_bytes} path={next_result.file_path}"
        )
        cache_paths.append(next_result.file_path)
        current_url = next_url
        current_html = next_result.file_path.read_text(encoding="utf-8")
    return cache_paths, fetched_pages, loaded_from_cache_pages, notes, source_status, stopped_at_page, stopped_reason


async def _collect_source(
    *,
    source: str,
    canton: str,
    base_url: str,
    max_pages: int,
    max_listings: int | None,
    timeout: float | None,
    retries: int | None,
    delay_seconds: float,
    use_cache: bool,
    cache_max_age_hours: int,
) -> SourceSummary:
    cache_paths, fetched_pages, loaded_from_cache_pages, notes, source_status, stopped_at_page, stopped_reason = await _fetch_pages_for_source(
        source=source,
        base_url=base_url,
        max_pages=max_pages,
        timeout=timeout,
        retries=retries,
        delay_seconds=delay_seconds,
        use_cache=use_cache,
        cache_max_age_hours=cache_max_age_hours,
    )

    scraper_cls = AnibisCachedHtmlScraper if source == "anibis" else LookmoveCachedHtmlScraper
    parse_error_cls = AnibisParseError if source == "anibis" else LookmoveParseError

    remaining = max_listings
    parsed_pages = 0
    detected_total = 0
    kept_canton_count = 0
    excluded_canton_count = 0
    tx_sale = 0
    tx_rent = 0
    tx_unknown = 0
    collected_count = 0
    created_count = 0
    updated_count = 0
    unchanged_count = 0
    errors: list[str] = []

    for cache_path in cache_paths:
        if remaining is not None and remaining <= 0:
            break

        scraper = scraper_cls(html_path=cache_path, source=f"{source}_cached")
        try:
            batch = await collect_and_normalize(scraper)
        except parse_error_cls as exc:
            errors.append(f"{source} parse error ({cache_path}): {exc}")
            break

        filtered_batch, stats = filter_collection_batch(
            batch,
            max_listings=remaining,
            transaction_type="sale",
            canton=canton,
        )
        persistence_result = await persist_collection_batch(filtered_batch)

        parsed_pages += 1
        detected_total += stats.detected_total
        kept_canton_count += stats.kept_canton_count
        excluded_canton_count += stats.excluded_canton_count
        tx_sale += stats.transaction_counts.get("sale", 0)
        tx_rent += stats.transaction_counts.get("rent", 0)
        tx_unknown += stats.transaction_counts.get("unknown", 0)
        collected_count += persistence_result.collected_count
        created_count += persistence_result.created_count
        updated_count += persistence_result.updated_count
        unchanged_count += persistence_result.unchanged_count
        errors.extend(persistence_result.errors)

        if remaining is not None:
            remaining = max(0, remaining - filtered_batch.collected_count)

    return SourceSummary(
        source=source,
        requested_pages=max_pages,
        fetched_pages=fetched_pages,
        loaded_from_cache_pages=loaded_from_cache_pages,
        parsed_pages=parsed_pages,
        cache_files=cache_paths,
        detected_total=detected_total,
        kept_canton_count=kept_canton_count,
        excluded_canton_count=excluded_canton_count,
        tx_sale=tx_sale,
        tx_rent=tx_rent,
        tx_unknown=tx_unknown,
        collected_count=collected_count,
        created_count=created_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        errors=errors,
        notes=notes,
        source_status="FAIL" if errors else source_status,
        stopped_at_page=stopped_at_page,
        pagination_stopped_reason=stopped_reason,
    )


async def _generate_exports_by_canton(
    *,
    canton: str,
) -> tuple[list[ExportFileResult], QualityExportResult, list[ExportFileResult], QualityExportResult]:
    output_dir = ROOT / "data" / "exports"
    by_canton_dir = output_dir / "by_canton" / canton
    canton_filter = build_canton_property_filter(canton)

    async with AsyncSessionLocal() as session:
        global_exports = await export_all_csv(output_dir=output_dir, session=session)
        global_quality = await export_quality_report_csv(session, output_dir / "quality_report.csv")

        by_canton_exports = await export_all_csv(
            output_dir=by_canton_dir,
            session=session,
            property_filter=canton_filter,
        )
        by_canton_quality = await export_quality_report_csv(
            session,
            by_canton_dir / "quality_report.csv",
            property_filter=canton_filter,
        )

    return global_exports, global_quality, by_canton_exports, by_canton_quality


async def _run(args: argparse.Namespace) -> int:
    try:
        _validate_args(args)
        canton = normalize_canton(args.canton)
        sources = parse_sources_csv(args.sources)
    except ValueError as exc:
        print(str(exc))
        return 2

    try:
        source_urls = {source: get_sale_search_url(source=source, canton=canton) for source in sources}
    except ValueError as exc:
        print(str(exc))
        return 2

    summaries: list[SourceSummary] = []
    try:
        for source in sources:
            summaries.append(
                await _collect_source(
                    source=source,
                    canton=canton,
                    base_url=source_urls[source],
                    max_pages=args.max_pages,
                    max_listings=args.max_listings,
                    timeout=args.timeout,
                    retries=args.retries,
                    delay_seconds=args.delay_seconds,
                    use_cache=args.use_cache,
                    cache_max_age_hours=args.cache_max_age_hours,
                )
            )
    except Exception as exc:
        print(f"Collection error: {exc}")
        return 1

    all_errors = [error for summary in summaries for error in summary.errors]
    any_fail = any(summary.source_status == "FAIL" for summary in summaries)
    print("Collection summary:")
    print(f"- Canton: {canton}")
    print(f"- Sources: {', '.join(sources)}")
    for summary in summaries:
        print(f"- [{summary.source}]")
        print(f"  requested pages: {summary.requested_pages}")
        print(f"  fetched pages: {summary.fetched_pages}")
        print(f"  loaded from cache: {summary.loaded_from_cache_pages}")
        print(f"  parsed pages: {summary.parsed_pages}")
        print(f"  source status: {summary.source_status}")
        if summary.stopped_at_page is not None:
            print(f"  stopped at page: {summary.stopped_at_page}")
        if summary.pagination_stopped_reason:
            print(f"  stop reason: {summary.pagination_stopped_reason}")
        print(f"  cache files: {len(summary.cache_files)}")
        for cache_path in summary.cache_files:
            print(f"    - {cache_path}")
        for note in summary.notes:
            print(f"  {note}")
        print(
            f"  detected total: {summary.detected_total} "
            f"(sale/rent/unknown={summary.tx_sale}/{summary.tx_rent}/{summary.tx_unknown})"
        )
        print(
            f"  kept canton {canton}: {summary.kept_canton_count} "
            f"excluded: {summary.excluded_canton_count}"
        )
        print(
            f"  collected={summary.collected_count} "
            f"created={summary.created_count} "
            f"updated={summary.updated_count} "
            f"unchanged={summary.unchanged_count} "
            f"errors={len(summary.errors)}"
        )

    if not args.no_export:
        try:
            global_exports, global_quality, by_canton_exports, by_canton_quality = (
                await _generate_exports_by_canton(canton=canton)
            )
        except Exception as exc:
            print(f"Export error: {exc}")
            return 1

        print("Global exports:")
        for item in [*global_exports, global_quality]:
            print(f"- {item.name}: {item.path} ({item.row_count} rows)")

        print(f"By-canton exports ({canton}):")
        for item in [*by_canton_exports, by_canton_quality]:
            print(f"- {item.name}: {item.path} ({item.row_count} rows)")

    if all_errors:
        print("Errors:")
        for error in all_errors:
            print(f"- {error}")
    if any_fail:
        return 1
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
