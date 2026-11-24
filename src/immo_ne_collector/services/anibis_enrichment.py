"""Enrichissement des annonces Anibis par leur fiche de détail.

Garde-fous : plafond `max_details`, délai entre requêtes, cache HTML réutilisé, arrêt dès
un blocage (403/429). Les annonces non enrichies sont marquées `price_status=unverified`.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

from immo_ne_collector.scrapers.anibis_detail import AnibisDetailParseError, parse_anibis_detail
from immo_ne_collector.scrapers.http_fetcher import (
    ScraperHTTPError,
    build_cache_filename,
    fetch_html_to_cache,
)
from immo_ne_collector.scrapers.safety import RateLimiter, SafetyConfig
from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.normalization import (
    NormalizedListing,
    normalize_address_full,
    normalize_area_m2,
    normalize_description,
    normalize_price_chf,
    normalize_rooms,
    normalize_title,
)

DEFAULT_MAX_DETAILS = 30


@dataclass
class EnrichmentReport:
    attempted: int = 0
    enriched: int = 0
    from_cache: int = 0
    failed: int = 0
    skipped_over_cap: int = 0
    stopped_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def find_cached_detail(url: str, cache_dir: Path, max_age_hours: float) -> Path | None:
    """Fiche déjà en cache (même URL), plus récente que `max_age_hours`."""
    suffix = build_cache_filename(url).split("_", 1)[1]
    candidates = sorted(cache_dir.glob(f"*_{suffix}"), reverse=True)
    for path in candidates:
        if time.time() - path.stat().st_mtime <= max_age_hours * 3600:
            return path
    return None


def _apply_detail(listing: NormalizedListing, html_text: str) -> NormalizedListing:
    detail = parse_anibis_detail(html_text)
    raw = dict(listing.raw_data)
    raw["search_page_values"] = {
        "price_chf": str(listing.price_chf) if listing.price_chf is not None else None,
        "rooms": str(listing.rooms) if listing.rooms is not None else None,
        "title": listing.title,
    }
    raw["price_status"] = "detail_page" if detail.price_raw else "no_price_on_detail"
    if detail.plot_area_raw:
        raw["plot_area_m2"] = str(normalize_area_m2(detail.plot_area_raw))
    if detail.price_is_rent:
        raw["detail_price_is_rent"] = True

    update = {
        "title": normalize_title(detail.title) or listing.title,
        "description": normalize_description(detail.description) or listing.description,
        # La fiche fait foi : pas de repli sur la page de résultats si une valeur manque.
        "price_chf": normalize_price_chf(detail.price_raw),
        "rooms": normalize_rooms(detail.rooms_raw),
        "living_area_m2": normalize_area_m2(detail.living_area_raw),
        "address_full": normalize_address_full(detail.address_raw) or listing.address_full,
        "raw_data": raw,
    }
    return listing.model_copy(update=update)


def _mark_unverified(listing: NormalizedListing) -> NormalizedListing:
    raw = dict(listing.raw_data)
    raw["price_status"] = "unverified_search_page"
    return listing.model_copy(update={"raw_data": raw})


async def enrich_anibis_batch(
    batch: CollectionBatch,
    *,
    max_details: int | None = DEFAULT_MAX_DETAILS,
    delay_seconds: float = 1.0,
    timeout: float | None = None,
    retries: int | None = None,
    cache_dir: Path = Path("data/cache/html"),
    cache_max_age_hours: float = 24,
    fetch=fetch_html_to_cache,
) -> tuple[CollectionBatch, EnrichmentReport]:
    report = EnrichmentReport()
    safety = SafetyConfig(
        timeout_seconds=timeout or 20.0,
        max_retries=1 if retries is None else retries,
        min_interval_seconds=delay_seconds,
    )
    limiter = RateLimiter(safety.min_interval_seconds)
    cap = max_details if max_details is not None else len(batch.listings)
    out: list[NormalizedListing] = []
    blocked = False

    for listing in batch.listings:
        if blocked or report.attempted >= cap:
            if not blocked:
                report.skipped_over_cap += 1
            out.append(_mark_unverified(listing))
            continue
        report.attempted += 1
        try:
            cached = find_cached_detail(listing.url, cache_dir, cache_max_age_hours)
            if cached is not None:
                report.from_cache += 1
                html_text = cached.read_text(encoding="utf-8")
            else:
                result = await fetch(
                    url=listing.url,
                    cache_dir=cache_dir,
                    source="anibis_detail",
                    safety=safety,
                    rate_limiter=limiter,
                )
                html_text = Path(result.file_path).read_text(encoding="utf-8")
            out.append(_apply_detail(listing, html_text))
            report.enriched += 1
        except ScraperHTTPError as exc:
            report.failed += 1
            out.append(_mark_unverified(listing))
            report.warnings.append(f"Fiche {listing.url} : HTTP {exc.status_code}")
            if exc.status_code in (403, 429):
                blocked = True
                report.stopped_reason = f"HTTP_{exc.status_code}"
                report.warnings.append(
                    f"Anibis bloque les fiches de détail (HTTP {exc.status_code}) : "
                    "enrichissement interrompu, prix non vérifiés."
                )
        except (AnibisDetailParseError, OSError, RuntimeError, TimeoutError) as exc:
            report.failed += 1
            out.append(_mark_unverified(listing))
            report.warnings.append(f"Fiche {listing.url} : {type(exc).__name__}: {exc}")

    if report.skipped_over_cap:
        report.warnings.append(
            f"{report.skipped_over_cap} annonce(s) au-delà du plafond de {cap} fiches : "
            "prix non vérifiés (page de résultats)."
        )
    return batch.model_copy(update={"listings": out}), report
