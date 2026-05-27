import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from immo_ne_collector.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PropertyStatus(StrEnum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    UPDATED = "UPDATED"
    INACTIVE = "INACTIVE"
    REMOVED = "REMOVED"


class SitnStatus(StrEnum):
    OK = "OK"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    NOT_ELIGIBLE_MISSING_ADDRESS = "NOT_ELIGIBLE_MISSING_ADDRESS"
    NOT_RUN = "NOT_RUN"


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(Text)
    property_type: Mapped[str | None] = mapped_column(String(80), index=True)
    price_chf: Mapped[float | None] = mapped_column(Numeric(12, 2), index=True)
    rooms: Mapped[float | None] = mapped_column(Numeric(4, 1))
    living_area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2))
    address_full: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10))
    sources: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_urls: Mapped[list[str]] = mapped_column(JSONB, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default=PropertyStatus.NEW, index=True)
    needs_completion: Mapped[bool] = mapped_column(Boolean, default=False)
    completion_reason: Mapped[str | None] = mapped_column(String(120))
    sitn_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    sitn_status: Mapped[str] = mapped_column(String(80), default=SitnStatus.NOT_RUN)
    sitn_bien_fonds: Mapped[str | None] = mapped_column(String(120))
    sitn_owner_name: Mapped[str | None] = mapped_column(Text)
    sitn_url: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    listings: Mapped[list["SourceListing"]] = relationship(back_populates="property")


class SourceListing(Base):
    __tablename__ = "source_listings"
    __table_args__ = (
        UniqueConstraint("source", "source_listing_id", name="uq_source_listing_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(100), index=True)
    source_listing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    property_type: Mapped[str | None] = mapped_column(String(80))
    price_chf: Mapped[float | None] = mapped_column(Numeric(12, 2))
    rooms: Mapped[float | None] = mapped_column(Numeric(4, 1))
    living_area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2))
    address_full: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("properties.id"),
        nullable=True,
        index=True,
    )

    property: Mapped[Property | None] = relationship(back_populates="listings")


class SearchMandate(Base):
    __tablename__ = "search_mandates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    cities: Mapped[list[str]] = mapped_column(JSONB, default=list)
    property_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    min_price_chf: Mapped[float | None] = mapped_column(Numeric(12, 2))
    max_price_chf: Mapped[float | None] = mapped_column(Numeric(12, 2))
    min_rooms: Mapped[float | None] = mapped_column(Numeric(4, 1))
    max_rooms: Mapped[float | None] = mapped_column(Numeric(4, 1))
    min_living_area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2))
    max_living_area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2))
    only_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyRun(Base):
    __tablename__ = "daily_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="RUNNING")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
