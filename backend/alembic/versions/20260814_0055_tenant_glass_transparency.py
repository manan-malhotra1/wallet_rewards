"""Add per-tenant glassmorphism transparency slider column.

Adds nullable `brand_glass_transparency` (Integer, 0-100) to `tenants`,
guarded by a `ck_tenants_glass_transparency_range` CHECK constraint. NULL
means "no override" — the admin UI glass theme falls back to the default
transparency of 50, which reproduces today's static panel alpha values
(see `admin-ui/lib/glass-tokens.ts`). This mirrors the existing branding
columns (`brand_accent_color`, `brand_light_color`, `brand_icon_url`):
nullable, cosmetic, edited via the same `PUT /api/v1/tenants/{id}/branding`
endpoint.

Revision ID: 0055
Revises: 0054
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable glass-transparency column and its 0-100 CHECK constraint."""
    op.add_column(
        "tenants",
        sa.Column("brand_glass_transparency", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_tenants_glass_transparency_range",
        "tenants",
        "brand_glass_transparency BETWEEN 0 AND 100",
    )


def downgrade() -> None:
    """Drop the CHECK constraint and the column."""
    op.drop_constraint("ck_tenants_glass_transparency_range", "tenants", type_="check")
    op.drop_column("tenants", "brand_glass_transparency")
