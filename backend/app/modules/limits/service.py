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

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_admin
from app.modules.limits.schemas import (
    LimitConfigCreateRequest,
    WalletLimitConfigCreateRequest,
)
from app.shared.exceptions import (
    AmountAboveMax,
    AmountBelowMin,
    AppHTTPException,
    DailyCountExceeded,
    DailyValueExceeded,
    LimitConfigNotFound,
    MaxBalanceExceeded,
    MonthlyCountExceeded,
    MonthlyValueExceeded,
    RecipientLimitReached,
    RecipientMaxBalanceExceeded,
    TenantNotFound,
    WalletLimitConfigNotFound,
    WalletReceiveLimitExceeded,
    WalletSendLimitExceeded,
    WeeklyCountExceeded,
    WeeklyValueExceeded,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    LedgerEntry,
    LimitConfig,
    Tenant,
    Transaction,
    TXN_STATUS_COMPLETED,
    WalletLimitConfig,
)
from app.shared.utils.user_types import resolve_user_type


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
    user_type: str,
) -> LimitConfig | None:
    """Resolve the limit config for a slot, type-aware (Epic 15).

    Matches the exact-dimensions row for the caller's `user_type` OR the
    `user_type IS NULL` default, and prefers the typed row (ORDER BY user_type
    NULLS LAST). Returns None when neither exists (graceful pass-through).
    """
    result = await session.execute(
        select(LimitConfig)
        .where(
            LimitConfig.tenant_id == tenant_id,
            LimitConfig.transaction_type == transaction_type,
            LimitConfig.account_type == account_type,
            LimitConfig.currency == currency.upper(),
            or_(LimitConfig.user_type == user_type, LimitConfig.user_type.is_(None)),
        )
        .order_by(LimitConfig.user_type.nulls_last())
        .limit(1)
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
    user_type = await resolve_user_type(session, tenant_id, user_id)
    config = await _find_limit_config(
        session,
        tenant_id=tenant_id,
        transaction_type=transaction_type,
        account_type=account_type,
        currency=currency,
        user_type=user_type,
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
# Wallet-level cumulative SEND / RECEIVE checks (WAL-235, WAL-236)
# -----------------------------------------------------------------------------


def _wallet_windows(direction: str) -> tuple[tuple[str, str, str, timedelta], ...]:
    """Build the rolling-window specs for a direction ('send' or 'receive').

    Each tuple is (window label, count-cap attr, value-cap attr, window length).
    The label feeds the Wallet{Send,Receive}LimitExceeded error code.
    """
    return (
        (
            "daily",
            f"{direction}_daily_count_cap",
            f"{direction}_daily_value_cap",
            timedelta(hours=24),
        ),
        (
            "weekly",
            f"{direction}_weekly_count_cap",
            f"{direction}_weekly_value_cap",
            timedelta(days=7),
        ),
        (
            "monthly",
            f"{direction}_monthly_count_cap",
            f"{direction}_monthly_value_cap",
            timedelta(days=30),
        ),
    )


async def _find_wallet_limit_config(
    session: AsyncSession, *, tenant_id: UUID, currency: str, user_type: str
) -> WalletLimitConfig | None:
    """Resolve the (tenant, currency) wallet limit config, type-aware (Epic 15).

    Exact-type row beats the `user_type IS NULL` default; None when neither
    exists (pass-through).
    """
    result = await session.execute(
        select(WalletLimitConfig)
        .where(
            WalletLimitConfig.tenant_id == tenant_id,
            WalletLimitConfig.currency == currency.upper(),
            or_(
                WalletLimitConfig.user_type == user_type,
                WalletLimitConfig.user_type.is_(None),
            ),
        )
        .order_by(WalletLimitConfig.user_type.nulls_last())
        .limit(1)
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


async def _aggregate_wallet_movement(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    wallet_id: UUID,
    entry_type: str,
    window_floor: datetime,
) -> tuple[int, Decimal]:
    """Return (count, summed principal) of movements on `wallet_id` since the floor.

    A movement is a COMPLETED transaction with a leg of `entry_type` (DEBIT for
    sends, CREDIT for receives) on the wallet. We sum `transactions.amount` (the
    principal) — NOT the ledger leg amounts — so a send's service-charge leg is
    excluded. An EXISTS subquery counts each transaction once even when the
    wallet has two legs for it (principal + fee).
    """
    has_leg = (
        select(LedgerEntry.id)
        .where(
            LedgerEntry.transaction_id == Transaction.id,
            LedgerEntry.account_id == wallet_id,
            LedgerEntry.entry_type == entry_type,
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
            has_leg,
        )
    )
    row = agg.one()
    return int(row[0] or 0), Decimal(str(row[1] or 0))


async def _first_wallet_window_breach(
    session: AsyncSession,
    *,
    config: WalletLimitConfig,
    direction: str,
    entry_type: str,
    tenant_id: UUID,
    wallet_id: UUID | None,
    amount: Decimal,
    current: datetime,
) -> tuple[str, str, str] | None:
    """Return (window, axis, cap) of the first breached cap, or None.

    Shared by the send + receive checks. `direction` selects the config columns
    ('send'/'receive') and `entry_type` the ledger leg (DEBIT/CREDIT). A window
    is only queried when it has a cap set. When the user has no wallet yet there
    is no prior activity, but the current `amount` is still checked.
    """
    for label, count_attr, value_attr, window_len in _wallet_windows(direction):
        count_cap = getattr(config, count_attr)
        value_cap = getattr(config, value_attr)
        if count_cap is None and value_cap is None:
            continue

        if wallet_id is None:
            existing_count, existing_total = 0, Decimal("0")
        else:
            existing_count, existing_total = await _aggregate_wallet_movement(
                session,
                tenant_id=tenant_id,
                wallet_id=wallet_id,
                entry_type=entry_type,
                window_floor=current - window_len,
            )
        if count_cap is not None and existing_count + 1 > int(count_cap):
            return (label, "count", str(int(count_cap)))
        if value_cap is not None and existing_total + amount > Decimal(str(value_cap)):
            return (label, "value", str(value_cap))
    return None


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
    user_type = await resolve_user_type(session, tenant_id, user_id)
    config = await _find_wallet_limit_config(
        session, tenant_id=tenant_id, currency=currency, user_type=user_type
    )
    if config is None:
        return  # No config = no wallet limit (intentional pass-through).

    wallet_id = await _user_financial_wallet_id(
        session, tenant_id=tenant_id, user_id=user_id, currency=currency
    )
    breach = await _first_wallet_window_breach(
        session,
        config=config,
        direction="send",
        entry_type=ENTRY_DEBIT,
        tenant_id=tenant_id,
        wallet_id=wallet_id,
        amount=amount,
        current=now or datetime.now(UTC),
    )
    if breach is not None:
        label, axis, cap = breach
        raise WalletSendLimitExceeded(label, axis, cap)


async def check_wallet_receive_limits(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    currency: str,
    amount: Decimal,
    recipient_facing: bool = False,
    now: datetime | None = None,
) -> None:
    """Raise if crediting `amount` would breach a receive cap or max balance (WAL-236).

    Enforced BEFORE a credit lands on a user's financial wallet. Two guards:
      1. max_balance — reject if `derive_balance(wallet) + amount` exceeds the cap.
      2. cumulative receive caps — COMPLETED financial-wallet CREDIT activity
         (principal only) over rolling daily/weekly/monthly windows.
    No-op when no wallet limit config exists or the relevant caps are NULL.

    `recipient_facing` controls error surface: for a P2P credit to someone
    else's wallet (True) a breach fails the SENDER with a detail-free
    `recipient_*` error and the recipient is never notified; for a credit to the
    actor's own wallet (e.g. top-up, False) the owner gets the specific cap.

    Args:
        tenant_id: Tenant scope.
        user_id: The wallet owner being credited.
        currency: The financial wallet currency.
        amount: The principal about to be credited.
        recipient_facing: True when the actor is not the wallet owner (P2P).
        now: Override for tests.

    Raises:
        MaxBalanceExceeded / WalletReceiveLimitExceeded: owner-facing (409/429).
        RecipientMaxBalanceExceeded / RecipientLimitReached: sender-facing (409).
    """
    user_type = await resolve_user_type(session, tenant_id, user_id)
    config = await _find_wallet_limit_config(
        session, tenant_id=tenant_id, currency=currency, user_type=user_type
    )
    if config is None:
        return  # No config = no wallet limit (intentional pass-through).

    wallet_id = await _user_financial_wallet_id(
        session, tenant_id=tenant_id, user_id=user_id, currency=currency
    )

    # 1. Max-balance ceiling. balance is 0 when the wallet doesn't exist yet
    # (the credit would create it), so a first credit over the cap is rejected.
    if config.max_balance is not None:
        balance = Decimal("0")
        if wallet_id is not None:
            balance, _reserved = await derive_balance(session, wallet_id)
        if balance + amount > Decimal(str(config.max_balance)):
            if recipient_facing:
                raise RecipientMaxBalanceExceeded()
            raise MaxBalanceExceeded(str(config.max_balance))

    # 2. Cumulative receive caps.
    breach = await _first_wallet_window_breach(
        session,
        config=config,
        direction="receive",
        entry_type=ENTRY_CREDIT,
        tenant_id=tenant_id,
        wallet_id=wallet_id,
        amount=amount,
        current=now or datetime.now(UTC),
    )
    if breach is not None:
        if recipient_facing:
            raise RecipientLimitReached()
        label, axis, cap = breach
        raise WalletReceiveLimitExceeded(label, axis, cap)


# -----------------------------------------------------------------------------
# Admin CRUD
# -----------------------------------------------------------------------------


def _caps_snapshot(config: object, fields: tuple[str, ...]) -> dict[str, object]:
    """Serialise cap fields for an audit snapshot — Decimals to str, ints as-is."""
    snapshot: dict[str, object] = {}
    for field in fields:
        value = getattr(config, field)
        snapshot[field] = value if (value is None or isinstance(value, int)) else str(value)
    return snapshot


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
        user_type=request.user_type,
        min_amount=request.min_amount,
        max_amount=request.max_amount,
        daily_count_cap=request.daily_count_cap,
        daily_value_cap=request.daily_value_cap,
        weekly_count_cap=request.weekly_count_cap,
        weekly_value_cap=request.weekly_value_cap,
        monthly_count_cap=request.monthly_count_cap,
        monthly_value_cap=request.monthly_value_cap,
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
                **_caps_snapshot(
                    config,
                    (
                        "min_amount",
                        "max_amount",
                        "daily_count_cap",
                        "daily_value_cap",
                        "weekly_count_cap",
                        "weekly_value_cap",
                        "monthly_count_cap",
                        "monthly_value_cap",
                    ),
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


# -----------------------------------------------------------------------------
# Admin CRUD — wallet limit configs (WAL-237)
# -----------------------------------------------------------------------------

# ORM column names carried straight from the request to the row + audit snapshot.
_WALLET_CONFIG_FIELDS = (
    "max_balance",
    "send_daily_count_cap",
    "send_daily_value_cap",
    "send_weekly_count_cap",
    "send_weekly_value_cap",
    "send_monthly_count_cap",
    "send_monthly_value_cap",
    "receive_daily_count_cap",
    "receive_daily_value_cap",
    "receive_weekly_count_cap",
    "receive_weekly_value_cap",
    "receive_monthly_count_cap",
    "receive_monthly_value_cap",
)


async def create_wallet_limit_config(
    session: AsyncSession,
    request: WalletLimitConfigCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> WalletLimitConfig:
    """Create a per-(tenant, currency) wallet limit config.

    Raises 409 on unique-index collision (one config per (tenant, currency)).
    """
    await _assert_tenant_exists(session, request.tenant_id)
    config = WalletLimitConfig(
        tenant_id=request.tenant_id,
        currency=request.currency.upper(),
        user_type=request.user_type,
        **{field: getattr(request, field) for field in _WALLET_CONFIG_FIELDS},
    )
    session.add(config)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "wallet_limit_config_already_exists",
            "A wallet limit config already exists for this currency.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="wallet_limit_config.created",
            entity_type="wallet_limit_config",
            entity_id=str(config.id),
            after_state={
                "currency": config.currency,
                **_caps_snapshot(config, _WALLET_CONFIG_FIELDS),
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(config)
    return config


async def list_wallet_limit_configs(
    session: AsyncSession, tenant_id: UUID
) -> list[WalletLimitConfig]:
    """Return every wallet limit config in a tenant, newest-first."""
    result = await session.execute(
        select(WalletLimitConfig)
        .where(WalletLimitConfig.tenant_id == tenant_id)
        .order_by(WalletLimitConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_wallet_limit_config(
    session: AsyncSession,
    config_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a wallet limit config. Tenant-isolated; 404 when not found."""
    result = await session.execute(
        select(WalletLimitConfig).where(
            WalletLimitConfig.id == config_id,
            WalletLimitConfig.tenant_id == tenant_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise WalletLimitConfigNotFound()
    before = {"currency": config.currency}
    await session.delete(config)
    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="wallet_limit_config.deleted",
            entity_type="wallet_limit_config",
            entity_id=str(config_id),
            before_state=before,
            ip_address=ip_address,
        )
    await session.commit()
