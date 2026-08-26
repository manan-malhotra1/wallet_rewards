"""Commission engine service — Pricing v2 Epic 19 (Story 19.3).

Two surfaces mirroring the pricing service:
  - `calculate_commission()` — commission math for the acting earner AND their
    parent, amount- and type-aware. Returns a `CommissionOutcome` naming both
    legs, the payout destination and any parent-skip reason. Unlike pricing
    there is NO silent-zero prohibition: a missing config simply means "no
    commission", because commission is an optional additive payout, not a
    mandatory charge.
  - Admin CRUD on `commission_configs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.commissions.resolution import (
    DESTINATION_COMMISSION,
    DESTINATION_MAIN,
    SKIP_PARENT_ZERO_RATE,
    resolve_parent_target,
)
from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.user_types.service import (
    assert_optional_user_type_valid,
    is_commission_wallet_eligible,
)
from app.shared.exceptions import (
    AppHTTPException,
    CommissionDestinationNotAvailable,
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


@dataclass(frozen=True)
class CommissionOutcome:
    """Both commission legs for one transaction, plus where they land.

    Attributes:
        self_amount: The acting earner's own commission, 6 dp.
        parent_amount: Their parent's commission, 6 dp. Zero when skipped.
        destination: 'main_wallet' or 'commission_wallet' — applies to BOTH
            legs (D6). 'main_wallet' when no config resolved.
        parent_account_id: The ACCOUNT the parent's leg credits, or None. An
            account rather than a user id because that is what the caller needs
            to build the ledger leg; resolving it twice would let the two
            resolutions disagree.
        parent_skip_reason: Why the parent leg does not pay, or None.
    """

    self_amount: Decimal
    parent_amount: Decimal
    destination: str
    parent_account_id: UUID | None
    parent_skip_reason: str | None


_NO_COMMISSION = CommissionOutcome(
    self_amount=Decimal("0"),
    parent_amount=Decimal("0"),
    destination=DESTINATION_MAIN,
    parent_account_id=None,
    parent_skip_reason=None,
)


def _band_amount(
    fixed: Decimal, pct: Decimal, cap: Decimal | None, amount: Decimal
) -> Decimal:
    """`fixed + min(pct * amount, cap or +Inf)`, quantized to the ledger's 6 dp.

    Shared by both legs so the child and parent round IDENTICALLY — computing
    them differently is how a three-leg ledger fails to balance by a cent.
    """
    variable = pct * amount
    if cap is not None and variable > cap:
        variable = cap
    return (fixed + variable).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def calculate_commission(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_user_id: UUID,
    transaction_type: str,
    currency: str,
    amount: Decimal,
) -> CommissionOutcome:
    """Compute both commission legs for one transaction.

    The parent's rate is a percentage of the TRANSACTION AMOUNT (D8), resolved
    from the SAME config row and therefore the same amount band and precedence
    as the child's. It is NOT a share of the child's commission.

    A missing config yields `_NO_COMMISSION` rather than raising — commission
    stays an additive, optional payout, not a mandatory charge (unchanged from
    the pre-2026-08-26 behaviour, and deliberately NOT invariant-#12 territory).

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        agent_user_id: The acting earner (commission beneficiary).
        transaction_type: Service code, e.g. 'cash_in'.
        currency: ISO 4217.
        amount: The transaction amount — the base for BOTH variable parts.

    Returns:
        A CommissionOutcome. `parent_amount` is zero whenever
        `parent_skip_reason` is set.
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
        return _NO_COMMISSION

    self_amount = _band_amount(
        Decimal(str(config.fixed_commission)),
        Decimal(str(config.variable_commission_pct)),
        Decimal(str(config.commission_cap))
        if config.commission_cap is not None
        else None,
        amount,
    )
    parent_amount = _band_amount(
        Decimal(str(config.parent_fixed_commission)),
        Decimal(str(config.parent_variable_commission_pct)),
        Decimal(str(config.parent_commission_cap))
        if config.parent_commission_cap is not None
        else None,
        amount,
    )

    if parent_amount <= 0:
        return CommissionOutcome(
            self_amount=self_amount,
            parent_amount=Decimal("0"),
            destination=config.payout_destination,
            parent_account_id=None,
            parent_skip_reason=SKIP_PARENT_ZERO_RATE,
        )

    target = await resolve_parent_target(
        session,
        tenant_id=tenant_id,
        earner_user_id=agent_user_id,
        destination=config.payout_destination,
        currency=currency,
    )
    if target.account_id is None:
        return CommissionOutcome(
            self_amount=self_amount,
            parent_amount=Decimal("0"),
            destination=config.payout_destination,
            parent_account_id=None,
            parent_skip_reason=target.skip_reason,
        )

    return CommissionOutcome(
        self_amount=self_amount,
        parent_amount=parent_amount,
        destination=config.payout_destination,
        parent_account_id=target.account_id,
        parent_skip_reason=None,
    )


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
        payout_destination=request.payout_destination,
        parent_fixed_commission=request.parent_fixed_commission,
        parent_variable_commission_pct=request.parent_variable_commission_pct,
        parent_commission_cap=request.parent_commission_cap,
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
        "payout_destination": config.payout_destination,
        "parent_fixed_commission": str(config.parent_fixed_commission),
        "parent_variable_commission_pct": str(config.parent_variable_commission_pct),
        "parent_commission_cap": (
            str(config.parent_commission_cap)
            if config.parent_commission_cap is not None
            else None
        ),
    }


async def _assert_destination_available(
    session: AsyncSession, request: CommissionConfigCreateRequest
) -> None:
    """Refuse a commission-wallet destination that cannot resolve to a wallet (D7).

    Three ways a rule could name a destination with no wallet behind it: the
    tenant flag is off, the rule is a catch-all (NULL user_type) band that
    could match a consumer, or it is scoped to a consumer-category type.

    Checked BEFORE any write — and, in the replace path, before the deletes —
    so a bad payload never wipes a live band set. Refusing here rather than at
    payout means an unpayable rule can never be saved at all, which is what
    makes the payout path's missing-wallet branch a backstop rather than a live
    code path.

    Raises:
        CommissionDestinationNotAvailable: 422 for any of the three cases.
    """
    if request.payout_destination != DESTINATION_COMMISSION:
        return

    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == request.tenant_id))
    ).scalar_one_or_none()
    if tenant is None or not tenant.commission_wallet_enabled:
        raise CommissionDestinationNotAvailable()

    # A NULL user_type band applies to EVERY type including consumers, who
    # never hold a commission wallet. Rather than resolving that per-earner at
    # payout, forbid the combination outright.
    if request.user_type is None:
        raise CommissionDestinationNotAvailable()

    if not await is_commission_wallet_eligible(
        session, request.tenant_id, request.user_type
    ):
        raise CommissionDestinationNotAvailable()


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
    await _assert_destination_available(session, request)
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
    # Before the deletes below, so a bad payload never wipes the live band set.
    await _assert_destination_available(session, first)
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
