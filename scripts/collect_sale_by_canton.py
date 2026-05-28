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
from immo_ne_collector.scrapers.homegate import HomegateCachedHtmlScraper, HomegateParseError
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
    ROMANDY_CANTONS,
    SourceCantonConfig,
    SourceUrlConfig,
    build_canton_property_filter,
    get_sale_source_config,
    get_sale_source_urls,
    list_sale_source_configs,
    normalize_canton,
    parse_sources_csv,
)

MAX_ALLOWED_PAGES = 10


class SourceSummary(NamedTuple):
    source: str
    url_kind: str
    base_url: str | None
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


def _build_homegate_page_urls(base_url: str, max_pages: int) -> list[str]:
    return [_set_query_param(base_url, key="ep", value=str(page)) for page in range(1, max_pages + 1)]


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
    parser.add_argument("--canton", help="Canton cible (ex: NE).")
    parser.add_argument(
        "--all-romandie",
        action="store_true",
        help="Traiter GE, VD, NE, JU, FR, VS dans cet ordre.",
    )
    parser.add_argument(
        "--list-config",
        action="store_true",
        help="Afficher la configuration source/canton (enabled/url/note).",
    )
    parser.add_argument(
        "--sources",
        default="anibis,lookmove",
        help="Liste de sources séparées par des virgules (ex: anibis,lookmove,homegate).",
    )
    parser.add_argument("--max-pages", type=int, default=1, help="Nombre maximum de pages (défaut: 1).")
    parser.add_argument("--max-listings", type=int, default=None, help="Nombre max d'annonces par source.")
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Réutiliser le cache récent quand disponible avant de refaire un fetch (Lookmove/Homegate).",
    )
    parser.add_argument(
        "--cache-max-age-hours",
        type=int,
        default=24,
        help="Âge max du cache en heures si --use-cache (défaut: 24).",
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

    if args.list_config:
        return

    if args.all_romandie and args.canton:
        raise ValueError("Use either --canton or --all-romandie, not both")
    if not args.all_romandie and not args.canton:
        raise ValueError("Either --canton or --all-romandie is required")


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

    if source == "homegate":
        cache_paths = []
        page_urls = _build_homegate_page_urls(base_url, max_pages)
        source_status = "PASS"
        stopped_at_page: int | None = None
        stopped_reason: str | None = None

        for index, page_url in enumerate(page_urls, start=1):
            if use_cache:
                cached = _find_fresh_cache_for_url(cache_dir, page_url, max_age_hours=cache_max_age_hours)
            else:
                cached = None

            if cached is not None:
                cache_paths.append(cached)
                loaded_from_cache_pages += 1
                print(f"[{source}] Page {index}: loaded from cache path={cached}")
            else:
                try:
                    result = await fetch_html_to_cache(
                        url=page_url,
                        cache_dir=cache_dir,
                        source=f"{source}_sale",
                        safety=safety,
                    )
                except ScraperHTTPError as exc:
                    if cache_paths:
                        source_status = "WARNING"
                        stopped_at_page = index
                        stopped_reason = f"HTTP_{exc.status_code}"
                        notes.append(
                            f"Homegate pagination stopped at page {index}: HTTP {exc.status_code}, "
                            "partial results kept."
                        )
                        break
                    raise
                except ScraperTimeoutError:
                    if cache_paths:
                        source_status = "WARNING"
                        stopped_at_page = index
                        stopped_reason = "TIMEOUT"
                        notes.append(
                            f"Homegate pagination stopped at page {index}: TIMEOUT, partial results kept."
                        )
                        break
                    raise
                print(
                    f"[{source}] Page {index}: "
                    f"HTTP status={result.status_code} size={result.size_bytes} path={result.file_path}"
                )
                cache_paths.append(result.file_path)
                fetched_pages += 1

            if index < len(page_urls) and delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

        return (
            cache_paths,
            fetched_pages,
            loaded_from_cache_pages,
            notes,
            source_status,
            stopped_at_page,
            stopped_reason,
        )

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
    url_kind: str,
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

    scraper_cls_by_source = {
        "anibis": AnibisCachedHtmlScraper,
        "lookmove": LookmoveCachedHtmlScraper,
        "homegate": HomegateCachedHtmlScraper,
    }
    parse_error_cls_by_source = {
        "anibis": AnibisParseError,
        "lookmove": LookmoveParseError,
        "homegate": HomegateParseError,
    }
    scraper_cls = scraper_cls_by_source[source]
    parse_error_cls = parse_error_cls_by_source[source]

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

        scraper_kwargs: dict[str, object] = {
            "html_path": cache_path,
            "source": f"{source}_cached",
        }
        if source == "homegate":
            scraper_kwargs["url_kind"] = url_kind
        scraper = scraper_cls(**scraper_kwargs)
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
        url_kind=url_kind,
        base_url=base_url,
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


def _build_disabled_source_summary(
    *,
    source: str,
    url_kind: str = "default",
    base_url: str | None = None,
    max_pages: int,
    note: str,
    pagination_reason: str = "SOURCE_DISABLED",
) -> SourceSummary:
    return SourceSummary(
        source=source,
        url_kind=url_kind,
        base_url=base_url,
        requested_pages=max_pages,
        fetched_pages=0,
        loaded_from_cache_pages=0,
        parsed_pages=0,
        cache_files=[],
        detected_total=0,
        kept_canton_count=0,
        excluded_canton_count=0,
        tx_sale=0,
        tx_rent=0,
        tx_unknown=0,
        collected_count=0,
        created_count=0,
        updated_count=0,
        unchanged_count=0,
        errors=[],
        notes=[note],
        source_status="WARNING",
        stopped_at_page=None,
        pagination_stopped_reason=pagination_reason,
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
            canton=canton,
        )
        by_canton_quality = await export_quality_report_csv(
            session,
            by_canton_dir / "quality_report.csv",
            property_filter=canton_filter,
        )

    return global_exports, global_quality, by_canton_exports, by_canton_quality


def _print_source_summary(*, canton: str, summary: SourceSummary) -> None:
    label = f"{summary.source}/{summary.url_kind}" if summary.url_kind else summary.source
    print(f"- [{canton}/{label}]")
    if summary.base_url:
        print(f"  url: {summary.base_url}")
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


def _print_list_config(*, sources: list[str]) -> None:
    rows = list_sale_source_configs(cantons=list(ROMANDY_CANTONS), sources=sources)
    print("Configured source/canton sale URLs:")
    print("canton | source | enabled | url_kind | url | note")
    for row in rows:
        note = row.note or ""
        enabled = "true" if row.enabled else "false"
        source_urls = get_sale_source_urls(source=row.source, canton=row.canton)
        if not source_urls:
            url = row.url or "-"
            print(f"{row.canton} | {row.source} | {enabled} | default | {url} | {note}")
            continue
        for source_url in source_urls:
            print(
                f"{row.canton} | {row.source} | {enabled} | {source_url.url_kind} | {source_url.url} | {note}"
            )


async def _run_canton(
    *,
    canton: str,
    sources: list[str],
    args: argparse.Namespace,
) -> tuple[list[SourceSummary], list[str]]:
    summaries: list[SourceSummary] = []
    errors: list[str] = []

    print(f"Running canton {canton}...")
    for source in sources:
        try:
            source_config: SourceCantonConfig = get_sale_source_config(source=source, canton=canton)
        except ValueError as exc:
            message = str(exc)
            summaries.append(
                _build_disabled_source_summary(
                    source=source,
                    max_pages=args.max_pages,
                    note=message,
                )
            )
            continue

        source_urls = get_sale_source_urls(source=source, canton=canton)
        if not source_urls and source_config.url:
            source_urls = [SourceUrlConfig(url=source_config.url, url_kind="default")]

        if not source_config.enabled:
            note = source_config.note or "source disabled"
            disabled_reason = (
                "HOMEGATE_DISABLED_ANTI_BOT_RISK" if source == "homegate" else "SOURCE_DISABLED"
            )
            if not source_urls:
                summaries.append(
                    _build_disabled_source_summary(
                        source=source,
                        max_pages=args.max_pages,
                        note=f"{source} disabled for {canton}: {note}",
                        pagination_reason=disabled_reason,
                    )
                )
                continue
            for source_url in source_urls:
                summaries.append(
                    _build_disabled_source_summary(
                        source=source,
                        url_kind=source_url.url_kind,
                        base_url=source_url.url,
                        max_pages=args.max_pages,
                        note=f"{source} disabled for {canton}: {note}",
                        pagination_reason=disabled_reason,
                    )
                )
            continue

        if not source_urls:
            summaries.append(
                _build_disabled_source_summary(
                    source=source,
                    max_pages=args.max_pages,
                    note=f"{source} has no URL configured for {canton}",
                )
            )
            continue

        remaining_for_source = args.max_listings
        for source_url in source_urls:
            if remaining_for_source is not None and remaining_for_source <= 0:
                break
            try:
                summary = await _collect_source(
                    source=source,
                    url_kind=source_url.url_kind,
                    canton=canton,
                    base_url=source_url.url,
                    max_pages=args.max_pages,
                    max_listings=remaining_for_source,
                    timeout=args.timeout,
                    retries=args.retries,
                    delay_seconds=args.delay_seconds,
                    use_cache=args.use_cache,
                    cache_max_age_hours=args.cache_max_age_hours,
                )
                summaries.append(summary)
                if remaining_for_source is not None:
                    remaining_for_source = max(0, remaining_for_source - summary.collected_count)
            except ScraperHTTPError as exc:
                if source == "lookmove":
                    summaries.append(
                        SourceSummary(
                            source=source,
                            url_kind=source_url.url_kind,
                            base_url=source_url.url,
                            requested_pages=args.max_pages,
                            fetched_pages=0,
                            loaded_from_cache_pages=0,
                            parsed_pages=0,
                            cache_files=[],
                            detected_total=0,
                            kept_canton_count=0,
                            excluded_canton_count=0,
                            tx_sale=0,
                            tx_rent=0,
                            tx_unknown=0,
                            collected_count=0,
                            created_count=0,
                            updated_count=0,
                            unchanged_count=0,
                            errors=[],
                            notes=[
                                f"Lookmove blocked at page 1: HTTP {exc.status_code}, use cache or retry later."
                            ],
                            source_status="WARNING",
                            stopped_at_page=1,
                            pagination_stopped_reason=f"HTTP_{exc.status_code}",
                        )
                    )
                    continue
                failed_summary = SourceSummary(
                    source=source,
                    url_kind=source_url.url_kind,
                    base_url=source_url.url,
                    requested_pages=args.max_pages,
                    fetched_pages=0,
                    loaded_from_cache_pages=0,
                    parsed_pages=0,
                    cache_files=[],
                    detected_total=0,
                    kept_canton_count=0,
                    excluded_canton_count=0,
                    tx_sale=0,
                    tx_rent=0,
                    tx_unknown=0,
                    collected_count=0,
                    created_count=0,
                    updated_count=0,
                    unchanged_count=0,
                    errors=[str(exc)],
                    notes=[f"Collection error on {source}/{canton}/{source_url.url_kind}: {exc}"],
                    source_status="FAIL",
                    stopped_at_page=1,
                    pagination_stopped_reason=f"HTTP_{exc.status_code}",
                )
                summaries.append(failed_summary)
                errors.append(f"{canton}/{source}/{source_url.url_kind}: {exc}")
            except ScraperTimeoutError:
                if source == "lookmove":
                    summaries.append(
                        SourceSummary(
                            source=source,
                            url_kind=source_url.url_kind,
                            base_url=source_url.url,
                            requested_pages=args.max_pages,
                            fetched_pages=0,
                            loaded_from_cache_pages=0,
                            parsed_pages=0,
                            cache_files=[],
                            detected_total=0,
                            kept_canton_count=0,
                            excluded_canton_count=0,
                            tx_sale=0,
                            tx_rent=0,
                            tx_unknown=0,
                            collected_count=0,
                            created_count=0,
                            updated_count=0,
                            unchanged_count=0,
                            errors=[],
                            notes=["Lookmove blocked at page 1: TIMEOUT, use cache or retry later."],
                            source_status="WARNING",
                            stopped_at_page=1,
                            pagination_stopped_reason="TIMEOUT",
                        )
                    )
                    continue
                failed_summary = SourceSummary(
                    source=source,
                    url_kind=source_url.url_kind,
                    base_url=source_url.url,
                    requested_pages=args.max_pages,
                    fetched_pages=0,
                    loaded_from_cache_pages=0,
                    parsed_pages=0,
                    cache_files=[],
                    detected_total=0,
                    kept_canton_count=0,
                    excluded_canton_count=0,
                    tx_sale=0,
                    tx_rent=0,
                    tx_unknown=0,
                    collected_count=0,
                    created_count=0,
                    updated_count=0,
                    unchanged_count=0,
                    errors=["TIMEOUT"],
                    notes=[f"Collection error on {source}/{canton}/{source_url.url_kind}: TIMEOUT"],
                    source_status="FAIL",
                    stopped_at_page=1,
                    pagination_stopped_reason="TIMEOUT",
                )
                summaries.append(failed_summary)
                errors.append(f"{canton}/{source}/{source_url.url_kind}: TIMEOUT")
            except Exception as exc:
                failed_summary = SourceSummary(
                    source=source,
                    url_kind=source_url.url_kind,
                    base_url=source_url.url,
                    requested_pages=args.max_pages,
                    fetched_pages=0,
                    loaded_from_cache_pages=0,
                    parsed_pages=0,
                    cache_files=[],
                    detected_total=0,
                    kept_canton_count=0,
                    excluded_canton_count=0,
                    tx_sale=0,
                    tx_rent=0,
                    tx_unknown=0,
                    collected_count=0,
                    created_count=0,
                    updated_count=0,
                    unchanged_count=0,
                    errors=[str(exc)],
                    notes=[f"Collection error on {source}/{canton}/{source_url.url_kind}: {exc}"],
                    source_status="FAIL",
                    stopped_at_page=None,
                    pagination_stopped_reason="COLLECTION_EXCEPTION",
                )
                summaries.append(failed_summary)
                errors.append(f"{canton}/{source}/{source_url.url_kind}: {exc}")

    return summaries, errors


def _resolve_cantons(args: argparse.Namespace) -> list[str]:
    if args.all_romandie:
        return list(ROMANDY_CANTONS)
    if args.canton:
        normalized = normalize_canton(args.canton)
        if normalized not in ROMANDY_CANTONS:
            raise ValueError(
                f"Unsupported canton '{normalized}'. Supported: {', '.join(ROMANDY_CANTONS)}"
            )
        return [normalized]
    return []


async def _run(args: argparse.Namespace) -> int:
    try:
        _validate_args(args)
        sources = parse_sources_csv(args.sources)
    except ValueError as exc:
        print(str(exc))
        return 2

    if args.list_config:
        _print_list_config(sources=sources)
        return 0

    try:
        cantons = _resolve_cantons(args)
    except ValueError as exc:
        print(str(exc))
        return 2
    all_summaries: dict[str, list[SourceSummary]] = {}
    hard_errors: list[str] = []

    for canton in cantons:
        try:
            summaries, errors = await _run_canton(canton=canton, sources=sources, args=args)
        except ValueError as exc:
            print(f"{canton}: {exc}")
            return 2

        all_summaries[canton] = summaries
        hard_errors.extend(errors)

        print(f"Collection summary ({canton}):")
        for summary in summaries:
            _print_source_summary(canton=canton, summary=summary)

        if not args.no_export:
            try:
                global_exports, global_quality, by_canton_exports, by_canton_quality = (
                    await _generate_exports_by_canton(canton=canton)
                )
            except Exception as exc:
                print(f"Export error for canton {canton}: {exc}")
                return 1

            print("Global exports:")
            for item in [*global_exports, global_quality]:
                print(f"- {item.name}: {item.path} ({item.row_count} rows)")

            print(f"By-canton exports ({canton}):")
            for item in [*by_canton_exports, by_canton_quality]:
                print(f"- {item.name}: {item.path} ({item.row_count} rows)")

    total_requested_cantons = len(cantons)
    treated_cantons = len(all_summaries)
    total_summaries = [summary for group in all_summaries.values() for summary in group]

    total_fetched = sum(item.fetched_pages for item in total_summaries)
    total_cached = sum(item.loaded_from_cache_pages for item in total_summaries)
    total_parsed = sum(item.parsed_pages for item in total_summaries)
    total_detected = sum(item.detected_total for item in total_summaries)
    total_collected = sum(item.collected_count for item in total_summaries)
    total_warnings = sum(1 for item in total_summaries if item.source_status == "WARNING")
    total_failures = sum(1 for item in total_summaries if item.source_status == "FAIL")
    all_errors = [error for item in total_summaries for error in item.errors]

    print("Global run summary:")
    print(f"- Requested cantons: {', '.join(cantons)}")
    print(f"- Treated cantons: {treated_cantons}/{total_requested_cantons}")
    print(f"- Sources: {', '.join(sources)}")
    print(f"- Pages fetched: {total_fetched}")
    print(f"- Pages loaded from cache: {total_cached}")
    print(f"- Pages parsed: {total_parsed}")
    print(f"- Total detected: {total_detected}")
    print(f"- Total collected: {total_collected}")
    print(f"- Source warnings: {total_warnings}")
    print(f"- Source failures: {total_failures}")

    if hard_errors or all_errors:
        print("Errors:")
        for error in [*hard_errors, *all_errors]:
            print(f"- {error}")

    if total_failures > 0:
        return 1
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
