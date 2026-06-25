"""Pricing engine service — Phase G.3 (WAL-52).

Three surfaces:
  - `calculate_fee()` — pure-Python fee math given a config + amount.
    Raises `PricingConfigMissing` when no config row exists for the
    tuple (Pay-PRD-0420: every txn runs pricing; zero-fee must be
    explicitly configured).
  - `get_or_create_system_fee_account()` — auto-creates the per-(tenant,
    currency) system_fee_collected account on first need.
  - Admin CRUD on `pricing_configs`.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.shared.exceptions import (
    AppHTTPException,
    PricingConfigMissing,
    PricingConfigNotFound,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    Account,
    PricingConfig,
    Tenant,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _find_pricing_config(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    transaction_type: str,
    account_type: str,
    currency: str,
) -> PricingConfig | None:
    """Lookup helper — returns None when no config exists."""
    result = await session.execute(
        select(PricingConfig).where(
            PricingConfig.tenant_id == tenant_id,
            PricingConfig.transaction_type == transaction_type,
            PricingConfig.account_type == account_type,
            PricingConfig.currency == currency.upper(),
        )
    )
    return result.scalar_one_or_none()


# -----------------------------------------------------------------------------
# Fee computation
# -----------------------------------------------------------------------------


async def calculate_fee(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    transaction_type: str,
    account_type: str,
    currency: str,
    amount: Decimal,
) -> Decimal:
    """Compute the fee for one transaction.

    Formula: `fixed_fee + min(variable_fee_pct * amount, fee_cap or +Inf)`.
    Rounded to 6 decimal places (HALF_UP) to match the ledger's
    NUMERIC(20, 6) storage.

    Per Pay-PRD-0420, EVERY transaction must run pricing — there is no
    silent zero-fee fallback. When no config exists for the tuple we
    raise `PricingConfigMissing`. Operators have to explicitly insert a
    zero-fee row if that's the intent.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        transaction_type: 'p2p', 'top_up', 'redemption', etc.
        account_type: 'financial_wallet' or 'points_account'.
        currency: ISO 4217 (or 'PTS').
        amount: Amount the user is moving (the base for the variable part).

    Returns:
        The total fee as a Decimal, rounded to 6 dp.

    Raises:
        PricingConfigMissing: 422 — no config for this tuple.
    """
    config = await _find_pricing_config(
        session,
        tenant_id=tenant_id,
        transaction_type=transaction_type,
        account_type=account_type,
        currency=currency,
    )
    if config is None:
        raise PricingConfigMissing(transaction_type)

    fixed = Decimal(str(config.fixed_fee))
    pct = Decimal(str(config.variable_fee_pct))
    cap = Decimal(str(config.fee_cap)) if config.fee_cap is not None else None

    variable = pct * amount
    if cap is not None and variable > cap:
        variable = cap

    fee = (fixed + variable).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return fee


def account_type_for_currency(currency: str) -> str:
    """Default the fee's account scope from the currency.

    Points instruments (PTS) settle on the points account; every other
    currency on the financial wallet. This covers all current services
    (p2p / cash-in / withdraw / airtime → financial_wallet; redemption →
    points_account). Callers needing a different scope pass `account_type`
    explicitly to `quote_fee`.
    """
    return (
        ACCOUNT_TYPE_POINTS
        if currency.upper() == "PTS"
        else ACCOUNT_TYPE_FINANCIAL_WALLET
    )


async def quote_fee(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    service: str,
    amount: Decimal,
    currency: str,
    account_type: str | None = None,
) -> Decimal:
    """Preview the service charge for ANY service + amount (read-only).

    Service-agnostic: `service` is the service code, which equals the
    `transaction_type` pricing/rules/transactions are keyed on — so one
    quote path serves every user service, present and future. Uses the same
    `calculate_fee()` the real transaction runs, guaranteeing the quoted fee
    equals the charged fee.

    Args:
        tenant_id: Caller's tenant (resolved from the session token).
        service: The service code (== transaction_type), e.g. 'p2p'.
        amount: The amount the operation would move.
        currency: 3-letter ISO 4217 (or 'PTS').
        account_type: Optional override; defaults via `account_type_for_currency`.

    Returns:
        The fee as a Decimal; `Decimal("0")` when no pricing config applies
        (legacy pass-through, mirroring the transaction paths).
    """
    resolved_account_type = account_type or account_type_for_currency(currency)
    try:
        return await calculate_fee(
            session,
            tenant_id=tenant_id,
            transaction_type=service,
            account_type=resolved_account_type,
            currency=currency,
            amount=amount,
        )
    except PricingConfigMissing:
        return Decimal("0")


# -----------------------------------------------------------------------------
# System fee account helper
# -----------------------------------------------------------------------------


async def get_or_create_system_fee_account(
    session: AsyncSession, *, tenant_id: UUID, currency: str
) -> Account:
    """Return the per-(tenant, currency) `system_fee_collected` account.

    Auto-creates the account on first use. Idempotent: re-callers see the
    existing row. Unique-index drift (Phase F.5.1 partial-unique on
    accounts) makes the create atomic.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        currency: ISO 4217 (or 'PTS'). Case-insensitive — we uppercase.
    """
    currency_canon = currency.upper()
    existing = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.account_type == ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
            Account.currency == currency_canon,
            Account.user_id.is_(None),
        )
    )
    account = existing.scalar_one_or_none()
    if account is not None:
        return account

    account = Account(
        tenant_id=tenant_id,
        user_id=None,
        account_type=ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
        currency=currency_canon,
    )
    session.add(account)
    try:
        await session.flush()
    except IntegrityError:
        # Lost the race to a concurrent caller — refetch and return theirs.
        await session.rollback()
        result = await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
                Account.currency == currency_canon,
                Account.user_id.is_(None),
            )
        )
        return result.scalar_one()
    return account


# -----------------------------------------------------------------------------
# Admin CRUD
# -----------------------------------------------------------------------------


async def create_pricing_config(
    session: AsyncSession,
    request: PricingConfigCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> PricingConfig:
    """Persist a new pricing config. 409 on unique-index collision."""
    await _assert_tenant_exists(session, request.tenant_id)
    config = PricingConfig(
        tenant_id=request.tenant_id,
        transaction_type=request.transaction_type,
        account_type=request.account_type,
        currency=request.currency.upper(),
        fixed_fee=request.fixed_fee,
        variable_fee_pct=request.variable_fee_pct,
        fee_cap=request.fee_cap,
    )
    session.add(config)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "pricing_config_already_exists",
            "A pricing config already exists for this scope.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="pricing_config.created",
            entity_type="pricing_config",
            entity_id=str(config.id),
            after_state={
                "transaction_type": config.transaction_type,
                "account_type": config.account_type,
                "currency": config.currency,
                "fixed_fee": str(config.fixed_fee),
                "variable_fee_pct": str(config.variable_fee_pct),
                "fee_cap": str(config.fee_cap) if config.fee_cap is not None else None,
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(config)
    return config


async def list_pricing_configs(
    session: AsyncSession, tenant_id: UUID
) -> list[PricingConfig]:
    """Return every pricing config in a tenant, newest-first."""
    result = await session.execute(
        select(PricingConfig)
        .where(PricingConfig.tenant_id == tenant_id)
        .order_by(PricingConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_pricing_config(
    session: AsyncSession,
    config_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a pricing config. Tenant-isolated."""
    result = await session.execute(
        select(PricingConfig).where(
            PricingConfig.id == config_id,
            PricingConfig.tenant_id == tenant_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise PricingConfigNotFound()
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
            action="pricing_config.deleted",
            entity_type="pricing_config",
            entity_id=str(config_id),
            before_state=before,
            ip_address=ip_address,
        )
    await session.commit()
