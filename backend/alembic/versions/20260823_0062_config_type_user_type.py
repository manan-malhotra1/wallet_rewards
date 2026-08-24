"""extend ck_config_change_requests_config_type to allow 'user_type'

Adds `user_type` to the config types the maker-checker workflow governs, so
creating / relabelling / retiring / reactivating a configurable user type is a
four-eyes proposal like pricing / limit / commission / tax (spec 2026-08-23 D4).

Revision ID: 0062
Revises: 0061
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0062"
down_revision: str | Sequence[str] | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_NAME = "ck_config_change_requests_config_type"
_TABLE = "config_change_requests"
_WITHOUT_USER_TYPE = (
    "config_type IN ('pricing', 'limit', 'wallet_limit', 'commission', "
    "'tax', 'step_up', 'conversion_rate')"
)
_WITH_USER_TYPE = (
    "config_type IN ('pricing', 'limit', 'wallet_limit', 'commission', "
    "'tax', 'step_up', 'conversion_rate', 'user_type')"
)


def upgrade() -> None:
    """Drop + recreate the config_type CHECK to add the 'user_type' value."""
    op.drop_constraint(_CHECK_NAME, _TABLE, type_="check")
    op.create_check_constraint(_CHECK_NAME, _TABLE, _WITH_USER_TYPE)


def downgrade() -> None:
    """Restore the seven-value CHECK.

    IRREVERSIBLE while any `user_type` request rows exist: recreating the
    narrower CHECK would reject them and the ALTER TABLE fails loudly rather
    than half-applying. Operators must remove those rows before downgrading.
    """
    op.drop_constraint(_CHECK_NAME, _TABLE, type_="check")
    op.create_check_constraint(_CHECK_NAME, _TABLE, _WITHOUT_USER_TYPE)
