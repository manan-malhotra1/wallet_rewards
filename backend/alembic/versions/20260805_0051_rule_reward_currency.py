"""rules.reward_currency — per-rule cashback currency

Adds a nullable `reward_currency` (CHAR-ish String(3)) to `rules`. For cashback
rules it holds the financial currency the admin chose for the campaign (e.g.
ZAR/INR) and scopes the reward budget; points rules leave it NULL (points always
accrue in PTS). Nullable so existing rules are unaffected — a legacy cashback
rule with NULL falls back to the triggering event's currency at issuance.

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable rules.reward_currency column."""
    op.add_column("rules", sa.Column("reward_currency", sa.String(length=3), nullable=True))


def downgrade() -> None:
    """Drop rules.reward_currency."""
    op.drop_column("rules", "reward_currency")
