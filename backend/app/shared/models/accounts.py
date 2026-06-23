"""Account and AccountBalanceSnapshot models — PRD §6.5 + addendum.

PRD references:
  - Pay-PRD-0110 to 0160 (Account & Wallet Management module)

The account_type enum is extended from PRD §6.5 with `system_points_issuance` —
see docs/06-data-architecture.md §4 for the rationale (double-entry balance
requires a source account when issuing rewards).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Account type constants — keep in sync with the CHECK constraint below.
ACCOUNT_TYPE_FINANCIAL_WALLET = "financial_wallet"
ACCOUNT_TYPE_POINTS = "points_account"
ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE = "system_points_issuance"
ACCOUNT_TYPE_PROVIDER_REDEMPTION = "provider_redemption_wallet"
# system_cash_inflow is the debit-side master for any money entering the system
# from outside (top-ups, mobile money receipts). One per (tenant, currency).
# See docs/06-data-architecture.md §4 addendum (Phase B).
ACCOUNT_TYPE_SYSTEM_CASH_INFLOW = "system_cash_inflow"
# Phase G — Pricing engine credit side. One per (tenant, currency).
# Every fee leg writes a CREDIT here, balancing the user-wallet DEBIT.
ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED = "system_fee_collected"
# Phase H — Treasury counter-leg. Balance tracks net external cash that has
# flowed in (or out) of the platform via bank wires. Admin "fund float" and
# "withdraw float" actions write the opposite leg here so the ledger stays
# double-entry balanced. One per (tenant, currency).
ACCOUNT_TYPE_OPERATOR_ADJUSTMENT = "operator_adjustment"
# Phase H — Airtime recharge escrow. When a user buys airtime, their wallet
# is DEBITed and this account is CREDITed (PENDING) while the third-party
# provider provisioning call is in flight. Stays CREDITed after COMPLETED
# until ops settles externally with the MNO. One per (tenant, currency).
ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING = "airtime_merchant_holding"

ACCOUNT_TYPES = (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ACCOUNT_TYPE_PROVIDER_REDEMPTION,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
)


class Account(Base):
    """A financial or points-holding record.

    Either `user_id` OR `merchant_id` is set for user/merchant-owned accounts;
    both are NULL for system-owned accounts (system_points_issuance,
    provider_redemption_wallet).

    Balance is NOT stored here — it is derived from `ledger_entries`. The
    `account_balance_snapshots` table caches it for read performance.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ("
            "'financial_wallet', "
            "'points_account', "
            "'system_points_issuance', "
            "'provider_redemption_wallet', "
            "'system_cash_inflow', "
            "'system_fee_collected', "
            "'operator_adjustment', "
            "'airtime_merchant_holding'"
            ")",
            name="ck_accounts_type",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'closed')",
            name="ck_accounts_status",
        ),
        Index("ix_accounts_user_tenant", "user_id", "tenant_id"),
        Index(
            "ix_accounts_tenant_type",
            "tenant_id",
            "account_type",
        ),
        # Partial unique indexes — Postgres treats NULL as distinct on
        # a plain UniqueConstraint, so we split the rule:
        #   - User accounts: one per (tenant, user, type, currency)
        #   - System accounts: one per (tenant, type, currency) when user is NULL
        # Migration 0009 adds these on the live DB; seeds rely on the
        # uniqueness to stay idempotent.
        Index(
            "uq_accounts_user_scoped",
            "tenant_id",
            "user_id",
            "account_type",
            "currency",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_accounts_system_scoped",
            "tenant_id",
            "account_type",
            "currency",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    # NULL for system / merchant accounts.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # NULL for user / system accounts.
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # FK to merchants.id added in a later migration when merchants table exists.
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class AccountBalanceSnapshot(Base):
    """Cached balance for fast reads.

    NOT the source of truth — `ledger_entries` is. This snapshot is updated
    asynchronously after every ledger write. If the snapshot is stale, the
    ledger query is the fallback.
    """

    __tablename__ = "account_balance_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id"),
        nullable=False,
        unique=True,
    )
    # NUMERIC(20, 6) holds both money and points without precision loss.
    balance: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, server_default="0"
    )
    reserved_balance: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, server_default="0"
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    last_ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
