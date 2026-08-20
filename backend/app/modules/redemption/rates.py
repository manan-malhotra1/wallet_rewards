"""Points→fiat conversion-rate config service (Pay-PRD-1210/1220, design 07 §6.2).

One ACTIVE rate per (tenant, currency), managed through the config
change-request maker-checker exactly like pricing/limits — the create /
replace / delete helpers here are the `conversion_rate` entries in
config_requests/apply.py's dispatch registries. `resolve_active_rate` is the
FAIL-CLOSED gate the internal-redemption flow calls: no ACTIVE row → 422
`conversion_rate_missing`, never a default.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.redemption.schemas import ConversionRateCreateRequest
from app.shared.exceptions import AppHTTPException, ConversionRateMissing, TenantNotFound
from app.shared.models import PointsConversionRate, Tenant


def _rate_state(rate: PointsConversionRate) -> dict[str, Any]:
    """Serialise a rate row for audit before/after states."""
    return {
        "currency": rate.currency,
        "points_per_unit": str(rate.points_per_unit),
        "value_per_unit": str(rate.value_per_unit),
        "max_points_per_txn": (
            str(rate.max_points_per_txn) if rate.max_points_per_txn is not None else None
        ),
        "max_balance_pct_per_txn": (
            str(rate.max_balance_pct_per_txn) if rate.max_balance_pct_per_txn is not None else None
        ),
        "status": rate.status,
    }


def _new_rate(request: ConversionRateCreateRequest) -> PointsConversionRate:
    """Build an ACTIVE rate row from a validated create request."""
    return PointsConversionRate(
        tenant_id=request.tenant_id,
        currency=request.currency.upper(),
        points_per_unit=request.points_per_unit,
        value_per_unit=request.value_per_unit,
        max_points_per_txn=request.max_points_per_txn,
        max_balance_pct_per_txn=request.max_balance_pct_per_txn,
    )


async def create_conversion_rate_config(
    session: AsyncSession,
    request: ConversionRateCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> PointsConversionRate:
    """Create a conversion rate — one per (tenant, currency), 409 on collision."""
    tenant = await session.execute(select(Tenant).where(Tenant.id == request.tenant_id))
    if tenant.scalar_one_or_none() is None:
        raise TenantNotFound()

    rate = _new_rate(request)
    session.add(rate)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "conversion_rate_already_exists",
            "A conversion rate already exists for this currency.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="conversion_rate_config.created",
            entity_type="conversion_rate_config",
            entity_id=str(rate.id),
            after_state=_rate_state(rate),
            ip_address=ip_address,
        )
    await session.commit()
    await session.refresh(rate)
    return rate


async def replace_conversion_rate_config_for_scope(
    session: AsyncSession,
    requests: list[ConversionRateCreateRequest],
    *,
    target_config_id: UUID | None = None,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Atomically replace the rate for a (tenant, currency) scope.

    Single-row type: delete the existing row (flushed first so the unique
    index never trips), insert the new one, audit, one commit. A mid-apply
    failure rolls the whole replace back.
    """
    first = requests[0]
    existing = list(
        (
            await session.execute(
                select(PointsConversionRate).where(
                    PointsConversionRate.tenant_id == first.tenant_id,
                    PointsConversionRate.currency == first.currency.upper(),
                )
            )
        )
        .scalars()
        .all()
    )
    before = [_rate_state(r) for r in existing]
    for row in existing:
        await session.delete(row)
    await session.flush()  # DELETE must precede the INSERT (unique index).

    rate = _new_rate(first)
    session.add(rate)
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=first.tenant_id,
            action="conversion_rate_config.updated",
            entity_type="conversion_rate_config",
            entity_id=str(target_config_id or rate.id),
            before_state={"replaced": before},
            after_state=_rate_state(rate),
            ip_address=ip_address,
        )
    await session.commit()


async def delete_conversion_rate_config_for_scope(
    session: AsyncSession,
    target: PointsConversionRate,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete the rate row for `target`'s (tenant, currency) scope, one commit."""
    existing = list(
        (
            await session.execute(
                select(PointsConversionRate).where(
                    PointsConversionRate.tenant_id == target.tenant_id,
                    PointsConversionRate.currency == target.currency,
                )
            )
        )
        .scalars()
        .all()
    )
    before = [_rate_state(r) for r in existing]
    for row in existing:
        await session.delete(row)
    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=target.tenant_id,
            action="conversion_rate_config.deleted",
            entity_type="conversion_rate_config",
            entity_id=str(target.id),
            before_state={"deleted": before},
            ip_address=ip_address,
        )
    await session.commit()


async def list_conversion_rates(
    session: AsyncSession, tenant_id: UUID, *, active_only: bool = False
) -> list[PointsConversionRate]:
    """Return the tenant's conversion rates, currency-ascending."""
    stmt = select(PointsConversionRate).where(PointsConversionRate.tenant_id == tenant_id)
    if active_only:
        stmt = stmt.where(PointsConversionRate.status == "active")
    stmt = stmt.order_by(PointsConversionRate.currency.asc())
    return list((await session.execute(stmt)).scalars().all())


async def resolve_active_rate(
    session: AsyncSession, tenant_id: UUID, currency: str
) -> PointsConversionRate:
    """FAIL-CLOSED rate lookup (Pay-PRD-1220): ACTIVE row or 422, no defaults."""
    result = await session.execute(
        select(PointsConversionRate).where(
            PointsConversionRate.tenant_id == tenant_id,
            PointsConversionRate.currency == currency.upper(),
            PointsConversionRate.status == "active",
        )
    )
    rate = result.scalar_one_or_none()
    if rate is None:
        raise ConversionRateMissing()
    return rate
