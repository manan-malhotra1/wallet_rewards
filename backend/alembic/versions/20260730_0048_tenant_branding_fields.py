"""add per-tenant branding fields (accent/light colours + logo URL) to tenants

Adds three nullable columns that drive the admin UI's per-tenant theme: two
anchor colours (`brand_accent_color`, `brand_light_color`) the UI interpolates
into a derived palette, plus `brand_icon_url` for the sidebar logo. All nullable
so an unbranded tenant falls back to the app default — no backfill.

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048"
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the three nullable branding columns to `tenants`."""
    op.add_column("tenants", sa.Column("brand_accent_color", sa.String(length=9), nullable=True))
    op.add_column("tenants", sa.Column("brand_light_color", sa.String(length=9), nullable=True))
    op.add_column("tenants", sa.Column("brand_icon_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the three branding columns."""
    op.drop_column("tenants", "brand_icon_url")
    op.drop_column("tenants", "brand_light_color")
    op.drop_column("tenants", "brand_accent_color")
