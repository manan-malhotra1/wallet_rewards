"""add shared_secret column to redemption_providers (Phase F.5)

External providers callback `POST /redemption/{id}/callback` with an
HMAC-SHA256 signature; the secret used to verify lives in this new column.
NULL = provider has no callbacks enabled (admin operator overrides only).

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable shared_secret column to redemption_providers."""
    op.add_column(
        "redemption_providers",
        sa.Column("shared_secret", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop the column. Safe — no other table references it."""
    op.drop_column("redemption_providers", "shared_secret")
