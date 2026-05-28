from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import DailyRun, Property, PropertyStatus, SourceListing
from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.deduplication import (
    ListingCandidate,
    MatchOutcome,
    decide_property_match,
)
from immo_ne_collector.services.normalization import NormalizedListing
from immo_ne_collector.services.sitn import assess_sitn_eligibility
from immo_ne_collector.services.source_config import infer_detected_canton, normalize_detected_canton
from immo_ne_collector.services.statuses import detect_changed_fields


TRACKED_CHANGE_FIELDS = ("title", "price_chf", "rooms", "living_area_m2", "description")


class PersistenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_run_id: UUID
    collected_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    errors: list[str] = Field(default_factory=list)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _ensure_source_values(values: list[str], new_value: str) -> list[str]:
    if new_value in values:
        return values
    return [*values, new_value]


async def _find_source_listing(
    session: AsyncSession,
    *,
    source: str,
    source_listing_id: str | None,
    url: str,
) -> SourceListing | None:
    if source_listing_id:
        result = await session.execute(
            select(SourceListing).where(
                SourceListing.source == source,
                SourceListing.source_listing_id == source_listing_id,
            )
        )
        return result.scalar_one_or_none()

    # When source_listing_id is absent, URL is used as idempotency fallback.
    # This is supported by the current schema because `source_listings.url` is unique.
    result_by_url = await session.execute(select(SourceListing).where(SourceListing.url == url))
    return result_by_url.scalar_one_or_none()


def _apply_property_state(property_row: Property, *, address_full: str | None, city: str | None) -> None:
    eligibility = assess_sitn_eligibility(address_full=address_full, city=city)
    property_row.needs_completion = eligibility.needs_completion
    property_row.completion_reason = eligibility.completion_reason
    property_row.sitn_eligible = eligibility.eligible
    property_row.sitn_status = eligibility.sitn_status


def _build_candidate_from_listing(listing: NormalizedListing) -> ListingCandidate:
    raw_detected = listing.raw_data.get("detected_canton")
    detected = normalize_detected_canton(raw_detected if isinstance(raw_detected, str) else None)
    inferred, _ = infer_detected_canton(
        url=listing.url,
        city=listing.city,
        postal_code=listing.postal_code,
    )
    if detected != "unknown" and inferred != "unknown" and detected != inferred:
        detected = inferred
    elif detected == "unknown":
        detected = inferred
    return ListingCandidate(
        title=listing.title,
        property_type=listing.property_type,
        city=listing.city,
        price_chf=listing.price_chf,
        rooms=listing.rooms,
        living_area_m2=listing.living_area_m2,
        address_full=listing.address_full,
        detected_canton=detected,
    )


def _build_candidate_from_property(property_row: Property) -> ListingCandidate:
    detected_set: set[str] = set()
    for listing in property_row.listings:
        raw_detected = "unknown"
        if isinstance(listing.raw_data, dict):
            raw_detected = normalize_detected_canton(listing.raw_data.get("detected_canton"))  # type: ignore[arg-type]
        inferred, _ = infer_detected_canton(
            url=listing.url,
            city=listing.city,
            postal_code=listing.postal_code,
        )
        if raw_detected != "unknown" and inferred != "unknown" and raw_detected != inferred:
            detected = inferred
        elif raw_detected != "unknown":
            detected = raw_detected
        else:
            detected = inferred
        if detected != "unknown":
            detected_set.add(detected)
    if len(detected_set) == 1:
        detected_canton = next(iter(detected_set))
    else:
        detected_canton = "unknown"

    return ListingCandidate(
        title=property_row.title,
        property_type=property_row.property_type,
        city=property_row.city,
        price_chf=property_row.price_chf,
        rooms=property_row.rooms,
        living_area_m2=property_row.living_area_m2,
        address_full=property_row.address_full,
        detected_canton=detected_canton,
    )


def _new_source_listing_row(
    *,
    batch_source: str,
    listing: NormalizedListing,
    now: datetime,
    property_id,
) -> SourceListing:
    return SourceListing(
        source=batch_source,
        source_listing_id=listing.source_listing_id,
        url=listing.url,
        title=listing.title,
        property_type=listing.property_type,
        price_chf=listing.price_chf,
        rooms=listing.rooms,
        living_area_m2=listing.living_area_m2,
        address_full=listing.address_full,
        city=listing.city,
        postal_code=listing.postal_code,
        description=listing.description,
        raw_data=dict(listing.raw_data),
        first_seen_at=now,
        last_seen_at=now,
        collected_at=now,
        property_id=property_id,
    )


