"""track when each balance snapshot was last verified against the ledger

The drift sweep picked accounts by `snapshot_at DESC` — most recently *written*
first. That silently misses the population that matters: an account that drifts
and then goes quiet sinks down the ordering and is never re-checked, while the
sweep keeps reporting "no drift". Observed live — a known-drifted account sat at
rank 344 of 422 and was skipped by every run of a 200-account batch.

`last_verified_at` makes coverage a round-robin instead: oldest-verified first,
so every account is reached within `ceil(total / batch)` sweeps no matter how
busy it is.

It is NOT NULL defaulting to `-infinity` rather than nullable. "Never verified"
then sorts first under a plain ascending index, so the sweep's ORDER BY is
index-served — a nullable column would need `NULLS FIRST`, which matches neither
scan direction of a normal btree and would sort the whole table every run.

Revision ID: 0072
Revises: 0071
Create Date: 2026-08-31

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the verification timestamp plus the index the sweep orders by."""
    op.add_column(
        "account_balance_snapshots",
        sa.Column(
            "last_verified_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("'-infinity'"),
        ),
    )
    op.create_index(
        "ix_account_balance_snapshots_last_verified",
        "account_balance_snapshots",
        ["last_verified_at"],
    )


def downgrade() -> None:
    """Drop the column and its index."""
    op.drop_index(
        "ix_account_balance_snapshots_last_verified",
        table_name="account_balance_snapshots",
    )
    op.drop_column("account_balance_snapshots", "last_verified_at")
