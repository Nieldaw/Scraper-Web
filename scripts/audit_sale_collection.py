from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
from immo_ne_collector.services.anibis_filters import filter_collection_batch
from immo_ne_collector.services.collection import CollectionBatch, collect_and_normalize
from immo_ne_collector.services.exports import ExportFileResult, export_all_csv
from immo_ne_collector.services.persistence import persist_collection_batch
from immo_ne_collector.services.quality import QualityExportResult, export_quality_report_csv
from immo_ne_collector.services.source_config import (
    CANTON_MATCHERS,
    ROMANDY_CANTONS,
    SourceCantonConfig,
    build_canton_property_filter,
    get_sale_source_config,
    normalize_detected_canton,
    normalize_canton,
    parse_sources_csv,
)

MAX_ALLOWED_PAGES = 10
SUSPECT_NPA_PRICE_VALUES = {Decimal("2000"), Decimal("2300"), Decimal("2400")}


class AuditPageRow(NamedTuple):
    source: str
    canton: str
    page_requested: int
    page_parsed: str
    url_called: str
    http_status: str
    html_size_bytes: int
    cache_path: str
    detected_total: int
    detected_sale: int
    detected_rent: int
    detected_unknown: int
    kept_canton_count: int
    excluded_canton_count: int
    collected_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    error_count: int
    warning_count: int
    warnings: str
    errors: str
    source_status: str
    stopped_at_page: int | None
    pagination_stopped_reason: str


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


def _build_fetch_safety(timeout: float | None, retries: int | None) -> SafetyConfig:
    return SafetyConfig(
        timeout_seconds=timeout if timeout is not None else 20.0,
        max_retries=retries if retries is not None else 1,
        min_interval_seconds=1.0,
    )


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


def _find_latest_cache_for_url(cache_dir: Path, url: str) -> Path | None:
    domain, path_slug, query_suffix = _cache_lookup_key(url)
    pattern = f"*_{domain}_{path_slug}{query_suffix}.html"
    matches = sorted(cache_dir.glob(pattern))
    if not matches:
        return None
    return matches[-1]


def _find_fresh_cache_for_url(cache_dir: Path, url: str, *, max_age_hours: int) -> Path | None:
    latest = _find_latest_cache_for_url(cache_dir, url)
    if latest is None:
        return None
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    modified_at = datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
    if modified_at < cutoff:
        return None
    return latest


def _detect_listing_warnings(
    *,
    source: str,
    canton: str,
    detected_batch: CollectionBatch,
    filtered_batch: CollectionBatch,
    previous_page_ids: set[str],
) -> tuple[list[str], set[str]]:
    warnings: list[str] = []
    matcher = CANTON_MATCHERS.get(canton)

    detected_ids = [
        item.source_listing_id
        for item in detected_batch.listings
        if item.source_listing_id is not None and str(item.source_listing_id).strip()
    ]
    current_id_set = set(detected_ids)
    if detected_ids:
        unique_ratio = len(current_id_set) / len(detected_ids)
        if unique_ratio < 0.6:
            warnings.append(f"{source}: massive repeated source_listing_id on page (unique_ratio={unique_ratio:.2f})")

    if previous_page_ids and current_id_set:
        overlap_ratio = len(previous_page_ids.intersection(current_id_set)) / len(current_id_set)
        if overlap_ratio > 0.8:
            warnings.append(f"{source}: high source_listing_id overlap with previous page ({overlap_ratio:.2f}).")

    for listing in filtered_batch.listings:
        tx = str(listing.raw_data.get("transaction_type", "unknown"))
        if tx != "sale":
            warnings.append(f"{source}: non-sale listing passed filter ({tx}) for URL={listing.url}")

        if listing.price_chf in SUSPECT_NPA_PRICE_VALUES:
            warnings.append(
                f"{source}: suspicious price that looks like NPA ({listing.price_chf}) for URL={listing.url}"
            )

        if listing.rooms is not None and listing.rooms > Decimal("20"):
            warnings.append(
                f"{source}: suspicious rooms value ({listing.rooms}) for URL={listing.url}"
            )

        if matcher and not matcher(listing.url, listing.city, listing.postal_code):
            warnings.append(f"{source}: out-of-canton listing passed filter for URL={listing.url}")

    return warnings, current_id_set


