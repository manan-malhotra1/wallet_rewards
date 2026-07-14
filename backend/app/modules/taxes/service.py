"""Tax engine service — Pricing v2 Epic 19 (Story 19.4).

`calculate_tax()` computes the tax on a fee and the tax on a commission for a
(tenant, currency), returning both amounts plus the inclusive/exclusive flags
so the charge assembler (Epic 20) can decide which ledger leg bears each. The
tax amount is always `rate * base` — the flags change who bears it, not how much
it is (see the worked example in the design spec). Plus admin CRUD on
`tax_configs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.taxes.schemas import TaxConfigCreateRequest
from app.shared.exceptions import AppHTTPException, TaxConfigNotFound, TenantNotFound
from app.shared.models import TaxConfig, Tenant

_SIX_DP = Decimal("0.000001")


@dataclass(frozen=True)
class TaxComputation:
    """Result of `calculate_tax` — the two tax amounts + their axis flags.

    Attributes:
        fee_tax: Tax on the fee (`fee_tax_pct * fee`), 6 dp.
        commission_tax: Tax on the commission (`commission_tax_pct * commission`), 6 dp.
        fee_tax_inclusive: Axis 2 — is the fee's tax carved out of the fee
            (inclusive) or added on top (exclusive).
        commission_tax_inclusive: Axis 3 — same for the commission's tax.
    """

    fee_tax: Decimal
    commission_tax: Decimal
    fee_tax_inclusive: bool
    commission_tax_inclusive: bool


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _find_tax_config(
    session: AsyncSession, *, tenant_id: UUID, currency: str
) -> TaxConfig | None:
    """Resolve the tax config for a (tenant, currency), or None."""
    result = await session.execute(
        select(TaxConfig).where(
            TaxConfig.tenant_id == tenant_id,
            TaxConfig.currency == currency.upper(),
        )
    )
    return result.scalar_one_or_none()


async def calculate_tax(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    currency: str,
    fee: Decimal,
    commission: Decimal,
) -> TaxComputation:
    """Compute tax on a fee and on a commission for a (tenant, currency).

    Each tax is `rate * base`, rounded to 6 dp (HALF_UP). A missing config →
    zero tax with exclusive (default) flags.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        currency: ISO 4217.
        fee: The computed fee (base for `fee_tax_pct`).
        commission: The computed commission (base for `commission_tax_pct`).

    Returns:
        A `TaxComputation` with both tax amounts and the two inclusive flags.
    """
    config = await _find_tax_config(session, tenant_id=tenant_id, currency=currency)
    if config is None:
        return TaxComputation(Decimal("0"), Decimal("0"), False, False)

    fee_tax = (fee * Decimal(str(config.fee_tax_pct))).quantize(_SIX_DP, rounding=ROUND_HALF_UP)
    commission_tax = (commission * Decimal(str(config.commission_tax_pct))).quantize(
        _SIX_DP, rounding=ROUND_HALF_UP
    )
    return TaxComputation(
        fee_tax=fee_tax,
        commission_tax=commission_tax,
        fee_tax_inclusive=config.fee_tax_inclusive,
        commission_tax_inclusive=config.commission_tax_inclusive,
    )


# -----------------------------------------------------------------------------
# Admin CRUD
# -----------------------------------------------------------------------------


async def create_tax_config(
    session: AsyncSession,
    request: TaxConfigCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> TaxConfig:
    """Persist a new tax config. 409 on unique (tenant, currency) collision."""
    await _assert_tenant_exists(session, request.tenant_id)
    config = TaxConfig(
        tenant_id=request.tenant_id,
        currency=request.currency.upper(),
        fee_tax_pct=request.fee_tax_pct,
        commission_tax_pct=request.commission_tax_pct,
        fee_tax_inclusive=request.fee_tax_inclusive,
        commission_tax_inclusive=request.commission_tax_inclusive,
    )
    session.add(config)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "tax_config_already_exists",
            "A tax config already exists for this (tenant, currency).",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="tax_config.created",
            entity_type="tax_config",
            entity_id=str(config.id),
            after_state={
                "currency": config.currency,
                "fee_tax_pct": str(config.fee_tax_pct),
                "commission_tax_pct": str(config.commission_tax_pct),
                "fee_tax_inclusive": config.fee_tax_inclusive,
                "commission_tax_inclusive": config.commission_tax_inclusive,
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(config)
    return config


async def list_tax_configs(session: AsyncSession, tenant_id: UUID) -> list[TaxConfig]:
    """Return every tax config in a tenant, newest-first."""
    result = await session.execute(
        select(TaxConfig)
        .where(TaxConfig.tenant_id == tenant_id)
        .order_by(TaxConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_tax_config(
    session: AsyncSession,
    config_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a tax config. Tenant-isolated."""
    result = await session.execute(
        select(TaxConfig).where(
            TaxConfig.id == config_id,
            TaxConfig.tenant_id == tenant_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise TaxConfigNotFound()
    before = {
        "currency": config.currency,
        "fee_tax_pct": str(config.fee_tax_pct),
        "commission_tax_pct": str(config.commission_tax_pct),
    }
    await session.delete(config)
    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="tax_config.deleted",
            entity_type="tax_config",
            entity_id=str(config_id),
            before_state=before,
            ip_address=ip_address,
        )
    await session.commit()
