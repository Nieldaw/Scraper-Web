"""Coordonnées (latitude/longitude) des biens.

Revision ID: 20260526_0004
Revises: 20260525_0003
Create Date: 2026-05-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260526_0004"
down_revision = "20260525_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("properties", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("properties", "longitude")
    op.drop_column("properties", "latitude")
