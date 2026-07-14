"""Commission engine service — Pricing v2 Epic 19 (Story 19.3).

Two surfaces mirroring the pricing service:
  - `calculate_commission()` — pure-Python commission math for the acting
    agent, amount- and type-aware. Unlike pricing there is NO silent-zero
    prohibition: a missing config simply means "no commission" (`Decimal("0")`),
    because commission is an optional additive payout, not a mandatory charge.
  - Admin CRUD on `commission_configs`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.shared.exceptions import (
    AppHTTPException,
    CommissionConfigNotFound,
    TenantNotFound,
)
from app.shared.models import CommissionConfig, Tenant
from app.shared.utils.user_types import resolve_user_type


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _find_commission_config(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    transaction_type: str,
    currency: str,
    user_type: str,
    amount: Decimal,
) -> CommissionConfig | None:
    """Resolve the commission config for a slot, type- and amount-aware.

    Same precedence rules as pricing: a typed row beats the NULL-type default,
    and a specific amount band beats the NULL-band default. Returns None when
    nothing matches (→ no commission).
    """
    result = await session.execute(
        select(CommissionConfig)
        .where(
            CommissionConfig.tenant_id == tenant_id,
            CommissionConfig.transaction_type == transaction_type,
            CommissionConfig.currency == currency.upper(),
            or_(
                CommissionConfig.user_type == user_type,
                CommissionConfig.user_type.is_(None),
            ),
            or_(
                CommissionConfig.amount_from.is_(None),
                CommissionConfig.amount_from <= amount,
            ),
            or_(
                CommissionConfig.amount_to.is_(None),
                CommissionConfig.amount_to > amount,
            ),
        )
        .order_by(
            CommissionConfig.user_type.nulls_last(),
            CommissionConfig.amount_from.nulls_last(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def calculate_commission(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_user_id: UUID,
    transaction_type: str,
    currency: str,
    amount: Decimal,
) -> Decimal:
    """Compute the commission owed to the acting agent for one transaction.

    Formula: `fixed_commission + min(variable_commission_pct * amount,
    commission_cap or +Inf)`, rounded to 6 dp (HALF_UP) for the ledger's
    NUMERIC(20, 6) storage. The agent's `user_type` is resolved to pick the
    right schedule row.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        agent_user_id: The acting agent (commission beneficiary).
        transaction_type: Service code, e.g. 'cash_in'.
        currency: ISO 4217.
        amount: The transaction amount (base for the variable part).

    Returns:
        The commission as a Decimal (6 dp). `Decimal("0")` when no config
        applies — commission is optional and additive, never mandatory.
    """
    user_type = await resolve_user_type(session, tenant_id, agent_user_id)
    config = await _find_commission_config(
        session,
        tenant_id=tenant_id,
        transaction_type=transaction_type,
        currency=currency,
        user_type=user_type,
        amount=amount,
    )
    if config is None:
        return Decimal("0")

    fixed = Decimal(str(config.fixed_commission))
    pct = Decimal(str(config.variable_commission_pct))
    cap = Decimal(str(config.commission_cap)) if config.commission_cap is not None else None

    variable = pct * amount
    if cap is not None and variable > cap:
        variable = cap

    return (fixed + variable).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# -----------------------------------------------------------------------------
# Admin CRUD
# -----------------------------------------------------------------------------


async def create_commission_config(
    session: AsyncSession,
    request: CommissionConfigCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> CommissionConfig:
    """Persist a new commission config. 409 on unique-index collision."""
    await _assert_tenant_exists(session, request.tenant_id)
    config = CommissionConfig(
        tenant_id=request.tenant_id,
        transaction_type=request.transaction_type,
        currency=request.currency.upper(),
        user_type=request.user_type,
        amount_from=request.amount_from,
        amount_to=request.amount_to,
        fixed_commission=request.fixed_commission,
        variable_commission_pct=request.variable_commission_pct,
        commission_cap=request.commission_cap,
    )
    session.add(config)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "commission_config_already_exists",
            "A commission config already exists for this scope.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="commission_config.created",
            entity_type="commission_config",
            entity_id=str(config.id),
            after_state={
                "transaction_type": config.transaction_type,
                "currency": config.currency,
                "user_type": config.user_type,
                "amount_from": (
                    str(config.amount_from) if config.amount_from is not None else None
                ),
                "amount_to": str(config.amount_to) if config.amount_to is not None else None,
                "fixed_commission": str(config.fixed_commission),
                "variable_commission_pct": str(config.variable_commission_pct),
                "commission_cap": (
                    str(config.commission_cap) if config.commission_cap is not None else None
                ),
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(config)
    return config


async def list_commission_configs(session: AsyncSession, tenant_id: UUID) -> list[CommissionConfig]:
    """Return every commission config in a tenant, newest-first."""
    result = await session.execute(
        select(CommissionConfig)
        .where(CommissionConfig.tenant_id == tenant_id)
        .order_by(CommissionConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_commission_config(
    session: AsyncSession,
    config_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a commission config. Tenant-isolated."""
    result = await session.execute(
        select(CommissionConfig).where(
            CommissionConfig.id == config_id,
            CommissionConfig.tenant_id == tenant_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise CommissionConfigNotFound()
    before = {
        "transaction_type": config.transaction_type,
        "currency": config.currency,
        "user_type": config.user_type,
    }
    await session.delete(config)
    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="commission_config.deleted",
            entity_type="commission_config",
            entity_id=str(config_id),
            before_state=before,
            ip_address=ip_address,
        )
    await session.commit()
