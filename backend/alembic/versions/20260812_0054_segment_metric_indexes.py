"""Index to serve wallet-attributed segment metric aggregates.

Adds `ix_transactions_tenant_status_created` on
`transactions (tenant_id, status, created_at)`. The reworked txn_count /
txn_sum / days_since_last_txn builders in `app.modules.segments.metrics` join
a user's `financial_wallet` ledger entries to their COMPLETED transactions and
filter on tenant + status + a rolling `created_at` window; EXPLAIN on a
synthetic 300k-row `transactions` table showed this turns a parallel seq scan
into a Bitmap Index Scan (~358ms -> ~196ms). `ledger_entries` already has
`ix_ledger_entries_account (account_id, status, created_at)`, which covers the
Account -> LedgerEntry leg of the same join, so no second index is needed
there.

Revision ID: 0054
Revises: 0053
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0054"
down_revision: str | Sequence[str] | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the (tenant_id, status, created_at) index on transactions."""
    op.create_index(
        "ix_transactions_tenant_status_created",
        "transactions",
        ["tenant_id", "status", "created_at"],
    )


def downgrade() -> None:
    """Drop the index."""
    op.drop_index("ix_transactions_tenant_status_created", table_name="transactions")