def _write_audit_report(path: Path, rows: list[AuditPageRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        payload = [row._asdict() for row in rows]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    headers = list(AuditPageRow.__annotations__.keys())
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=headers)
        writer.writeheader()
        writer.writerows(row._asdict() for row in rows)


def _validate_by_canton_exports(canton: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    failures: list[str] = []
    export_dir = ROOT / "data" / "exports" / "by_canton" / canton
    ventes_path = export_dir / "ventes.csv"
    quality_path = export_dir / "quality_report.csv"
    master_path = export_dir / "master.csv"
    dedup_path = export_dir / "deduplication_report.csv"
    for required in (master_path, ventes_path, quality_path, dedup_path):
        if not required.exists():
            failures.append(f"Missing by-canton export: {required}")

    matcher = CANTON_MATCHERS.get(canton)
    if matcher and ventes_path.exists():
        with ventes_path.open("r", encoding="utf-8", newline="") as file_obj:
            rows = list(csv.DictReader(file_obj))
        for row in rows:
            tx = (row.get("transaction_type") or "").strip().lower()
            if tx != "sale":
                warnings.append(f"ventes.csv contains non-sale transaction_type={tx} for property_id={row.get('property_id')}")
            city = row.get("city")
            postal_code = row.get("postal_code")
            urls = row.get("source_urls") or "[]"
            try:
                parsed_urls = json.loads(urls)
            except Exception:
                parsed_urls = []
            for url in parsed_urls:
                if not matcher(str(url), city, postal_code):
                    failures.append(
                        f"by-canton ventes includes out-of-canton source_url={url} property_id={row.get('property_id')}"
                    )

    if dedup_path.exists():
        with dedup_path.open("r", encoding="utf-8", newline="") as file_obj:
            rows = list(csv.DictReader(file_obj))
        for row in rows:
            detected_cantons: list[str] = []
            raw_detected = row.get("detected_cantons", "[]")
            try:
                parsed_detected = json.loads(raw_detected)
                if isinstance(parsed_detected, list):
                    for value in parsed_detected:
                        normalized = normalize_detected_canton(str(value) if value is not None else None)
                        detected_cantons.append(normalized)
            except Exception:
                continue
            known_detected = [value for value in detected_cantons if value != "unknown"]
            if known_detected and any(value != canton for value in known_detected):
                failures.append(
                    f"by-canton deduplication_report includes incompatible detected_cantons={known_detected} "
                    f"for property_id={row.get('property_id')}"
                )

    if quality_path.exists():
        with quality_path.open("r", encoding="utf-8", newline="") as file_obj:
            rows = list(csv.DictReader(file_obj))
        missing_addr_rows = [row for row in rows if row.get("issue_code") == "ADDRESS_MISSING"]
        sitn_rows = [row for row in rows if row.get("issue_code") == "SITN_NOT_ELIGIBLE_ADDRESS"]
        if missing_addr_rows and not sitn_rows:
            warnings.append("Missing SITN_NOT_ELIGIBLE_ADDRESS issues while ADDRESS_MISSING exists.")

    return warnings, failures


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit contrôlé de collecte vente par canton (Anibis/Lookmove).",
    )
    parser.add_argument("--canton", help="Canton cible (ex: NE).")
    parser.add_argument(
        "--all-romandie",
        action="store_true",
        help="Audit GE, VD, NE, JU, FR, VS dans cet ordre.",
    )
    parser.add_argument("--sources", default="anibis,lookmove", help="Sources CSV (ex: anibis,lookmove).")
    parser.add_argument("--max-pages", type=int, default=1, help="Nombre max de pages (défaut: 1).")
    parser.add_argument("--max-listings", type=int, default=None, help="Nombre max d'annonces par source.")
    parser.add_argument("--skip-fetch", action="store_true", help="Réutiliser les caches existants si disponibles.")
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Réutiliser le cache récent (Anibis/Lookmove) avant de refaire un fetch.",
    )
    parser.add_argument(
        "--cache-max-age-hours",
        type=int,
        default=24,
        help="Âge max du cache en heures si --use-cache (défaut: 24).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "exports" / "audit_report.csv",
        help="Chemin du rapport d'audit (.csv ou .json).",
    )
    parser.add_argument("--timeout", type=float, default=None, help="Timeout HTTP en secondes.")
    parser.add_argument("--retries", type=int, default=None, help="Nombre de retries HTTP.")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.0,
        help="Délai entre pages d'une même source (défaut: 1.0).",
    )
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
    if args.all_romandie and args.canton:
        raise ValueError("Use either --canton or --all-romandie, not both")
    if not args.all_romandie and not args.canton:
        raise ValueError("Either --canton or --all-romandie is required")


