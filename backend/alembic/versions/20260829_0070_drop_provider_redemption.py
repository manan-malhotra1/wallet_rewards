"""drop the provider-fulfilled redemption path

Points are already monetised into real money by the INTERNAL redemption path
(Module 11b): the user burns points and their own wallet is credited at the
tenant's configured rate. The provider-fulfilled route added a second way to
turn points into value — one that settled asynchronously through an external
partner and needed its own reconciliation sweep to chase stale PENDING rows.
Two routes to the same outcome confused both operators and the ledger story,
so the provider one is removed rather than deprecated.

This drops `redemptions` and `redemption_providers`, deletes the
`provider_redemption_wallet` accounts those providers owned, and narrows
`ck_accounts_type` so the type cannot be written again. `points_conversion_rates`
and `internal_redemptions` — the internal path — are untouched, as are
`points_redemption_wallet` (the burn sink) and `cashback_provider_wallet`
(which funds internal payouts despite its name).

Revision ID: 0070
Revises: 0069
Create Date: 2026-08-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0070"
down_revision: str | Sequence[str] | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The account-type allowlist without `provider_redemption_wallet`; matches
# `ACCOUNT_TYPES` in app/shared/models/accounts.py after this migration.
_NEW_TYPES = (
    "'financial_wallet', 'points_account', 'system_points_issuance', "
    "'system_cash_inflow', 'system_fee_collected', 'operator_adjustment', "
    "'airtime_merchant_holding', 'commission', 'commission_wallet', "
    "'tax_service_collected', 'tax_commission_collected', "
    "'points_redemption_wallet', 'cashback_provider_wallet'"
)
_OLD_TYPES = _NEW_TYPES.replace(
    "'system_points_issuance', ",
    "'system_points_issuance', 'provider_redemption_wallet', ",
)


def upgrade() -> None:
    """Drop the two provider tables, their wallets, and the account type.

    Ordered by dependency: `redemptions` FKs `redemption_providers`, which in
    turn FKs the `accounts` rows deleted afterwards, so the tables must go
    first or the DELETE would be refused. The CHECK is narrowed last, once no
    row can still hold the retired type.

    Side effects:
        Drops `redemptions` and `redemption_providers` (and their indexes),
        deletes every `provider_redemption_wallet` account, and replaces
        `ck_accounts_type` with the narrowed allowlist.
    """
    op.drop_index("ix_redemptions_user_id", table_name="redemptions")
    op.drop_index("ix_redemptions_tenant_id", table_name="redemptions")
    op.drop_table("redemptions")

    op.drop_index("ix_redemption_providers_tenant_id", table_name="redemption_providers")
    op.drop_table("redemption_providers")

    # Only ever system-owned (user_id IS NULL) and only ever credited by the
    # provider flow just dropped, so there is nothing left to point at them.
    op.execute(sa.text("DELETE FROM accounts WHERE account_type = 'provider_redemption_wallet'"))

    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint("ck_accounts_type", "accounts", f"account_type IN ({_NEW_TYPES})")


def downgrade() -> None:
    """Recreate both tables and re-widen the account-type CHECK.

    Schema only. There is deliberately NO data guard and no attempt to restore
    rows: the platform was never live on this path, so `upgrade()` had no
    production data to destroy and this downgrade has none to bring back. The
    `provider_redemption_wallet` accounts are likewise not recreated — they
    were created on demand by provider registration, so re-registering a
    provider is what would bring one back.

    Side effects:
        Recreates `redemption_providers` and `redemptions` (empty, with their
        indexes) and restores the wider `ck_accounts_type`.
    """
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint("ck_accounts_type", "accounts", f"account_type IN ({_OLD_TYPES})")

    op.create_table(
        "redemption_providers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "redemption_wallet_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("status_check_url", sa.String(length=500), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("retry_interval_secs", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("escalate_after_mins", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        # Fernet-encrypted HMAC key for provider callbacks — the column shape
        # migrations 0008 and 0039 left behind, not the original plaintext one.
        sa.Column("shared_secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_redemption_providers_status",
        ),
    )
    op.create_index(
        "ix_redemption_providers_tenant_id",
        "redemption_providers",
        ["tenant_id"],
    )

    op.create_table(
        "redemptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("redemption_providers.id"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column("points_amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ("
            "'PENDING', 'PROCESSING', 'COMPLETED', "
            "'FAILED', 'REVERSED', 'MANUAL_REVIEW'"
            ")",
            name="ck_redemptions_status",
        ),
    )
    op.create_index("ix_redemptions_tenant_id", "redemptions", ["tenant_id"])
    op.create_index("ix_redemptions_user_id", "redemptions", ["user_id"])
