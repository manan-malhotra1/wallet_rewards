"""Per-transaction internal-redemption caps on points_conversion_rates.

Pay-PRD-1295 (anti-drain): `max_points_per_txn` (absolute) and
`max_balance_pct_per_txn` (percentage of the user's current points balance)
bound a SINGLE internal redemption. Both NULLable — NULL = uncapped.

Revision ID: 0060
Revises: 0059
Create Date: 2026-08-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the two nullable cap columns + their sanity CHECKs."""
    op.add_column(
        "points_conversion_rates",
        sa.Column("max_points_per_txn", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "points_conversion_rates",
        sa.Column("max_balance_pct_per_txn", sa.Numeric(5, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_points_conversion_rates_txn_cap",
        "points_conversion_rates",
        "max_points_per_txn IS NULL OR max_points_per_txn > 0",
    )
    op.create_check_constraint(
        "ck_points_conversion_rates_pct_cap",
        "points_conversion_rates",
        "max_balance_pct_per_txn IS NULL OR "
        "(max_balance_pct_per_txn > 0 AND max_balance_pct_per_txn <= 100)",
    )


def downgrade() -> None:
    """Drop the cap columns and their CHECKs."""
    op.drop_constraint("ck_points_conversion_rates_pct_cap", "points_conversion_rates", type_="check")
    op.drop_constraint("ck_points_conversion_rates_txn_cap", "points_conversion_rates", type_="check")
    op.drop_column("points_conversion_rates", "max_balance_pct_per_txn")
    op.drop_column("points_conversion_rates", "max_points_per_txn")