async def _find_matched_property(
    session: AsyncSession,
    listing: NormalizedListing,
) -> Property | None:
    all_properties = (
        await session.execute(
            select(Property).options(selectinload(Property.listings))
        )
    ).scalars().all()
    if not all_properties:
        return None

    listing_candidate = _build_candidate_from_listing(listing)
    candidates = [(row.id, _build_candidate_from_property(row)) for row in all_properties]
    decision = decide_property_match(listing_candidate, candidates)
    if decision.decision != MatchOutcome.MATCH or decision.matched_property_id is None:
        return None

    return next((row for row in all_properties if row.id == decision.matched_property_id), None)


async def _persist_one_listing(
    session: AsyncSession,
    *,
    batch_source: str,
    listing: NormalizedListing,
) -> str:
    existing_source = await _find_source_listing(
        session,
        source=batch_source,
        source_listing_id=listing.source_listing_id,
        url=listing.url,
    )
    now = listing.fetched_at

    if existing_source is None:
        matched_property = await _find_matched_property(session, listing)
        if matched_property is None:
            property_row = Property(
                title=listing.title,
                property_type=listing.property_type,
                price_chf=listing.price_chf,
                rooms=listing.rooms,
                living_area_m2=listing.living_area_m2,
                address_full=listing.address_full,
                city=listing.city,
                postal_code=listing.postal_code,
                sources=[batch_source],
                source_urls=[listing.url],
                first_seen_at=now,
                last_seen_at=now,
                last_changed_at=now,
                status=PropertyStatus.NEW,
                raw_data=dict(listing.raw_data),
            )
            _apply_property_state(property_row, address_full=listing.address_full, city=listing.city)
            session.add(property_row)
            await session.flush()
            session.add(
                _new_source_listing_row(
                    batch_source=batch_source,
                    listing=listing,
                    now=now,
                    property_id=property_row.id,
                )
            )
            return "created"

        before_property = {
            "title": matched_property.title,
            "price_chf": matched_property.price_chf,
            "rooms": matched_property.rooms,
            "living_area_m2": matched_property.living_area_m2,
        }
        after_property = {
            "title": listing.title,
            "price_chf": listing.price_chf,
            "rooms": listing.rooms,
            "living_area_m2": listing.living_area_m2,
        }
        changed_fields = detect_changed_fields(
            before_property,
            after_property,
            ("title", "price_chf", "rooms", "living_area_m2"),
        )

        matched_property.last_seen_at = now
        matched_property.sources = _ensure_source_values(matched_property.sources, batch_source)
        matched_property.source_urls = _ensure_source_values(matched_property.source_urls, listing.url)
        matched_property.raw_data = dict(listing.raw_data)
        if matched_property.title is None and listing.title is not None:
            matched_property.title = listing.title
        if matched_property.address_full is None and listing.address_full is not None:
            matched_property.address_full = listing.address_full
        if matched_property.postal_code is None and listing.postal_code is not None:
            matched_property.postal_code = listing.postal_code
        if matched_property.city is None and listing.city is not None:
            matched_property.city = listing.city
        if matched_property.property_type is None and listing.property_type is not None:
            matched_property.property_type = listing.property_type
        _apply_property_state(matched_property, address_full=matched_property.address_full, city=matched_property.city)
        if changed_fields:
            matched_property.last_changed_at = now
            matched_property.status = PropertyStatus.UPDATED
        else:
            matched_property.status = PropertyStatus.ACTIVE

        session.add(
            _new_source_listing_row(
                batch_source=batch_source,
                listing=listing,
                now=now,
                property_id=matched_property.id,
            )
        )
        return "created"

    property_row = await session.get(Property, existing_source.property_id) if existing_source.property_id else None
    if property_row is None:
        property_row = Property(
            title=listing.title,
            property_type=listing.property_type,
            price_chf=listing.price_chf,
            rooms=listing.rooms,
            living_area_m2=listing.living_area_m2,
            address_full=listing.address_full,
            city=listing.city,
            postal_code=listing.postal_code,
            sources=[batch_source],
            source_urls=[listing.url],
            first_seen_at=now,
            last_seen_at=now,
            last_changed_at=now,
            status=PropertyStatus.NEW,
            raw_data=dict(listing.raw_data),
        )
        _apply_property_state(property_row, address_full=listing.address_full, city=listing.city)
        session.add(property_row)
        await session.flush()
        existing_source.property_id = property_row.id

    before_source = {
        "title": existing_source.title,
        "description": existing_source.description,
        "price_chf": existing_source.price_chf,
        "rooms": existing_source.rooms,
        "living_area_m2": existing_source.living_area_m2,
    }
    after_source = {
        "title": listing.title,
        "description": listing.description,
        "price_chf": listing.price_chf,
        "rooms": listing.rooms,
        "living_area_m2": listing.living_area_m2,
    }
    changed_fields = detect_changed_fields(before_source, after_source, TRACKED_CHANGE_FIELDS)

    existing_source.url = listing.url
    existing_source.title = listing.title
    existing_source.property_type = listing.property_type
    existing_source.price_chf = listing.price_chf
    existing_source.rooms = listing.rooms
    existing_source.living_area_m2 = listing.living_area_m2
    existing_source.address_full = listing.address_full
    existing_source.city = listing.city
    existing_source.postal_code = listing.postal_code
    existing_source.description = listing.description
    existing_source.raw_data = dict(listing.raw_data)
    existing_source.last_seen_at = now
    existing_source.collected_at = now

    property_row.title = listing.title
    property_row.property_type = listing.property_type
    property_row.price_chf = listing.price_chf
    property_row.rooms = listing.rooms
    property_row.living_area_m2 = listing.living_area_m2
    property_row.address_full = listing.address_full
    property_row.city = listing.city
    property_row.postal_code = listing.postal_code
    property_row.raw_data = dict(listing.raw_data)
    property_row.last_seen_at = now
    property_row.sources = _ensure_source_values(property_row.sources, batch_source)
    property_row.source_urls = _ensure_source_values(property_row.source_urls, listing.url)
    _apply_property_state(property_row, address_full=listing.address_full, city=listing.city)

    if changed_fields:
        property_row.last_changed_at = now
        property_row.status = PropertyStatus.UPDATED
        return "updated"

    property_row.status = PropertyStatus.ACTIVE
    return "unchanged"


