"""extend ck_accounts_type with airtime_merchant_holding

Adds the `airtime_merchant_holding` account type so the airtime-recharge
module can hold the CREDIT leg of a recharge transaction (escrow) until
either the provider confirms (COMPLETED) or fails / times out
(REVERSED) and ops settles externally with the MNO.

One row per (tenant, currency). Lazy-created by the airtime service.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-19

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALLOWED_TYPES = (
    "financial_wallet",
    "points_account",
    "system_points_issuance",
    "provider_redemption_wallet",
    "system_cash_inflow",
    "system_fee_collected",
    "operator_adjustment",
    "airtime_merchant_holding",
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
    """Restore the prior 7-value CHECK constraint."""
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    types_sql = ", ".join(f"'{t}'" for t in ALLOWED_TYPES if t != "airtime_merchant_holding")
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        f"account_type IN ({types_sql})",
    )
