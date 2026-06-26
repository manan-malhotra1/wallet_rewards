"""Limits service — Phase G.2 (WAL-51) + weekly/monthly windows (WAL-234).

Two surfaces:
  - `check_limits()` — called inline by the payment orchestration BEFORE
    the ledger write. Rejects min/max breaches AND aggregate rolling count/
    value caps over daily/weekly/monthly windows. No-op when no matching
    limit config exists (graceful pass-through).
  - Admin CRUD for limit configs.

Aggregate caps are computed live from `transactions` (the source of truth)
— no separate counter table. The windows are "rolling 24h / 7d / 30d from
the DB's NOW()", not calendar boundaries, to defeat the midnight/month-edge
trickle attack listed in the threat model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.limits.schemas import LimitConfigCreateRequest
from app.shared.exceptions import (
    AmountAboveMax,
    AmountBelowMin,
    AppHTTPException,
    DailyCountExceeded,
    DailyValueExceeded,
    LimitConfigNotFound,
    MonthlyCountExceeded,
    MonthlyValueExceeded,
    TenantNotFound,
    WalletSendLimitExceeded,
    WeeklyCountExceeded,
    WeeklyValueExceeded,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_DEBIT,
    Account,
    LedgerEntry,
    LimitConfig,
    Tenant,
    Transaction,
    TXN_STATUS_COMPLETED,
    WalletLimitConfig,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _find_limit_config(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    transaction_type: str,
    account_type: str,
    currency: str,
) -> LimitConfig | None:
    """Lookup helper — returns None when no config matches (pass-through)."""
    result = await session.execute(
        select(LimitConfig).where(
            LimitConfig.tenant_id == tenant_id,
            LimitConfig.transaction_type == transaction_type,
            LimitConfig.account_type == account_type,
            LimitConfig.currency == currency.upper(),
        )
    )
    return result.scalar_one_or_none()


# Rolling windows checked by `check_limits`, widest last. Each tuple is
# (config count-cap attr, config value-cap attr, window length, count
# exception, value exception). All windows are rolling from DB-time NOW(),
# not calendar boundaries — defeats the midnight/month-edge trickle attack.
_WINDOW_SPECS = (
    (
        "daily_count_cap",
        "daily_value_cap",
        timedelta(hours=24),
        DailyCountExceeded,
        DailyValueExceeded,
    ),
    (
        "weekly_count_cap",
        "weekly_value_cap",
        timedelta(days=7),
        WeeklyCountExceeded,
        WeeklyValueExceeded,
    ),
    (
        "monthly_count_cap",
        "monthly_value_cap",
        timedelta(days=30),
        MonthlyCountExceeded,
        MonthlyValueExceeded,
    ),
)


async def _aggregate_user_txns(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    transaction_type: str,
    window_floor: datetime,
) -> tuple[int, Decimal]:
    """Return (count, summed amount) of this user's matching COMPLETED txns.

    Counts only transactions this user originated (`initiated_by`) of the
    given `transaction_type`, in this tenant, with status COMPLETED, created
    at or after `window_floor`. The single source of truth for every rolling
    window (daily/weekly/monthly) — the caller just varies the floor.
    """
    agg = await session.execute(
        select(
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
        ).where(
            Transaction.tenant_id == tenant_id,
            Transaction.initiated_by == user_id,
            Transaction.transaction_type == transaction_type,
            Transaction.status == TXN_STATUS_COMPLETED,
            Transaction.created_at >= window_floor,
        )
    )
    row = agg.one()
    return int(row[0] or 0), Decimal(str(row[1] or 0))


# -----------------------------------------------------------------------------
# Pre-write check
# -----------------------------------------------------------------------------


async def check_limits(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    transaction_type: str,
    account_type: str,
    currency: str,
    amount: Decimal,
    now: datetime | None = None,
) -> None:
    """Raise if `amount` would breach the limit config for this slot.

    Looked-up tuple: (tenant_id, transaction_type, account_type, currency).
    When no row exists the check is a no-op — operators opt-in.

    Rolling aggregates (daily=24h, weekly=7d, monthly=30d) count only this
    user's COMPLETED transactions of the same `transaction_type` originating
    from them (transactions.initiated_by == user_id). A window is only
    queried when it has at least one cap set, so operators who configure just
    min/max — or only some windows — pay no extra query cost.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: The user initiating — also the subject of the rolling caps.
        transaction_type: 'p2p', 'top_up', 'redemption', etc.
        account_type: 'financial_wallet' or 'points_account'.
        currency: ISO 4217 (or 'PTS').
        amount: Amount about to be moved.
        now: Override for tests.

    Raises:
        AmountBelowMin / AmountAboveMax: 422.
        Daily/Weekly/Monthly Count/Value Exceeded: 429.
    """
    config = await _find_limit_config(
        session,
        tenant_id=tenant_id,
        transaction_type=transaction_type,
        account_type=account_type,
        currency=currency,
    )
    if config is None:
        return  # No config = no limit (intentional pass-through).

    # Per-transaction min/max.
    if config.min_amount is not None and amount < Decimal(str(config.min_amount)):
        raise AmountBelowMin(str(config.min_amount))
    if config.max_amount is not None and amount > Decimal(str(config.max_amount)):
        raise AmountAboveMax(str(config.max_amount))

    # Rolling count/value caps per window (daily/weekly/monthly).
    current = now or datetime.now(UTC)
    for count_attr, value_attr, window_len, count_exc, value_exc in _WINDOW_SPECS:
        count_cap = getattr(config, count_attr)
        value_cap = getattr(config, value_attr)
        if count_cap is None and value_cap is None:
            continue  # Window not configured — skip the query.

        existing_count, existing_total = await _aggregate_user_txns(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            transaction_type=transaction_type,
            window_floor=current - window_len,
        )
        if count_cap is not None and existing_count + 1 > int(count_cap):
            raise count_exc(int(count_cap))
        if value_cap is not None and existing_total + amount > Decimal(str(value_cap)):
            raise value_exc(str(value_cap))


# -----------------------------------------------------------------------------
# Wallet-level cumulative SEND check (WAL-235)
# -----------------------------------------------------------------------------

# Rolling send windows: (label, count-cap attr, value-cap attr, window length).
# Labels feed the WalletSendLimitExceeded error code.
_WALLET_SEND_WINDOWS = (
    ("daily", "send_daily_count_cap", "send_daily_value_cap", timedelta(hours=24)),
    ("weekly", "send_weekly_count_cap", "send_weekly_value_cap", timedelta(days=7)),
    ("monthly", "send_monthly_count_cap", "send_monthly_value_cap", timedelta(days=30)),
)


async def _find_wallet_limit_config(
    session: AsyncSession, *, tenant_id: UUID, currency: str
) -> WalletLimitConfig | None:
    """Return the (tenant, currency) wallet limit config, or None (pass-through)."""
    result = await session.execute(
        select(WalletLimitConfig).where(
            WalletLimitConfig.tenant_id == tenant_id,
            WalletLimitConfig.currency == currency.upper(),
        )
    )
    return result.scalar_one_or_none()


async def _user_financial_wallet_id(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, currency: str
) -> UUID | None:
    """Return the user's financial_wallet account id for this currency, or None."""
    result = await session.execute(
        select(Account.id).where(
            Account.tenant_id == tenant_id,
            Account.user_id == user_id,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.currency == currency.upper(),
        )
    )
    return result.scalar_one_or_none()


