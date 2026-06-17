"""extend ck_accounts_type with operator_adjustment

Adds the `operator_adjustment` account type to the existing CHECK
constraint so the treasury module can use it as the counter-leg for
admin fund/withdraw actions on the system float.

One row per (tenant, currency) — created lazily by the treasury service
the first time a tenant adjusts a system wallet in that currency.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-17

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep the constant list in sync with `app.shared.models.accounts`.
ALLOWED_TYPES = (
    "financial_wallet",
    "points_account",
    "system_points_issuance",
    "provider_redemption_wallet",
    "system_cash_inflow",
    "system_fee_collected",
    "operator_adjustment",
)


def upgrade() -> None:
    """Drop and recreate ck_accounts_type with the new value included."""
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    types_sql = ", ".join(f"'{t}'" for t in ALLOWED_TYPES)
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        f"account_type IN ({types_sql})",
    )


def downgrade() -> None:
    """Restore the prior 6-value CHECK constraint."""
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    types_sql = ", ".join(
        f"'{t}'" for t in ALLOWED_TYPES if t != "operator_adjustment"
    )
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        f"account_type IN ({types_sql})",
    )