async def _fetch_or_reuse_page(
    *,
    source: str,
    url: str,
    skip_fetch: bool,
    use_cache: bool,
    cache_max_age_hours: int,
    safety: SafetyConfig,
    cache_dir: Path,
) -> tuple[str, int, Path | None, str, list[str]]:
    warnings: list[str] = []
    if skip_fetch:
        cached_path = _find_latest_cache_for_url(cache_dir, url)
        if cached_path is None:
            return ("CACHE_MISS", 0, None, "", [f"{source}: no cache found for URL={url}"])
        html = cached_path.read_text(encoding="utf-8")
        return ("CACHED", cached_path.stat().st_size, cached_path, html, warnings)

    if use_cache:
        cached_path = _find_fresh_cache_for_url(cache_dir, url, max_age_hours=cache_max_age_hours)
        if cached_path is not None:
            html = cached_path.read_text(encoding="utf-8")
            return ("CACHED", cached_path.stat().st_size, cached_path, html, warnings)
        latest_cache = _find_latest_cache_for_url(cache_dir, url)
        if latest_cache is None:
            warnings.append(
                f"{source}: cache miss for URL={url}; fetching live page."
            )
        else:
            warnings.append(
                f"{source}: stale cache for URL={url} (>{cache_max_age_hours}h); fetching live page."
            )

    result = await fetch_html_to_cache(
        url=url,
        cache_dir=cache_dir,
        source=f"{source}_audit",
        safety=safety,
    )
    html = result.file_path.read_text(encoding="utf-8")
    return (str(result.status_code), result.size_bytes, result.file_path, html, warnings)


