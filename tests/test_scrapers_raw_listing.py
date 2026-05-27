from datetime import datetime

import pytest
from pydantic import ValidationError

from immo_ne_collector.scrapers.base import RawListing


def test_raw_listing_minimum_fields() -> None:
    listing = RawListing(
        source="mock",
        source_listing_id="x-1",
        url="https://mock.local/x-1",
        title="Annonce test",
        raw_data={"ok": True},
    )
    assert listing.source == "mock"
    assert listing.source_listing_id == "x-1"
    assert listing.raw_data["ok"] is True


def test_raw_listing_sets_fetched_at_by_default() -> None:
    listing = RawListing(source="mock", url="https://mock.local/x-2")
    assert isinstance(listing.fetched_at, datetime)
    assert listing.fetched_at.tzinfo is not None


def test_raw_listing_rejects_empty_source_or_url() -> None:
    with pytest.raises(ValidationError):
        RawListing(source=" ", url="https://mock.local/x-3")

    with pytest.raises(ValidationError):
        RawListing(source="mock", url="  ")
