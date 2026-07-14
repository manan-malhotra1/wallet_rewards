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

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.shared.exceptions import (
    AppHTTPException,
    PricingConfigMissing,
    PricingConfigNotFound,
    ServiceNotConfigured,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_TAXES,
    Account,
    PricingConfig,
    Tenant,
)
from app.shared.utils.user_types import resolve_user_type


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
    user_type: str,
    amount: Decimal,
) -> PricingConfig | None:
    """Resolve the fee config for a slot, type- and amount-aware (Epics 16, 19).

    Matches the row whose `user_type` is the caller's OR the NULL default, AND
    whose amount band `[amount_from, amount_to)` contains `amount` (a NULL bound
    is open on that side; both NULL = applies to all amounts). Precedence:
    a typed row beats the NULL-type default, and a specific band beats the
    NULL-band default (`ORDER BY user_type NULLS LAST, amount_from NULLS LAST`).
    Returns None when nothing matches.
    """
    result = await session.execute(
        select(PricingConfig)
        .where(
            PricingConfig.tenant_id == tenant_id,
            PricingConfig.transaction_type == transaction_type,
            PricingConfig.account_type == account_type,
            PricingConfig.currency == currency.upper(),
            or_(
                PricingConfig.user_type == user_type,
                PricingConfig.user_type.is_(None),
            ),
            or_(
                PricingConfig.amount_from.is_(None),
                PricingConfig.amount_from <= amount,
            ),
            or_(
                PricingConfig.amount_to.is_(None),
                PricingConfig.amount_to > amount,
            ),
        )
        .order_by(
            PricingConfig.user_type.nulls_last(),
            PricingConfig.amount_from.nulls_last(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


# -----------------------------------------------------------------------------
# Fail-closed service gate (Epic 23)
# -----------------------------------------------------------------------------


async def pricing_config_exists(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    transaction_type: str,
    account_type: str,
    currency: str,
    user_type: str,
) -> bool:
    """Return True if any pricing config resolves for this slot (Epic 23 gate).

    Amount-agnostic existence check: a typed row for `user_type` OR the
    NULL-type default satisfies it. Mirrors `_find_pricing_config`'s scoping
    minus the amount band — the gate asks "is this service priced for this
    user type at all", not "does a fee resolve for one specific amount".
    """
    result = await session.execute(
        select(PricingConfig.id)
        .where(
            PricingConfig.tenant_id == tenant_id,
            PricingConfig.transaction_type == transaction_type,
            PricingConfig.account_type == account_type,
            PricingConfig.currency == currency.upper(),
            or_(
                PricingConfig.user_type == user_type,
                PricingConfig.user_type.is_(None),
            ),
        )
        .limit(1)
    )
    return result.first() is not None


async def _tenant_requires_config(session: AsyncSession, tenant_id: UUID) -> bool:
    """Return the tenant's `require_config_to_transact` flag (default False)."""
    result = await session.execute(
        select(Tenant.require_config_to_transact).where(Tenant.id == tenant_id)
    )
    return bool(result.scalar_one_or_none())


async def require_pricing_and_limits(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    service: str,
    account_type: str,
    currency: str,
    user_id: UUID,
) -> bool:
    """Enforce fail-closed service gating for a money path (Epic 23, Story 23.1).

    When the tenant's `require_config_to_transact` flag is set, a service may
    run only if BOTH a pricing config and a limit config resolve for the acting
    user's type. When the flag is off this is a no-op (legacy fail-open).

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        service: The service / transaction_type being gated (e.g. "p2p").
        account_type: The account type the config is scoped to.
        currency: 3-letter ISO 4217 (case-insensitive).
        user_id: The acting user, whose `user_type` selects the config scope.

    Returns:
        True if the tenant is fail-closed (config was required and verified),
        False if the flag is off (gate skipped). Callers use the flag to decide
        whether downstream config lookups may still fail open.

    Raises:
        ServiceNotConfigured (422): flag on and pricing OR limit config is
            missing for the resolved user_type.
    """
    if not await _tenant_requires_config(session, tenant_id):
        return False

    user_type = await resolve_user_type(session, tenant_id, user_id)

    if not await pricing_config_exists(
        session,
        tenant_id=tenant_id,
        transaction_type=service,
        account_type=account_type,
        currency=currency,
        user_type=user_type,
    ):
        raise ServiceNotConfigured(service, user_type)

    from app.modules.limits.service import limit_config_exists

    if not await limit_config_exists(
        session,
        tenant_id=tenant_id,
        transaction_type=service,
        account_type=account_type,
        currency=currency,
        user_type=user_type,
    ):
        raise ServiceNotConfigured(service, user_type)

    return True


# -----------------------------------------------------------------------------
# Fee computation
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class FeeQuote:
    """A resolved fee plus the config's `fee_inclusive` flag (axis 1).

    Attributes:
        fee: The total fee, 6 dp.
        fee_inclusive: Whether the fee is carved out of the principal
            (inclusive) or added on top (exclusive). The charge assembler
            (Epic 20) consumes this.
    """

    fee: Decimal
    fee_inclusive: bool


async def resolve_fee(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    transaction_type: str,
    account_type: str,
    currency: str,
    amount: Decimal,
) -> FeeQuote:
    """Compute the fee AND surface the config's `fee_inclusive` flag.

    Formula: `fixed_fee + min(variable_fee_pct * amount, fee_cap or +Inf)`,
    rounded to 6 dp (HALF_UP). The type- and amount-aware config row is
    resolved for the acting user; its `fee_inclusive` flag rides back so the
    charge assembler can place the fee on the right leg.

    Per Pay-PRD-0420, EVERY transaction must run pricing — no silent zero-fee
    fallback. Missing config → `PricingConfigMissing`.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: The acting user (drives type-aware resolution).
        transaction_type: 'p2p', 'cash_in', 'redemption', etc.
        account_type: 'financial_wallet' or 'points_account'.
        currency: ISO 4217 (or 'PTS').
        amount: Amount the user is moving (the base for the variable part).

    Returns:
        A `FeeQuote` with the fee and the inclusive flag.

    Raises:
        PricingConfigMissing: 422 — no config for this tuple.
    """
    user_type = await resolve_user_type(session, tenant_id, user_id)
    config = await _find_pricing_config(
        session,
        tenant_id=tenant_id,
        transaction_type=transaction_type,
        account_type=account_type,
        currency=currency,
        user_type=user_type,
        amount=amount,
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
    return FeeQuote(fee=fee, fee_inclusive=config.fee_inclusive)


async def calculate_fee(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    transaction_type: str,
    account_type: str,
    currency: str,
    amount: Decimal,
) -> Decimal:
    """Compute the fee for one transaction (see `resolve_fee` for the details).

    Thin wrapper returning just the fee amount, for the many callers that don't
    need the `fee_inclusive` flag.

    Raises:
        PricingConfigMissing: 422 — no config for this tuple.
    """
    quote = await resolve_fee(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        transaction_type=transaction_type,
        account_type=account_type,
        currency=currency,
        amount=amount,
    )
    return quote.fee


def account_type_for_currency(currency: str) -> str:
    """Default the fee's account scope from the currency.

    Points instruments (PTS) settle on the points account; every other
    currency on the financial wallet. This covers all current services
    (p2p / cash-in / withdraw / airtime → financial_wallet; redemption →
    points_account). Callers needing a different scope pass `account_type`
    explicitly to `quote_fee`.
    """
    return ACCOUNT_TYPE_POINTS if currency.upper() == "PTS" else ACCOUNT_TYPE_FINANCIAL_WALLET


async def quote_fee(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
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
            user_id=user_id,
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


async def _get_or_create_system_account(
    session: AsyncSession, *, tenant_id: UUID, currency: str, account_type: str
) -> Account:
    """Return the per-(tenant, currency) system account of `account_type`.

    Auto-creates the account on first use. Idempotent: re-callers see the
    existing row. The `uq_accounts_system_scoped` partial-unique index makes
    the create atomic — if a concurrent caller wins the race we roll back and
    refetch theirs.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        currency: ISO 4217 (or 'PTS'). Case-insensitive — we uppercase.
        account_type: A system account type (fee, commission, taxes, …).
    """
    currency_canon = currency.upper()
    existing = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.account_type == account_type,
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
        account_type=account_type,
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
                Account.account_type == account_type,
                Account.currency == currency_canon,
                Account.user_id.is_(None),
            )
        )
        return result.scalar_one()
    return account


async def get_or_create_system_fee_account(
    session: AsyncSession, *, tenant_id: UUID, currency: str
) -> Account:
    """Return the per-(tenant, currency) `system_fee_collected` account.

    Every fee leg CREDITs this account. Auto-created + idempotent.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        currency: ISO 4217 (or 'PTS'). Case-insensitive.
    """
    return await _get_or_create_system_account(
        session,
        tenant_id=tenant_id,
        currency=currency,
        account_type=ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    )


async def get_or_create_system_commission(
    session: AsyncSession, *, tenant_id: UUID, currency: str
) -> Account:
    """Return the per-(tenant, currency) `commission` pool account (Epic 19).

    A commission paid to an agent is DEBITed here → CREDITed to the agent. The
    operator tops the pool up; the balance guard skips it so it may run
    "negative". Auto-created + idempotent.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        currency: ISO 4217. Case-insensitive.
    """
    return await _get_or_create_system_account(
        session,
        tenant_id=tenant_id,
        currency=currency,
        account_type=ACCOUNT_TYPE_COMMISSION,
    )


async def get_or_create_system_taxes(
    session: AsyncSession, *, tenant_id: UUID, currency: str
) -> Account:
    """Return the per-(tenant, currency) `taxes` collector account (Epic 19).

    Every tax leg (on a fee or a commission) CREDITs this account.
    Auto-created + idempotent.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        currency: ISO 4217. Case-insensitive.
    """
    return await _get_or_create_system_account(
        session,
        tenant_id=tenant_id,
        currency=currency,
        account_type=ACCOUNT_TYPE_TAXES,
    )


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
        user_type=request.user_type,
        amount_from=request.amount_from,
        amount_to=request.amount_to,
        fixed_fee=request.fixed_fee,
        variable_fee_pct=request.variable_fee_pct,
        fee_cap=request.fee_cap,
        fee_inclusive=request.fee_inclusive,
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
                "user_type": config.user_type,
                "amount_from": str(config.amount_from) if config.amount_from is not None else None,
                "amount_to": str(config.amount_to) if config.amount_to is not None else None,
                "fixed_fee": str(config.fixed_fee),
                "variable_fee_pct": str(config.variable_fee_pct),
                "fee_cap": str(config.fee_cap) if config.fee_cap is not None else None,
                "fee_inclusive": config.fee_inclusive,
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(config)
    return config


async def list_pricing_configs(session: AsyncSession, tenant_id: UUID) -> list[PricingConfig]:
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
