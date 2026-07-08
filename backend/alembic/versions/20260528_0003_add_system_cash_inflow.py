"""add system_cash_inflow to accounts.account_type CHECK constraint

The new account type is the debit-side master for money entering the system
from outside (top-ups, mobile money receipts). See
docs/06-data-architecture.md §4 addendum (Phase B).

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-28

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the existing CHECK then add the new one with the extra value.
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        (
            "account_type IN ("
            "'financial_wallet', "
            "'points_account', "
            "'system_points_issuance', "
            "'provider_redemption_wallet', "
            "'system_cash_inflow'"
            ")"
        ),
    )


def downgrade() -> None:
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        (
            "account_type IN ("
            "'financial_wallet', "
            "'points_account', "
            "'system_points_issuance', "
            "'provider_redemption_wallet'"
            ")"
        ),
    )
