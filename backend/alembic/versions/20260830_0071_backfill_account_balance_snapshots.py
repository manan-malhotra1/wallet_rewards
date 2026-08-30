"""backfill account_balance_snapshots from the ledger

`account_balance_snapshots` has existed since the ledger schema landed but was
never written or read — the balance was re-derived from `ledger_entries` on
every call. That aggregate grows with an account's whole history and runs while
holding the account write lock inside `post_transaction`, so on a shared account
it got slower forever: the tenant's `system_fee_collected` takes an entry from
EVERY transaction (432k rows/day at 5 TPS), and the read measured 931ms by 5M
entries.

`derive_balance` now reads this table, so every existing account needs a row
before that read can be trusted. Accounts with no entries get an explicit zero
row rather than being skipped, so the fast path is a plain UPDATE for everyone
from here on.

This is idempotent: re-running recomputes the same absolute values. Application
code degrades safely without it (a missing row falls back to deriving from the
ledger and seeds itself), so this is a performance backfill, not a correctness
prerequisite.

Revision ID: 0071
Revises: 0070
Create Date: 2026-08-30

"""

from __future__ import annotations

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Insert one snapshot per account, derived from its ledger entries.

    Mirrors `ledger/snapshots.sum_from_ledger` exactly: balance sums COMPLETED
    entries with CREDIT positive; reserved sums PENDING entries mirrored (a
    pending DEBIT holds funds, a pending CREDIT releases them). REVERSED entries
    contribute to neither.
    """
    op.execute(
        """
        INSERT INTO account_balance_snapshots
            (account_id, balance, reserved_balance, snapshot_at)
        SELECT
            a.id,
            COALESCE(SUM(
                CASE WHEN le.status = 'COMPLETED' THEN
                    CASE
                        WHEN le.entry_type = 'CREDIT' THEN le.amount
                        WHEN le.entry_type = 'DEBIT'  THEN -le.amount
                        ELSE 0
                    END
                ELSE 0 END
            ), 0),
            COALESCE(SUM(
                CASE WHEN le.status = 'PENDING' THEN
                    CASE
                        WHEN le.entry_type = 'DEBIT'  THEN le.amount
                        WHEN le.entry_type = 'CREDIT' THEN -le.amount
                        ELSE 0
                    END
                ELSE 0 END
            ), 0),
            now()
        FROM accounts a
        LEFT JOIN ledger_entries le ON le.account_id = a.id
        GROUP BY a.id
        ON CONFLICT (account_id) DO UPDATE SET
            balance          = EXCLUDED.balance,
            reserved_balance = EXCLUDED.reserved_balance,
            snapshot_at      = now()
        """
    )


def downgrade() -> None:
    """Empty the cache, returning the table to its previous unused state.

    Safe: `derive_balance` falls back to deriving from `ledger_entries` when an
    account has no snapshot row, so removing these rows costs performance, not
    correctness.
    """
    op.execute("DELETE FROM account_balance_snapshots")
