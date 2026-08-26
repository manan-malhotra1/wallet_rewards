"""Commission wallet foundation — account type + tenant flag.

Adds `commission_wallet` to ck_accounts_type and `tenants.commission_wallet_enabled`.
Spec: docs/superpowers/specs/2026-08-26-commission-wallet-design.md §4.1, §4.2.

Revision ID: 0066
Revises: 0065
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = (
    "'financial_wallet', 'points_account', 'system_points_issuance', "
    "'provider_redemption_wallet', 'system_cash_inflow', 'system_fee_collected', "
    "'operator_adjustment', 'airtime_merchant_holding', 'commission', "
    "'tax_service_collected', 'tax_commission_collected', "
    "'points_redemption_wallet', 'cashback_provider_wallet'"
)
_NEW_TYPES = _OLD_TYPES + ", 'commission_wallet'"


def upgrade() -> None:
    """Add the commission_wallet account type and the per-tenant enable flag."""
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint("ck_accounts_type", "accounts", f"account_type IN ({_NEW_TYPES})")
    op.add_column(
        "tenants",
        sa.Column(
            "commission_wallet_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    """Drop the flag and restore the pre-commission-wallet account-type CHECK."""
    op.drop_column("tenants", "commission_wallet_enabled")
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint("ck_accounts_type", "accounts", f"account_type IN ({_OLD_TYPES})")