async def _aggregate_wallet_sends(
    session: AsyncSession, *, tenant_id: UUID, wallet_id: UUID, window_floor: datetime
) -> tuple[int, Decimal]:
    """Return (count, summed principal) of sends from `wallet_id` since the floor.

    A "send" is a COMPLETED transaction with a DEBIT leg on the wallet. We sum
    `transactions.amount` (the principal) — NOT the ledger debit amounts — so
    the service charge leg is excluded. An EXISTS subquery counts each
    transaction once even though a send debits the wallet twice (principal +
    fee).
    """
    has_debit_leg = (
        select(LedgerEntry.id)
        .where(
            LedgerEntry.transaction_id == Transaction.id,
            LedgerEntry.account_id == wallet_id,
            LedgerEntry.entry_type == ENTRY_DEBIT,
        )
        .exists()
    )
    agg = await session.execute(
        select(
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
        ).where(
            Transaction.tenant_id == tenant_id,
            Transaction.status == TXN_STATUS_COMPLETED,
            Transaction.created_at >= window_floor,
            has_debit_leg,
        )
    )
    row = agg.one()
    return int(row[0] or 0), Decimal(str(row[1] or 0))


async def check_wallet_send_limits(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    currency: str,
    amount: Decimal,
    now: datetime | None = None,
) -> None:
    """Raise if `amount` would breach a cumulative wallet SEND cap (WAL-235).

    Per-(tenant, currency) caps spanning every service for the user's financial
    wallet — independent of the per-transaction-type `check_limits`. Cumulative
    send = COMPLETED financial-wallet DEBIT activity in the rolling window,
    measured by transaction principal (fees excluded). No-op when no wallet
    limit config exists or the relevant window caps are NULL. Financial wallets
    only (points/redemption never reach here).

    Args:
        tenant_id: Tenant scope.
        user_id: The sender — subject of the cumulative caps.
        currency: The financial wallet currency (e.g. 'ZAR').
        amount: The principal about to be sent.
        now: Override for tests.

    Raises:
        WalletSendLimitExceeded: 429 — a daily/weekly/monthly count or value
            cap would be breached.
    """
    config = await _find_wallet_limit_config(session, tenant_id=tenant_id, currency=currency)
    if config is None:
        return  # No config = no wallet limit (intentional pass-through).

    wallet_id = await _user_financial_wallet_id(
        session, tenant_id=tenant_id, user_id=user_id, currency=currency
    )
    current = now or datetime.now(UTC)
    for label, count_attr, value_attr, window_len in _WALLET_SEND_WINDOWS:
        count_cap = getattr(config, count_attr)
        value_cap = getattr(config, value_attr)
        if count_cap is None and value_cap is None:
            continue

        # No wallet yet → no prior sends, but the current send is still checked.
        if wallet_id is None:
            existing_count, existing_total = 0, Decimal("0")
        else:
            existing_count, existing_total = await _aggregate_wallet_sends(
                session,
                tenant_id=tenant_id,
                wallet_id=wallet_id,
                window_floor=current - window_len,
            )
        if count_cap is not None and existing_count + 1 > int(count_cap):
            raise WalletSendLimitExceeded(label, "count", str(int(count_cap)))
        if value_cap is not None and existing_total + amount > Decimal(str(value_cap)):
            raise WalletSendLimitExceeded(label, "value", str(value_cap))


