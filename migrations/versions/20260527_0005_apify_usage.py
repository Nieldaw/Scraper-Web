"""Suivi des coûts Apify (table apify_usage).

Revision ID: 20260527_0005
Revises: 20260526_0004
Create Date: 2026-05-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260527_0005"
down_revision = "20260526_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "apify_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("cost", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(40), nullable=False),
    )
    op.create_index("ix_apify_usage_date", "apify_usage", ["date"])
    op.create_index("ix_apify_usage_actor_id", "apify_usage", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_apify_usage_actor_id", table_name="apify_usage")
    op.drop_index("ix_apify_usage_date", table_name="apify_usage")
    op.drop_table("apify_usage")