async def _collect_source_audit_rows(
    *,
    source: str,
    canton: str,
    base_url: str,
    max_pages: int,
    max_listings: int | None,
    skip_fetch: bool,
    use_cache: bool,
    cache_max_age_hours: int,
    timeout: float | None,
    retries: int | None,
    delay_seconds: float,
) -> tuple[list[AuditPageRow], list[str], str, int | None, str | None, int, int]:
    cache_dir = ROOT / "data" / "cache" / "html"
    safety = _build_fetch_safety(timeout, retries)
    rows: list[AuditPageRow] = []
    source_warnings: list[str] = []
    source_status = "PASS"
    stopped_at_page: int | None = None
    stopped_reason: str | None = None
    fetched_pages = 0
    loaded_from_cache_pages = 0
    previous_ids: set[str] = set()
    remaining = max_listings
    parsed_success_pages = 0

    if source == "anibis":
        page_urls = _build_anibis_page_urls(base_url, max_pages)
    else:
        page_urls = [base_url]

    current_url = base_url
    for page_number in range(1, max_pages + 1):
        if remaining is not None and remaining <= 0:
            break
        url = page_urls[page_number - 1] if source == "anibis" else current_url
        if page_number > 1 and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        try:
            status, html_size, cache_path, html, fetch_warnings = await _fetch_or_reuse_page(
                source=source,
                url=url,
                skip_fetch=skip_fetch,
                use_cache=use_cache,
                cache_max_age_hours=cache_max_age_hours,
                safety=safety,
                cache_dir=cache_dir,
            )
            if status == "CACHED":
                loaded_from_cache_pages += 1
            elif status not in {"CACHE_MISS", ""}:
                fetched_pages += 1
        except ScraperHTTPError as exc:
            failed_page = page_number
            if source == "lookmove":
                source_status = "WARNING"
                stopped_at_page = failed_page
                stopped_reason = f"HTTP_{exc.status_code}"
                source_warnings.append(
                    f"Lookmove pagination stopped at page {failed_page}: HTTP {exc.status_code}. "
                    "Use cache or retry later."
                )
                rows.append(
                    AuditPageRow(
                        source=source,
                        canton=canton,
                        page_requested=failed_page,
                        page_parsed="no",
                        url_called=url,
                        http_status=f"HTTP_{exc.status_code}",
                        html_size_bytes=0,
                        cache_path="",
                        detected_total=0,
                        detected_sale=0,
                        detected_rent=0,
                        detected_unknown=0,
                        kept_canton_count=0,
                        excluded_canton_count=0,
                        collected_count=0,
                        created_count=0,
                        updated_count=0,
                        unchanged_count=0,
                        error_count=0,
                        warning_count=1,
                        warnings=(
                            f"Lookmove pagination stopped at page {failed_page}: HTTP {exc.status_code}. "
                            "Use cache or retry later."
                        ),
                        errors="",
                        source_status=source_status,
                        stopped_at_page=stopped_at_page,
                        pagination_stopped_reason=stopped_reason or "",
                    )
                )
                break
            is_partial_success = parsed_success_pages > 0
            source_status = "WARNING" if is_partial_success else "FAIL"
            stopped_at_page = failed_page
            stopped_reason = f"HTTP_{exc.status_code}"
            rows.append(
                AuditPageRow(
                    source=source,
                    canton=canton,
                    page_requested=failed_page,
                    page_parsed="no",
                    url_called=url,
                    http_status=f"HTTP_{exc.status_code}",
                    html_size_bytes=0,
                    cache_path="",
                    detected_total=0,
                    detected_sale=0,
                    detected_rent=0,
                    detected_unknown=0,
                    kept_canton_count=0,
                    excluded_canton_count=0,
                    collected_count=0,
                    created_count=0,
                    updated_count=0,
                    unchanged_count=0,
                    error_count=0 if is_partial_success else 1,
                    warning_count=1 if is_partial_success else 0,
                    warnings=(
                        f"{source}: pagination stopped at page {failed_page}: HTTP {exc.status_code}. "
                        "Partial results kept."
                        if is_partial_success
                        else ""
                    ),
                    errors=(
                        ""
                        if is_partial_success
                        else f"{source}: fetch failed at page {failed_page} with HTTP {exc.status_code}"
                    ),
                    source_status=source_status,
                    stopped_at_page=stopped_at_page,
                    pagination_stopped_reason=stopped_reason or "",
                )
            )
            break
        except ScraperTimeoutError:
            failed_page = page_number
            if source == "lookmove":
                source_status = "WARNING"
                stopped_at_page = failed_page
                stopped_reason = "TIMEOUT"
                source_warnings.append(
                    f"Lookmove pagination stopped at page {failed_page}: TIMEOUT. Use cache or retry later."
                )
                rows.append(
                    AuditPageRow(
                        source=source,
                        canton=canton,
                        page_requested=failed_page,
                        page_parsed="no",
                        url_called=url,
                        http_status="TIMEOUT",
                        html_size_bytes=0,
                        cache_path="",
                        detected_total=0,
                        detected_sale=0,
                        detected_rent=0,
                        detected_unknown=0,
                        kept_canton_count=0,
                        excluded_canton_count=0,
                        collected_count=0,
                        created_count=0,
                        updated_count=0,
                        unchanged_count=0,
                        error_count=0,
                        warning_count=1,
                        warnings=(
                            f"Lookmove pagination stopped at page {failed_page}: TIMEOUT. "
                            "Use cache or retry later."
                        ),
                        errors="",
                        source_status=source_status,
                        stopped_at_page=stopped_at_page,
                        pagination_stopped_reason=stopped_reason or "",
                    )
                )
                break
            is_partial_success = parsed_success_pages > 0
            source_status = "WARNING" if is_partial_success else "FAIL"
            stopped_at_page = failed_page
            stopped_reason = "TIMEOUT"
            rows.append(
                AuditPageRow(
                    source=source,
                    canton=canton,
                    page_requested=failed_page,
                    page_parsed="no",
                    url_called=url,
                    http_status="TIMEOUT",
                    html_size_bytes=0,
                    cache_path="",
                    detected_total=0,
                    detected_sale=0,
                    detected_rent=0,
                    detected_unknown=0,
                    kept_canton_count=0,
                    excluded_canton_count=0,
                    collected_count=0,
                    created_count=0,
                    updated_count=0,
                    unchanged_count=0,
                    error_count=0 if is_partial_success else 1,
                    warning_count=1 if is_partial_success else 0,
                    warnings=(
                        f"{source}: pagination stopped at page {failed_page}: TIMEOUT. Partial results kept."
                        if is_partial_success
                        else ""
                    ),
                    errors=(
                        ""
                        if is_partial_success
                        else f"{source}: fetch timeout at page {failed_page}"
                    ),
                    source_status=source_status,
                    stopped_at_page=stopped_at_page,
                    pagination_stopped_reason=stopped_reason or "",
                )
            )
            break
        warnings = list(fetch_warnings)
        errors: list[str] = []
        parsed = False
        detected_total = 0
        tx_counts = Counter({"sale": 0, "rent": 0, "unknown": 0})
        kept_canton_count = 0
        excluded_canton_count = 0
        collected_count = 0
        created_count = 0
        updated_count = 0
        unchanged_count = 0

        if cache_path is None:
            errors.append(f"{source}: page {page_number} cache unavailable.")
        else:
            scraper_cls = AnibisCachedHtmlScraper if source == "anibis" else LookmoveCachedHtmlScraper
            parse_error_cls = AnibisParseError if source == "anibis" else LookmoveParseError
            scraper = scraper_cls(html_path=cache_path, source=f"{source}_cached")
            try:
                detected_batch = await collect_and_normalize(scraper)
                parsed = True
                filtered_batch, stats = filter_collection_batch(
                    detected_batch,
                    max_listings=remaining,
                    transaction_type="sale",
                    canton=canton,
                )
                persistence = await persist_collection_batch(filtered_batch)
                detected_total = stats.detected_total
                tx_counts.update(stats.transaction_counts)
                kept_canton_count = stats.kept_canton_count
                excluded_canton_count = stats.excluded_canton_count
                collected_count = persistence.collected_count
                created_count = persistence.created_count
                updated_count = persistence.updated_count
                unchanged_count = persistence.unchanged_count
                errors.extend(persistence.errors)

                listing_warnings, previous_ids = _detect_listing_warnings(
                    source=source,
                    canton=canton,
                    detected_batch=detected_batch,
                    filtered_batch=filtered_batch,
                    previous_page_ids=previous_ids,
                )
                warnings.extend(listing_warnings)
                if detected_total == 0:
                    warnings.append(f"{source}: empty page detected at page={page_number}.")
                if remaining is not None:
                    remaining = max(0, remaining - filtered_batch.collected_count)
            except parse_error_cls as exc:
                errors.append(f"{source}: parse error page={page_number}: {exc}")

        rows.append(
            AuditPageRow(
                source=source,
                canton=canton,
                page_requested=page_number,
                page_parsed="yes" if parsed else "no",
                url_called=url,
                http_status=status,
                html_size_bytes=html_size,
                cache_path=str(cache_path) if cache_path else "",
                detected_total=detected_total,
                detected_sale=tx_counts.get("sale", 0),
                detected_rent=tx_counts.get("rent", 0),
                detected_unknown=tx_counts.get("unknown", 0),
                kept_canton_count=kept_canton_count,
                excluded_canton_count=excluded_canton_count,
                collected_count=collected_count,
                created_count=created_count,
                updated_count=updated_count,
                unchanged_count=unchanged_count,
                error_count=len(errors),
                warning_count=len(warnings),
                warnings=" | ".join(warnings),
                errors=" | ".join(errors),
                source_status=source_status,
                stopped_at_page=stopped_at_page,
                pagination_stopped_reason=stopped_reason or "",
            )
        )
        if parsed:
            parsed_success_pages += 1

        if source == "lookmove":
            if page_number >= max_pages:
                break
            next_url = _extract_lookmove_next_page_url(html, current_url) if html else None
            if not next_url:
                source_warnings.append("lookmove: pagination not detected, stopped after page 1")
                if max_pages > 1 and source_status == "PASS":
                    source_status = "WARNING"
                    stopped_at_page = page_number + 1
                    stopped_reason = "PAGINATION_NOT_DETECTED"
                break
            current_url = next_url

        if source == "anibis" and detected_total == 0:
            source_warnings.append(f"anibis: stopped after empty page {page_number}")
            break

    # Anibis-specific audit: ensure pages are not byte-identical when multiple fetched.
    if source == "anibis" and len(rows) > 1:
        sizes = [row.html_size_bytes for row in rows if row.html_size_bytes > 0]
        if len(sizes) > 1 and len(set(sizes)) == 1:
            source_warnings.append("anibis: fetched pages have identical HTML size; verify pagination.")
        paths = [Path(row.cache_path) for row in rows if row.cache_path]
        if len(paths) != len({path.name for path in paths}):
            source_warnings.append("anibis: cache file names are not unique across pages.")

    if source_status == "PASS" and any(row.error_count > 0 for row in rows):
        source_status = "FAIL"
    if rows and source_status != "PASS":
        updated_rows: list[AuditPageRow] = []
        for row in rows:
            updated_rows.append(
                row._replace(
                    source_status=source_status,
                    stopped_at_page=stopped_at_page,
                    pagination_stopped_reason=stopped_reason or "",
                )
            )
        rows = updated_rows
    return (
        rows,
        source_warnings,
        source_status,
        stopped_at_page,
        stopped_reason,
        fetched_pages,
        loaded_from_cache_pages,
    )


