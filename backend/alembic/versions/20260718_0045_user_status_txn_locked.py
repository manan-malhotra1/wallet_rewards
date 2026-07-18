"""extend ck_users_status to allow 'txn_locked' (admin access-lock)

Adds a fourth allowed value to the `users.status` CHECK so an admin can put a
user into the transactions-locked access level (can log in / read, but every
user-initiated money path is blocked). Login-lock (`suspended`) and `closed`
already existed. `status` is now ENFORCED at login + every money path — see the
identity service guard and `authenticate_pin`.

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop + recreate ck_users_status to add the 'txn_locked' value."""
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint(
        "ck_users_status",
        "users",
        "status IN ('active', 'suspended', 'closed', 'txn_locked')",
    )


def downgrade() -> None:
    """Restore the original 3-value CHECK.

    IRREVERSIBLE while any `txn_locked` rows exist: recreating the old CHECK
    would reject them and the ALTER TABLE would fail. Operators must first move
    every `txn_locked` user to another status (e.g. `active` or `suspended`)
    before downgrading.
    """
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint(
        "ck_users_status",
        "users",
        "status IN ('active', 'suspended', 'closed')",
    )
