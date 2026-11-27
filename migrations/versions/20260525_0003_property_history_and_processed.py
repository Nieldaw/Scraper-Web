"""Historique des modifications d'un bien et statut « traité ».

Revision ID: 20260525_0003
Revises: 20260518_0002
Create Date: 2026-05-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260525_0003"
down_revision = "20260518_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("is_processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_properties_is_processed", "properties", ["is_processed"])
    op.create_table(
        "property_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field", sa.String(40), nullable=False),
        sa.Column("old_value", sa.Text()),
        sa.Column("new_value", sa.Text()),
        sa.Column("source", sa.String(100)),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_property_history_property_id", "property_history", ["property_id"])
    op.create_index("ix_property_history_changed_at", "property_history", ["changed_at"])


def downgrade() -> None:
    op.drop_table("property_history")
    op.drop_index("ix_properties_is_processed", table_name="properties")
    op.drop_column("properties", "is_processed")