async def _generate_exports(canton: str) -> tuple[list[ExportFileResult], QualityExportResult, list[ExportFileResult], QualityExportResult]:
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


def _global_status(
    *,
    rows: list[AuditPageRow],
    extra_warnings: list[str],
    source_statuses: list[str],
    hard_failures: list[str],
) -> str:
    if hard_failures:
        return "FAIL"
    error_total = sum(row.error_count for row in rows)
    warning_total = sum(row.warning_count for row in rows) + len(extra_warnings)
    if any(status == "FAIL" for status in source_statuses):
        return "FAIL"
    if error_total > 0:
        return "FAIL"
    if warning_total > 0:
        return "WARNING"
    return "PASS"


def _extract_main_errors(rows: list[AuditPageRow], *, limit: int = 12) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not row.errors:
            continue
        for item in row.errors.split(" | "):
            text = item.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            errors.append(
                f"{row.canton}/{row.source}/page{row.page_requested}: {text}"
            )
            if len(errors) >= limit:
                return errors
    return errors


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

    try:
        cantons = _resolve_cantons(args)
    except ValueError as exc:
        print(str(exc))
        return 2

    all_rows: list[AuditPageRow] = []
    top_warnings: list[str] = []
    top_failures: list[str] = []
    source_statuses: list[str] = []
    total_fetched_pages = 0
    total_loaded_from_cache_pages = 0
    for canton in cantons:
        for source in sources:
            try:
                source_config: SourceCantonConfig = get_sale_source_config(source=source, canton=canton)
            except ValueError as exc:
                source_statuses.append("WARNING")
                top_warnings.append(f"{canton}/{source}: {exc}")
                all_rows.append(
                    AuditPageRow(
                        source=source,
                        canton=canton,
                        page_requested=0,
                        page_parsed="no",
                        url_called="",
                        http_status="SKIPPED",
                        html_size_bytes=0,
                        cache_path="",
                        detected_total=0,
                        detected_sale=0,
                        detected_rent=0,
                        detected_unknown=0,
                        kept_canton_count=0,
                        excluded_canton_count=0,
                        collected_count=0,
                        created_count=0,
                        updated_count=0,
                        unchanged_count=0,
                        error_count=0,
                        warning_count=1,
                        warnings=str(exc),
                        errors="",
                        source_status="WARNING",
                        stopped_at_page=None,
                        pagination_stopped_reason="SOURCE_NOT_CONFIGURED",
                    )
                )
                continue

            if not source_config.enabled or not source_config.url:
                message = source_config.note or "source disabled"
                source_statuses.append("WARNING")
                top_warnings.append(f"{canton}/{source}: disabled ({message})")
                all_rows.append(
                    AuditPageRow(
                        source=source,
                        canton=canton,
                        page_requested=0,
                        page_parsed="no",
                        url_called="",
                        http_status="SKIPPED",
                        html_size_bytes=0,
                        cache_path="",
                        detected_total=0,
                        detected_sale=0,
                        detected_rent=0,
                        detected_unknown=0,
                        kept_canton_count=0,
                        excluded_canton_count=0,
                        collected_count=0,
                        created_count=0,
                        updated_count=0,
                        unchanged_count=0,
                        error_count=0,
                        warning_count=1,
                        warnings=message,
                        errors="",
                        source_status="WARNING",
                        stopped_at_page=None,
                        pagination_stopped_reason="SOURCE_DISABLED",
                    )
                )
                continue

            try:
                (
                    page_rows,
                    source_warnings,
                    source_status,
                    stopped_at_page,
                    stopped_reason,
                    source_fetched_pages,
                    source_loaded_from_cache_pages,
                ) = await _collect_source_audit_rows(
                    source=source,
                    canton=canton,
                    base_url=source_config.url,
                    max_pages=args.max_pages,
                    max_listings=args.max_listings,
                    skip_fetch=args.skip_fetch,
                    use_cache=args.use_cache,
                    cache_max_age_hours=args.cache_max_age_hours,
                    timeout=args.timeout,
                    retries=args.retries,
                    delay_seconds=args.delay_seconds,
                )
                all_rows.extend(page_rows)
                top_warnings.extend(source_warnings)
                source_statuses.append(source_status)
                total_fetched_pages += source_fetched_pages
                total_loaded_from_cache_pages += source_loaded_from_cache_pages
                if source_status == "WARNING" and stopped_at_page is not None and stopped_reason:
                    top_warnings.append(
                        f"{canton}/{source} pagination stopped at page {stopped_at_page}: {stopped_reason}"
                    )
            except Exception as exc:
                source_statuses.append("FAIL")
                top_warnings.append(f"{canton}/{source}: unexpected audit error: {exc}")

        try:
            global_exports, global_quality, by_canton_exports, by_canton_quality = await _generate_exports(canton)
        except Exception as exc:
            print(f"Export error ({canton}): {exc}")
            return 1
        export_warnings, export_failures = _validate_by_canton_exports(canton)
        top_warnings.extend(export_warnings)
        top_failures.extend(export_failures)

        print(f"Exports ({canton}):")
        print("Global exports:")
        for item in [*global_exports, global_quality]:
            print(f"  - {item.name}: {item.path} ({item.row_count} rows)")
        print(f"By-canton exports ({canton}):")
        for item in [*by_canton_exports, by_canton_quality]:
            print(f"  - {item.name}: {item.path} ({item.row_count} rows)")

    _write_audit_report(args.output, all_rows)

    status = _global_status(
        rows=all_rows,
        extra_warnings=top_warnings,
        source_statuses=source_statuses,
        hard_failures=top_failures,
    )
    pages_parsed = sum(1 for row in all_rows if row.page_parsed == "yes")
    detected_total = sum(row.detected_total for row in all_rows)
    collected_total = sum(row.collected_count for row in all_rows)
    errors_total = sum(row.error_count for row in all_rows)

    print("Audit summary:")
    print(f"- Global status: {status}")
    print(f"- Cantons requested: {', '.join(cantons)}")
    print(f"- Cantons treated: {len(cantons)}")
    print(f"- Sources audited: {len(sources)}")
    print(f"- Pages fetched: {total_fetched_pages}")
    print(f"- Pages loaded from cache: {total_loaded_from_cache_pages}")
    print(f"- Pages parsed: {pages_parsed}")
    print(f"- Total listings detected: {detected_total}")
    print(f"- Total collected: {collected_total}")
    print(f"- Total errors: {errors_total}")
    print(f"- Audit report: {args.output}")

    if top_warnings:
        print("- Main warnings:")
        for warning in top_warnings[:12]:
            print(f"  - {warning}")
    if top_failures:
        print("- Main failures:")
        for failure in top_failures[:12]:
            print(f"  - {failure}")
    main_errors = _extract_main_errors(all_rows)
    if main_errors:
        print("- Main errors:")
        for error in main_errors:
            print(f"  - {error}")

    if status == "FAIL":
        return 1
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
