"""add partial unique indexes to accounts (close duplicate-seed bug)

Phase F.5.1 follow-up. The seed script's idempotent "get-or-create" pattern
silently created duplicate system accounts on re-runs because there was no
UNIQUE constraint at the schema level. Two partial unique indexes lock the
invariant in:

  - `uq_accounts_user_scoped`   — one row per (tenant, user, type, currency)
                                   when user_id IS NOT NULL
  - `uq_accounts_system_scoped` — one row per (tenant, type, currency)
                                   when user_id IS NULL

We need TWO indexes (not one plain UNIQUE) because Postgres treats NULLs as
distinct in a regular UNIQUE constraint, which would let any number of
system accounts with the same (tenant, type, currency) slip through.

If your live DB already has duplicate rows this migration will fail. Run
`scripts/dedupe_accounts.sql` first (or just `docker compose down -v` on
the local stack) to wipe state before applying.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-16

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the two partial unique indexes."""
    op.create_index(
        "uq_accounts_user_scoped",
        "accounts",
        ["tenant_id", "user_id", "account_type", "currency"],
        unique=True,
        postgresql_where="user_id IS NOT NULL",
    )
    op.create_index(
        "uq_accounts_system_scoped",
        "accounts",
        ["tenant_id", "account_type", "currency"],
        unique=True,
        postgresql_where="user_id IS NULL",
    )


def downgrade() -> None:
    """Drop the indexes — reverts to the pre-0009 schema."""
    op.drop_index("uq_accounts_system_scoped", table_name="accounts")
    op.drop_index("uq_accounts_user_scoped", table_name="accounts")
