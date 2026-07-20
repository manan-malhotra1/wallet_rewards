"""extend ck_config_change_requests_config_type to allow 'step_up'

Adds `step_up` to the config types the maker-checker workflow governs so
step-up policy config can be routed through config governance like pricing /
limit / commission / tax.

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop + recreate the config_type CHECK to add the 'step_up' value."""
    op.drop_constraint(
        "ck_config_change_requests_config_type",
        "config_change_requests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_config_change_requests_config_type",
        "config_change_requests",
        "config_type IN ('pricing', 'limit', 'wallet_limit', 'commission', 'tax', 'step_up')",
    )


def downgrade() -> None:
    """Restore the original 5-value CHECK.

    IRREVERSIBLE while any `step_up` rows exist: recreating the old CHECK would
    reject them and the ALTER TABLE would fail. Operators must first remove or
    re-type every `step_up` config-change request before downgrading.
    """
    op.drop_constraint(
        "ck_config_change_requests_config_type",
        "config_change_requests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_config_change_requests_config_type",
        "config_change_requests",
        "config_type IN ('pricing', 'limit', 'wallet_limit', 'commission', 'tax')",
    )
