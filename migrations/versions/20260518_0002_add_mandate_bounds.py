"""Add missing mandate bounds fields for MVP filters.

Revision ID: 20260518_0002
Revises: 20260518_0001
Create Date: 2026-05-18
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260518_0002"
down_revision = "20260518_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_mandates", sa.Column("max_rooms", sa.Numeric(precision=4, scale=1), nullable=True))
    op.add_column(
        "search_mandates",
        sa.Column("max_living_area_m2", sa.Numeric(precision=8, scale=2), nullable=True),
    )
    op.add_column(
        "search_mandates",
        sa.Column("only_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.alter_column("search_mandates", "only_active", server_default=None)


def downgrade() -> None:
    op.drop_column("search_mandates", "only_active")
    op.drop_column("search_mandates", "max_living_area_m2")
    op.drop_column("search_mandates", "max_rooms")
