"""Limit config models — Phase G.2 (PRD Module 5) + enhancement (WAL-233).

Two scopes, both consulted before any ledger write in the payment
orchestration sequence (Pay-PRD-0260 step 2):

- `LimitConfig` — per (tenant, transaction_type, account_type, currency):
  per-txn min/max plus rolling count + value caps (daily/weekly/monthly).
- `WalletLimitConfig` — per (tenant, currency), financial wallets only:
  a max-balance ceiling plus cumulative send + receive count/value caps
  (daily/weekly/monthly) spanning every service for a user's wallet.

When no row exists for a tuple, the relevant check is a no-op (graceful
pass-through). Operators MUST opt-in by inserting configs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class LimitConfig(Base):
    """A per-(tenant, txn-type, account-type, currency) limit config."""

    __tablename__ = "limit_configs"
    __table_args__ = (
        # NULLS NOT DISTINCT: two NULL-type rows for the same other dims collide
        # (PG 15+). A specific-type row and the NULL default coexist.
        UniqueConstraint(
            "tenant_id",
            "transaction_type",
            "account_type",
            "currency",
            "user_type",
            name="uq_limit_configs_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # Type-aware scope (Epic 15): NULL = default for all user types; an
    # exact-type row wins over the NULL default at enforcement.
    user_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Every cap is nullable — operators configure any combination. NULL means
    # "no limit on this axis". Rolling windows: daily=24h, weekly=7d,
    # monthly=30d (count = number of txns, value = summed amount).
    min_amount: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    max_amount: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    daily_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    weekly_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    monthly_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class WalletLimitConfig(Base):
    """A per-(tenant, currency) financial-wallet limit config (WAL-233).

    Unlike `LimitConfig` (which is per transaction_type), these caps span
    every service for one user's financial wallet:

    - `max_balance` — the wallet may never exceed this balance.
    - `send_*` — cumulative outbound (DEBIT) caps, rolling daily/weekly/monthly.
    - `receive_*` — cumulative inbound (CREDIT) caps, rolling daily/weekly/monthly.

    Per the locked design: rolling windows, cumulative counts/values measure
    the principal amount only (fees excluded), per-tenant, financial wallets
    only. Every cap is nullable (NULL = no limit on that axis).
    """

    __tablename__ = "wallet_limit_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "currency",
            "user_type",
            name="uq_wallet_limit_configs_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # Type-aware scope (Epic 15): NULL = default for all user types.
    user_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    max_balance: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    send_daily_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    send_daily_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    send_weekly_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    send_weekly_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    send_monthly_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    send_monthly_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    receive_daily_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receive_daily_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    receive_weekly_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receive_weekly_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    receive_monthly_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receive_monthly_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
