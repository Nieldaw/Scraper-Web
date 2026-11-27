from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PropertyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(alias="property_id")
    title: str | None = None
    property_type: str | None = None
    price_chf: float | None = None
    rooms: float | None = None
    living_area_m2: float | None = None
    address_full: str | None = None
    city: str | None = None
    postal_code: str | None = None
    sources: list[str] = []
    source_urls: list[str] = []
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime | None = None
    status: str
    needs_completion: bool
    completion_reason: str | None = None
    sitn_eligible: bool
    sitn_status: str
    sitn_bien_fonds: str | None = None
    sitn_owner_name: str | None = None
    sitn_url: str | None = None


class SearchMandateCreate(BaseModel):
    name: str
    cities: list[str] = []
    property_types: list[str] = []
    min_price_chf: float | None = None
    max_price_chf: float | None = None
    min_rooms: float | None = None
    max_rooms: float | None = None
    min_living_area_m2: float | None = None
    max_living_area_m2: float | None = None
    only_active: bool = True


class PropertyOut(BaseModel):
    """Bien tel qu'exposé par l'API et les cartes de l'interface."""

    id: UUID
    title: str | None = None
    property_type: str | None = None
    price_chf: float | None = None
    rooms: float | None = None
    living_area_m2: float | None = None
    address_full: str | None = None
    city: str | None = None
    postal_code: str | None = None
    sources: list[str] = []
    source_urls: list[str] = []
    status: str
    status_label: str
    image_url: str | None = None
    price_status: str | None = None  # "verified" (fiche) | "estimated" (page de résultats) | None
    is_processed: bool = False
    price_status_label: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime | None = None
    needs_completion: bool = False
    sitn_status: str | None = None


class PropertyListResponse(BaseModel):
    items: list[PropertyOut]
    total: int
    page: int
    page_size: int


class StatsOut(BaseModel):
    new: int
    active: int
    modified: int
    inactive: int
    total: int


class SearchMandateOut(SearchMandateCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool = True
    created_at: datetime


class DailyRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    stats: dict = {}
    error: str | None = None


class MandateMatchesOut(BaseModel):
    mandate_id: UUID
    total: int
    items: list[PropertyOut]
