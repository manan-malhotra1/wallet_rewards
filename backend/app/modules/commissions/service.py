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

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.user_types.service import assert_optional_user_type_valid
from app.shared.exceptions import (
    AppHTTPException,
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

    Same rules as pricing: the amount band `[amount_from, amount_to]` is
    inclusive on BOTH ends (an amount equal to `amount_to` still matches; a NULL
    bound is open on that side). A typed row beats the NULL-type default, and a
    specific amount band beats the NULL-band default. Returns None when nothing
    matches (→ no commission).
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
                CommissionConfig.amount_to >= amount,
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


def _new_commission_config(request: CommissionConfigCreateRequest) -> CommissionConfig:
    """Build a CommissionConfig ORM row from a validated create request (no DB I/O).

    Shared by `create_commission_config` and `replace_commission_config_for_scope`.
    """
    return CommissionConfig(
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


def _commission_scope_filter(
    *,
    tenant_id: UUID,
    transaction_type: str,
    currency: str,
    user_type: str | None,
) -> list[ColumnElement[bool]]:
    """Column predicates selecting EVERY commission row in one scope.

    Shared by `replace_commission_config_for_scope` and
    `delete_commission_config_for_scope`. No account_type — commission is keyed
    without it. `currency` is upper-cased; a NULL `user_type` matched with IS NULL.
    """
    return [
        CommissionConfig.tenant_id == tenant_id,
        CommissionConfig.transaction_type == transaction_type,
        CommissionConfig.currency == currency.upper(),
        CommissionConfig.user_type.is_(None)
        if user_type is None
        else CommissionConfig.user_type == user_type,
    ]


def _commission_config_state(config: CommissionConfig) -> dict[str, object]:
    """Serialise a commission config for an audit snapshot (Decimals to str)."""
    return {
        "transaction_type": config.transaction_type,
        "currency": config.currency,
        "user_type": config.user_type,
        "amount_from": str(config.amount_from) if config.amount_from is not None else None,
        "amount_to": str(config.amount_to) if config.amount_to is not None else None,
        "fixed_commission": str(config.fixed_commission),
        "variable_commission_pct": str(config.variable_commission_pct),
        "commission_cap": (
            str(config.commission_cap) if config.commission_cap is not None else None
        ),
    }


async def create_commission_config(
    session: AsyncSession,
    request: CommissionConfigCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> CommissionConfig:
    """Persist a new commission config.

    Raises:
        TenantNotFound: 404 — unknown tenant.
        UnknownUserType: 422 — the row is scoped to a type that does not resolve
            for this tenant (spec §6). Such a row would never match at payout
            time and the agent would silently fall through to the
            `user_type IS NULL` default band.
        AppHTTPException 409: unique-index collision.
    """
    await _assert_tenant_exists(session, request.tenant_id)
    await assert_optional_user_type_valid(
        session, tenant_id=request.tenant_id, code=request.user_type
    )
    config = _new_commission_config(request)
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
            after_state=_commission_config_state(config),
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(config)
    return config


async def replace_commission_config_for_scope(
    session: AsyncSession,
    requests: list[CommissionConfigCreateRequest],
    *,
    target_config_id: UUID | None = None,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Atomically replace ALL commission bands for a scope with a new band set.

    Scope = the shared (tenant, transaction_type, currency, user_type) of the
    incoming bands (no account_type — commission is keyed without it). Every
    existing row for that scope is deleted and the new band(s) inserted in ONE
    transaction — DELETEs flushed before INSERTs so the unique index never
    trips — committed once. A mid-apply failure rolls the whole replace back.

    Args:
        requests: The validated new band set (one element for a single band).
        target_config_id: The live row the maker edited (audit traceability).

    Raises:
        UnknownUserType: 422 — the new scope names a type that does not resolve
            for this tenant (spec §6). Checked BEFORE the deletes, so a bad
            payload never wipes the live band set. One check covers the whole
            set: every band shares the scope's `user_type`.

    Side effects:
        Deletes + inserts commission_configs rows; appends one
        `commission_config.updated` audit row. Commits once.
    """
    first = requests[0]
    await assert_optional_user_type_valid(session, tenant_id=first.tenant_id, code=first.user_type)
    scope = _commission_scope_filter(
        tenant_id=first.tenant_id,
        transaction_type=first.transaction_type,
        currency=first.currency,
        user_type=first.user_type,
    )
    existing = list((await session.execute(select(CommissionConfig).where(*scope))).scalars().all())
    before = [_commission_config_state(c) for c in existing]
    for row in existing:
        await session.delete(row)
    await session.flush()  # DELETEs must precede the INSERTs (unique index).

    new_configs = [_new_commission_config(r) for r in requests]
    session.add_all(new_configs)
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=first.tenant_id,
            action="commission_config.updated",
            entity_type="commission_config",
            entity_id=str(target_config_id or new_configs[0].id),
            before_state={"replaced": before},
            after_state={"bands": [_commission_config_state(c) for c in new_configs]},
            ip_address=ip_address,
        )
    await session.commit()


async def list_commission_configs(session: AsyncSession, tenant_id: UUID) -> list[CommissionConfig]:
    """Return every commission config in a tenant, newest-first."""
    result = await session.execute(
        select(CommissionConfig)
        .where(CommissionConfig.tenant_id == tenant_id)
        .order_by(CommissionConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_commission_config_for_scope(
    session: AsyncSession,
    target: CommissionConfig,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete EVERY commission band sharing `target`'s scope, in one commit.

    A commission schedule is several bands sharing (tenant, transaction_type,
    currency, user_type); a per-config delete removes them all — not only the
    band named by the maker. The removals plus one `commission_config.deleted`
    audit row (before_state summarising every removed band) land in ONE
    transaction, so a mid-delete failure rolls the whole scope back.

    Args:
        target: The live row whose scope is removed — already loaded and
            tenant-checked by the caller; its id anchors the audit entry.

    Side effects:
        Deletes commission_configs rows; appends one `commission_config.deleted`
        audit row. Commits once.
    """
    scope = _commission_scope_filter(
        tenant_id=target.tenant_id,
        transaction_type=target.transaction_type,
        currency=target.currency,
        user_type=target.user_type,
    )
    existing = list((await session.execute(select(CommissionConfig).where(*scope))).scalars().all())
    before = [_commission_config_state(c) for c in existing]
    for row in existing:
        await session.delete(row)
    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=target.tenant_id,
            action="commission_config.deleted",
            entity_type="commission_config",
            entity_id=str(target.id),
            before_state={"deleted": before},
            ip_address=ip_address,
        )
    await session.commit()
