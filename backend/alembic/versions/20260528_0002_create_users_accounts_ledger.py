"""create users, accounts, ledger tables (PRD §6.2, §6.5, §6.6)

Adds Phase A foundation tables:
  - users, user_identifiers, user_profiles, otp_requests, auth_attempts
  - accounts (with extended account_type incl. system_points_issuance), account_balance_snapshots
  - transactions, ledger_entries

OtpRequest and AuthAttempt are scaffolded — full auth flow lands in Phase 2.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- users -------------------------------------------------------------
    op.create_table(
        "users",
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
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("pin_hash", sa.String(length=255), nullable=True),
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
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'closed')",
            name="ck_users_status",
        ),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    # -- user_identifiers --------------------------------------------------
    op.create_table(
        "user_identifiers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("identifier_type", sa.String(length=30), nullable=False),
        sa.Column("identifier_value", sa.String(length=255), nullable=False),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "identifier_type",
            "identifier_value",
            name="uq_user_identifiers_value_per_tenant",
        ),
        sa.CheckConstraint(
            "identifier_type IN ('phone', 'email', 'account_number', 'card_number')",
            name="ck_user_identifiers_type",
        ),
    )
    op.create_index("ix_user_identifiers_user_id", "user_identifiers", ["user_id"])
    op.create_index(
        "ix_user_identifiers_lookup",
        "user_identifiers",
        ["tenant_id", "identifier_type", "identifier_value"],
    )

    # -- user_profiles -----------------------------------------------------
    op.create_table(
        "user_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column(
            "kyc_status",
            sa.String(length=20),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kyc_status IN ('unverified', 'pending', 'verified', 'rejected')",
            name="ck_user_profiles_kyc_status",
        ),
    )

    # -- otp_requests (scaffold for Phase 2) -------------------------------
    op.create_table(
        "otp_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("otp_hash", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "purpose IN ('registration', 'pin_reset', 'login')",
            name="ck_otp_requests_purpose",
        ),
    )

    # -- auth_attempts (scaffold for Phase 2) ------------------------------
    op.create_table(
        "auth_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("attempt_type", sa.String(length=20), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "attempt_type IN ('pin', 'otp')",
            name="ck_auth_attempts_type",
        ),
    )
    op.create_index("ix_auth_attempts_user_id", "auth_attempts", ["user_id"])

    # -- accounts ----------------------------------------------------------
    op.create_table(
        "accounts",
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
            nullable=True,
        ),
        # FK to merchants.id added when merchants table exists in a later migration.
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
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
            "account_type IN ("
            "'financial_wallet', "
            "'points_account', "
            "'system_points_issuance', "
            "'provider_redemption_wallet'"
            ")",
            name="ck_accounts_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'closed')",
            name="ck_accounts_status",
        ),
    )
    op.create_index("ix_accounts_user_tenant", "accounts", ["user_id", "tenant_id"])
    op.create_index("ix_accounts_tenant_type", "accounts", ["tenant_id", "account_type"])

    # -- account_balance_snapshots ----------------------------------------
    op.create_table(
        "account_balance_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "balance",
            sa.Numeric(precision=20, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "reserved_balance",
            sa.Numeric(precision=20, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "snapshot_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_ledger_entry_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # -- transactions ------------------------------------------------------
    op.create_table(
        "transactions",
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
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "initiated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column(
            "fee_amount",
            sa.Numeric(precision=20, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("external_status", sa.String(length=50), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
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
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_transactions_idempotency_per_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED', 'REVERSED')",
            name="ck_transactions_status",
        ),
    )
    op.create_index("ix_transactions_status", "transactions", ["status", "tenant_id"])
    op.create_index(
        "ix_transactions_user_created",
        "transactions",
        ["initiated_by", "tenant_id", "created_at"],
    )

    # -- ledger_entries ----------------------------------------------------
    op.create_table(
        "ledger_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # No updated_at — entries are immutable (PRD Pay-PRD-0170).
        sa.CheckConstraint(
            "entry_type IN ('DEBIT', 'CREDIT')",
            name="ck_ledger_entries_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'REVERSED')",
            name="ck_ledger_entries_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
    )
    op.create_index(
        "ix_ledger_entries_account",
        "ledger_entries",
        ["account_id", "status", "created_at"],
    )
    op.create_index("ix_ledger_entries_transaction", "ledger_entries", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_transaction", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_account", table_name="ledger_entries")
    op.drop_table("ledger_entries")

    op.drop_index("ix_transactions_user_created", table_name="transactions")
    op.drop_index("ix_transactions_status", table_name="transactions")
    op.drop_table("transactions")

    op.drop_table("account_balance_snapshots")

    op.drop_index("ix_accounts_tenant_type", table_name="accounts")
    op.drop_index("ix_accounts_user_tenant", table_name="accounts")
    op.drop_table("accounts")

    op.drop_index("ix_auth_attempts_user_id", table_name="auth_attempts")
    op.drop_table("auth_attempts")

    op.drop_table("otp_requests")
    op.drop_table("user_profiles")

    op.drop_index("ix_user_identifiers_lookup", table_name="user_identifiers")
    op.drop_index("ix_user_identifiers_user_id", table_name="user_identifiers")
    op.drop_table("user_identifiers")

    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
