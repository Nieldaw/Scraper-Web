from collections import Counter
from dataclasses import dataclass

from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.source_config import (
    CANTON_MATCHERS,
    ROMANDY_CANTONS,
    infer_detected_canton,
    normalize_canton,
    normalize_detected_canton,
)

VALID_TRANSACTION_TYPES = ("sale", "rent", "unknown", "all")
VALID_CANTONS = ROMANDY_CANTONS


@dataclass(frozen=True)
class FilterStats:
    detected_total: int
    transaction_counts: dict[str, int]
    kept_canton_count: int
    excluded_canton_count: int
    excluded_examples: list[str]
    filtered_count: int


def resolve_canton(*, canton: str | None, region: str | None) -> str | None:
    resolved = normalize_canton(canton) if canton is not None else None
    if region is None:
        return resolved

    normalized_region = region.strip().lower()
    region_to_canton = {
        "geneve": "GE",
        "geneva": "GE",
        "vaud": "VD",
        "neuchatel": "NE",
        "jura": "JU",
        "fribourg": "FR",
        "valais": "VS",
    }
    if normalized_region in region_to_canton:
        return region_to_canton[normalized_region]
    raise ValueError("--region supports: geneve|vaud|neuchatel|jura|fribourg|valais")


def filter_collection_batch(
    batch: CollectionBatch,
    *,
    max_listings: int | None,
    transaction_type: str,
    canton: str | None,
) -> tuple[CollectionBatch, FilterStats]:
    original_count = len(batch.listings)
    tx_counts = Counter(
        str(listing.raw_data.get("transaction_type", "unknown")) for listing in batch.listings
    )
    enriched_listings = []
    for listing in batch.listings:
        raw_data = dict(listing.raw_data)
        existing_detected = normalize_detected_canton(raw_data.get("detected_canton"))  # type: ignore[arg-type]
        existing_reason = raw_data.get("detected_canton_reason")
        inferred_canton, inferred_reason = infer_detected_canton(
            url=listing.url,
            city=listing.city,
            postal_code=listing.postal_code,
        )
        if (
            existing_detected != "unknown"
            and inferred_canton != "unknown"
            and existing_detected != inferred_canton
        ):
            raw_data["detected_canton"] = inferred_canton
            raw_data["detected_canton_reason"] = inferred_reason
        elif existing_detected != "unknown":
            raw_data["detected_canton"] = existing_detected
            raw_data["detected_canton_reason"] = (
                str(existing_reason) if isinstance(existing_reason, str) and existing_reason else "unknown"
            )
        else:
            raw_data["detected_canton"] = inferred_canton
            raw_data["detected_canton_reason"] = inferred_reason
        enriched_listings.append(listing.model_copy(update={"raw_data": raw_data}))

    filtered = list(enriched_listings)
    excluded_examples: list[str] = []
    kept_canton_count = len(filtered)
    excluded_canton_count = 0

    normalized_canton = normalize_canton(canton) if canton else None
    matcher = CANTON_MATCHERS.get(normalized_canton) if normalized_canton else None
    if normalized_canton is not None and matcher is None:
        raise ValueError(f"Unsupported canton filter: {normalized_canton}")

    if matcher is not None:
        kept = []
        excluded = []
        for listing in filtered:
            detected_canton = "unknown"
            if isinstance(listing.raw_data, dict):
                detected_canton = normalize_detected_canton(listing.raw_data.get("detected_canton"))  # type: ignore[arg-type]

            if detected_canton == normalized_canton:
                kept.append(listing)
                continue
            if detected_canton != "unknown":
                excluded.append(listing)
                continue
            if matcher(listing.url, listing.city, listing.postal_code):
                kept.append(listing)
            else:
                excluded.append(listing)
        kept_canton_count = len(kept)
        excluded_canton_count = len(excluded)
        excluded_examples = [item.url for item in excluded[:5]]
        filtered = kept

    if transaction_type != "all":
        filtered = [
            listing
            for listing in filtered
            if listing.raw_data.get("transaction_type", "unknown") == transaction_type
        ]

    if max_listings is not None:
        filtered = filtered[:max_listings]

    return (
        batch.model_copy(update={"listings": filtered, "collected_count": len(filtered)}),
        FilterStats(
            detected_total=original_count,
            transaction_counts={
                "sale": tx_counts.get("sale", 0),
                "rent": tx_counts.get("rent", 0),
                "unknown": tx_counts.get("unknown", 0),
            },
            kept_canton_count=kept_canton_count,
            excluded_canton_count=excluded_canton_count,
            excluded_examples=excluded_examples,
            filtered_count=len(filtered),
        ),
    )
