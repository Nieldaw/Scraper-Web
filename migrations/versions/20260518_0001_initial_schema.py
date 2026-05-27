"""Initial schema for MVP models.

Revision ID: 20260518_0001
Revises:
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260518_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("property_type", sa.String(length=80), nullable=True),
        sa.Column("price_chf", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("rooms", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("living_area_m2", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("address_full", sa.Text(), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("postal_code", sa.String(length=10), nullable=True),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("needs_completion", sa.Boolean(), nullable=False),
        sa.Column("completion_reason", sa.String(length=120), nullable=True),
        sa.Column("sitn_eligible", sa.Boolean(), nullable=False),
        sa.Column("sitn_status", sa.String(length=80), nullable=False),
        sa.Column("sitn_bien_fonds", sa.String(length=120), nullable=True),
        sa.Column("sitn_owner_name", sa.Text(), nullable=True),
        sa.Column("sitn_url", sa.Text(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_properties_city", "properties", ["city"], unique=False)
    op.create_index(
        "ix_properties_last_changed_at",
        "properties",
        ["last_changed_at"],
        unique=False,
    )
    op.create_index("ix_properties_last_seen_at", "properties", ["last_seen_at"], unique=False)
    op.create_index("ix_properties_price_chf", "properties", ["price_chf"], unique=False)
    op.create_index("ix_properties_property_type", "properties", ["property_type"], unique=False)
    op.create_index("ix_properties_status", "properties", ["status"], unique=False)

    op.create_table(
        "search_mandates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("cities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("property_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("min_price_chf", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("max_price_chf", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("min_rooms", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("min_living_area_m2", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "source_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_listing_id", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("property_type", sa.String(length=80), nullable=True),
        sa.Column("price_chf", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("rooms", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("living_area_m2", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("address_full", sa.Text(), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("postal_code", sa.String(length=10), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_listing_id", name="uq_source_listing_id"),
        sa.UniqueConstraint("url"),
    )
    op.create_index("ix_source_listings_city", "source_listings", ["city"], unique=False)
    op.create_index(
        "ix_source_listings_content_hash",
        "source_listings",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_source_listings_property_id",
        "source_listings",
        ["property_id"],
        unique=False,
    )
    op.create_index("ix_source_listings_source", "source_listings", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_source_listings_source", table_name="source_listings")
    op.drop_index("ix_source_listings_property_id", table_name="source_listings")
    op.drop_index("ix_source_listings_content_hash", table_name="source_listings")
    op.drop_index("ix_source_listings_city", table_name="source_listings")
    op.drop_table("source_listings")

    op.drop_table("search_mandates")

    op.drop_index("ix_properties_status", table_name="properties")
    op.drop_index("ix_properties_property_type", table_name="properties")
    op.drop_index("ix_properties_price_chf", table_name="properties")
    op.drop_index("ix_properties_last_seen_at", table_name="properties")
    op.drop_index("ix_properties_last_changed_at", table_name="properties")
    op.drop_index("ix_properties_city", table_name="properties")
    op.drop_table("properties")

    op.drop_table("daily_runs")