# -----------------------------------------------------------------------------
# Admin CRUD
# -----------------------------------------------------------------------------


async def create_limit_config(
    session: AsyncSession,
    request: LimitConfigCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> LimitConfig:
    """Create a new limit config row.

    Raises 409 on unique-index collision (one config per
    `(tenant, transaction_type, account_type, currency)`).
    """
    await _assert_tenant_exists(session, request.tenant_id)
    config = LimitConfig(
        tenant_id=request.tenant_id,
        transaction_type=request.transaction_type,
        account_type=request.account_type,
        currency=request.currency.upper(),
        min_amount=request.min_amount,
        max_amount=request.max_amount,
        daily_count_cap=request.daily_count_cap,
        daily_value_cap=request.daily_value_cap,
    )
    session.add(config)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "limit_config_already_exists",
            "A limit config already exists for this scope.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="limit_config.created",
            entity_type="limit_config",
            entity_id=str(config.id),
            after_state={
                "transaction_type": config.transaction_type,
                "account_type": config.account_type,
                "currency": config.currency,
                "min_amount": (str(config.min_amount) if config.min_amount is not None else None),
                "max_amount": (str(config.max_amount) if config.max_amount is not None else None),
                "daily_count_cap": config.daily_count_cap,
                "daily_value_cap": (
                    str(config.daily_value_cap) if config.daily_value_cap is not None else None
                ),
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(config)
    return config


async def list_limit_configs(session: AsyncSession, tenant_id: UUID) -> list[LimitConfig]:
    """Return every limit config in a tenant, newest-first."""
    result = await session.execute(
        select(LimitConfig)
        .where(LimitConfig.tenant_id == tenant_id)
        .order_by(LimitConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_limit_config(
    session: AsyncSession,
    config_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a limit config. Tenant-isolated."""
    result = await session.execute(
        select(LimitConfig).where(
            LimitConfig.id == config_id,
            LimitConfig.tenant_id == tenant_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise LimitConfigNotFound()
    before = {
        "transaction_type": config.transaction_type,
        "account_type": config.account_type,
        "currency": config.currency,
    }
    await session.delete(config)
    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="limit_config.deleted",
            entity_type="limit_config",
            entity_id=str(config_id),
            before_state=before,
            ip_address=ip_address,
        )
    await session.commit()
