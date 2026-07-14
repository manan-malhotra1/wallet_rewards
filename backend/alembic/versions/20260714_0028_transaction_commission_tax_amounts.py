"""add commission_amount + tax_amount to transactions (Pricing v2 Epic 20)

Story 20.2 — display-only siblings to `transactions.fee_amount`. The economics
already live in the balanced ledger legs; these surface the agent commission
and the total tax on the transaction row. Default 0 backfills every pre-v2 row.

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the two display columns, defaulting existing rows to 0."""
    op.add_column(
        "transactions",
        sa.Column("commission_amount", sa.Numeric(20, 6), server_default="0", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("tax_amount", sa.Numeric(20, 6), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Drop the two display columns."""
    op.drop_column("transactions", "tax_amount")
    op.drop_column("transactions", "commission_amount")
