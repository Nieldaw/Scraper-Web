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
