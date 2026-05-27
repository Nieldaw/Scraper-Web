from collections import Counter
from dataclasses import dataclass

from immo_ne_collector.scrapers.anibis_utils import is_canton_ne_listing
from immo_ne_collector.services.collection import CollectionBatch

VALID_TRANSACTION_TYPES = ("sale", "rent", "unknown", "all")
VALID_CANTONS = ("NE",)


@dataclass(frozen=True)
class FilterStats:
    detected_total: int
    transaction_counts: dict[str, int]
    kept_canton_count: int
    excluded_canton_count: int
    excluded_examples: list[str]
    filtered_count: int


def resolve_canton(*, canton: str | None, region: str | None) -> str | None:
    resolved = canton
    if region is None:
        return resolved

    normalized_region = region.strip().lower()
    if normalized_region == "neuchatel":
        return "NE"
    raise ValueError("--region only supports 'neuchatel' in MVP")


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
    filtered = list(batch.listings)
    excluded_examples: list[str] = []
    kept_canton_count = len(filtered)
    excluded_canton_count = 0

    if canton == "NE":
        kept = []
        excluded = []
        for listing in filtered:
            if is_canton_ne_listing(listing.url, listing.city, listing.postal_code):
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