async def _persist_collection_batch_in_session(
    session: AsyncSession,
    batch: CollectionBatch,
) -> PersistenceResult:
    started_at = _now_utc()
    daily_run = DailyRun(
        started_at=started_at,
        status="RUNNING",
        stats={"source": batch.source},
    )
    session.add(daily_run)
    await session.commit()
    daily_run_id = daily_run.id

    created_count = 0
    updated_count = 0
    unchanged_count = 0
    try:
        for listing in batch.listings:
            outcome = await _persist_one_listing(
                session,
                batch_source=batch.source,
                listing=listing,
            )
            if outcome == "created":
                created_count += 1
            elif outcome == "updated":
                updated_count += 1
            else:
                unchanged_count += 1

        await session.commit()
        await session.execute(
            update(DailyRun)
            .where(DailyRun.id == daily_run_id)
            .values(
                finished_at=_now_utc(),
                status="SUCCESS",
                stats={
                    "source": batch.source,
                    "collected_count": batch.collected_count,
                    "created_count": created_count,
                    "updated_count": updated_count,
                    "unchanged_count": unchanged_count,
                    "error_count": 0,
                },
                error=None,
            )
        )
        await session.commit()

        return PersistenceResult(
            daily_run_id=daily_run_id,
            collected_count=batch.collected_count,
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            errors=[],
        )
    except Exception as exc:
        await session.rollback()

        await session.execute(
            update(DailyRun)
            .where(DailyRun.id == daily_run_id)
            .values(
                finished_at=_now_utc(),
                status="FAILED",
                stats={
                    "source": batch.source,
                    "collected_count": batch.collected_count,
                    "created_count": 0,
                    "updated_count": 0,
                    "unchanged_count": 0,
                    "error_count": 1,
                },
                error=str(exc),
            )
        )
        await session.commit()

        return PersistenceResult(
            daily_run_id=daily_run_id,
            collected_count=batch.collected_count,
            created_count=0,
            updated_count=0,
            unchanged_count=0,
            errors=[str(exc)],
        )


async def persist_collection_batch(
    batch: CollectionBatch,
    session: AsyncSession | None = None,
) -> PersistenceResult:
    if session is not None:
        return await _persist_collection_batch_in_session(session, batch)

    async with AsyncSessionLocal() as owned_session:
        return await _persist_collection_batch_in_session(owned_session, batch)
