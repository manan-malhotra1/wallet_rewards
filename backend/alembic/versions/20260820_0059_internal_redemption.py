"""Internal redemption — conversion rates, pair table, new account + config types.

Module 11b (Pay-PRD-1200-1290, design doc 07 §6):
  - extend ck_accounts_type with `points_redemption_wallet` (tenant PTS sink)
    and `cashback_provider_wallet` (per-currency payout source, floored);
  - extend ck_config_change_requests_config_type with `conversion_rate`;
  - create `points_conversion_rates` (one ACTIVE rate per tenant+currency);
  - create `internal_redemptions` (binds the points burn + fiat payout pair,
    with the rate snapshotted).

Revision ID: 0059
Revises: 0058
Create Date: 2026-08-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Full account-type list AFTER this migration (keep in sync with accounts.py).
ACCOUNT_TYPES = (
    "financial_wallet",
    "points_account",
    "system_points_issuance",
    "provider_redemption_wallet",
    "system_cash_inflow",
    "system_fee_collected",
    "operator_adjustment",
    "airtime_merchant_holding",
    "commission",
    "tax_service_collected",
    "tax_commission_collected",
    "points_redemption_wallet",
    "cashback_provider_wallet",
)
_NEW_ACCOUNT_TYPES = ("points_redemption_wallet", "cashback_provider_wallet")

# Full config-type list AFTER this migration (keep in sync with config_requests.py).
CONFIG_TYPES = (
    "pricing",
    "limit",
    "wallet_limit",
    "commission",
    "tax",
    "step_up",
    "conversion_rate",
)


def _recreate_check(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    """Drop and recreate an IN(...) CHECK constraint with the given values."""
    op.drop_constraint(name, table, type_="check")
    values_sql = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(name, table, f"{column} IN ({values_sql})")


def upgrade() -> None:
    """Extend the two CHECK constraints and create the two new tables."""
    _recreate_check("accounts", "ck_accounts_type", "account_type", ACCOUNT_TYPES)
    _recreate_check(
        "config_change_requests",
        "ck_config_change_requests_config_type",
        "config_type",
        CONFIG_TYPES,
    )

    op.create_table(
        "points_conversion_rates",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("points_per_unit", sa.Numeric(20, 6), nullable=False),
        sa.Column("value_per_unit", sa.Numeric(20, 6), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "currency", name="uq_points_conversion_rates_scope"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name="ck_points_conversion_rates_status"
        ),
        sa.CheckConstraint("points_per_unit > 0", name="ck_points_conversion_rates_points"),
        sa.CheckConstraint("value_per_unit > 0", name="ck_points_conversion_rates_value"),
    )
    op.create_index(
        "ix_points_conversion_rates_tenant_id", "points_conversion_rates", ["tenant_id"]
    )

    op.create_table(
        "internal_redemptions",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "points_transaction_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column(
            "payout_transaction_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("points_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("fiat_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("points_per_unit", sa.Numeric(20, 6), nullable=False),
        sa.Column("value_per_unit", sa.Numeric(20, 6), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_internal_redemptions_idempotency"
        ),
    )
    op.create_index("ix_internal_redemptions_tenant_id", "internal_redemptions", ["tenant_id"])
    op.create_index("ix_internal_redemptions_user_id", "internal_redemptions", ["user_id"])


def downgrade() -> None:
    """Drop the new tables and restore the prior CHECK constraints."""
    op.drop_table("internal_redemptions")
    op.drop_table("points_conversion_rates")
    _recreate_check(
        "config_change_requests",
        "ck_config_change_requests_config_type",
        "config_type",
        tuple(t for t in CONFIG_TYPES if t != "conversion_rate"),
    )
    _recreate_check(
        "accounts",
        "ck_accounts_type",
        "account_type",
        tuple(t for t in ACCOUNT_TYPES if t not in _NEW_ACCOUNT_TYPES),
    )
