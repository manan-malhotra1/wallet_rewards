"""Bonus multipliers — admin CRUD + hot-path resolution.

`resolve_multiplier_for_issuance()` is the function the rewards layer
calls when issuing a reward. It returns the SINGLE best-matching
multiplier (highest value), or `Decimal('1.00')` when nothing applies.

Resolution rules (in order of strength):
  1. Window must be valid for `now` (valid_from <= now < valid_until,
     either NULL = open-ended).
  2. tenant_id must match.
  3. rule_id: must match the firing rule OR be NULL (global per-rule scope).
  4. segment_id: must match a segment the user belongs to OR be NULL.
  5. Among matches, the LARGEST multiplier wins. (Overlapping multipliers
     don't stack — the biggest single multiplier applies.)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.multipliers.schemas import (
    BonusMultiplierCreateRequest,
    BonusMultiplierOut,
)
from app.modules.segments.service import user_is_in_segment
from app.shared.exceptions import AppHTTPException, TenantNotFound
from app.shared.models import BonusMultiplier, Tenant


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


# -----------------------------------------------------------------------------
# Hot path
# -----------------------------------------------------------------------------


async def resolve_multiplier_for_issuance(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    rule_id: UUID,
    user_id: UUID,
    now: datetime | None = None,
) -> Decimal:
    """Return the multiplier to apply for this (tenant, rule, user) at `now`.

    `1.00` when no multiplier matches. Caller is the rewards layer; the
    rule's `reward_value` is multiplied by this number before the credit
    ledger entry is written.

    Cheap: one indexed query + an O(N) sort in Python, where N is the
    number of multipliers configured for the tenant (typically < 10).

    Args:
        session: Async DB session (read-only).
        tenant_id: Scope.
        rule_id: The firing rule.
        user_id: The user being rewarded — used to resolve segment scope.
        now: Override for tests. Defaults to `datetime.now(UTC)`.

    Returns:
        The Decimal multiplier (>= 1 when one matches, exactly 1.00 when none).
    """
    current = now or datetime.now(UTC)

    # Candidate rows: tenant match + rule scope is NULL or matches +
    # window covers `now` (NULL on either bound = open-ended).
    candidates_q = await session.execute(
        select(BonusMultiplier).where(
            BonusMultiplier.tenant_id == tenant_id,
            (BonusMultiplier.rule_id.is_(None)) | (BonusMultiplier.rule_id == rule_id),
            (BonusMultiplier.valid_from.is_(None)) | (BonusMultiplier.valid_from <= current),
            (BonusMultiplier.valid_until.is_(None)) | (BonusMultiplier.valid_until > current),
        )
    )
    candidates = list(candidates_q.scalars().all())

    # Filter by segment scope. NULL = applies to everyone; otherwise the
    # user must be a member of the segment.
    eligible: list[BonusMultiplier] = []
    for m in candidates:
        if m.segment_id is None:
            eligible.append(m)
            continue
        if await user_is_in_segment(session, user_id=user_id, segment_id=m.segment_id):
            eligible.append(m)

    if not eligible:
        return Decimal("1.00")

    # Biggest multiplier wins.
    best = max(eligible, key=lambda m: Decimal(str(m.multiplier)))
    return Decimal(str(best.multiplier))


# -----------------------------------------------------------------------------
# Admin CRUD
# -----------------------------------------------------------------------------


async def _find_multiplier_by_key(
    session: AsyncSession, tenant_id: UUID, idempotency_key: str
) -> BonusMultiplier | None:
    """Return the multiplier already created under this key, or None."""
    return (
        await session.execute(
            select(BonusMultiplier).where(
                BonusMultiplier.tenant_id == tenant_id,
                BonusMultiplier.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()


async def create_multiplier(
    session: AsyncSession,
    request: BonusMultiplierCreateRequest,
    *,
    idempotency_key: str,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> BonusMultiplier:
    """Persist a new multiplier, keyed idempotently on the `Idempotency-Key`.

    A replay with the same `(tenant, idempotency_key)` returns the ORIGINAL
    row without inserting a duplicate or writing a second audit record
    (Pay-PRD-0200).

    Args:
        session: Async DB session (committed here).
        request: The validated create payload.
        idempotency_key: The required `Idempotency-Key` header value.
        admin: Acting admin — audited when present.
        ip_address: Caller IP for the audit record.

    Returns:
        The created (or replayed) BonusMultiplier.

    Raises:
        TenantNotFound: request.tenant_id is unknown.

    Side effects:
        Inserts a `bonus_multipliers` row and a `multiplier.created` audit row.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    # Idempotency fast-path — a replay returns the original row before any write.
    replay = await _find_multiplier_by_key(session, request.tenant_id, idempotency_key)
    if replay is not None:
        return replay

    row = BonusMultiplier(
        tenant_id=request.tenant_id,
        rule_id=request.rule_id,
        segment_id=request.segment_id,
        multiplier=request.multiplier,
        valid_from=request.valid_from,
        valid_until=request.valid_until,
        idempotency_key=idempotency_key,
    )
    session.add(row)
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="multiplier.created",
            entity_type="bonus_multiplier",
            entity_id=str(row.id),
            after_state={
                "rule_id": str(row.rule_id) if row.rule_id else None,
                "segment_id": str(row.segment_id) if row.segment_id else None,
                "multiplier": str(row.multiplier),
                "valid_from": (row.valid_from.isoformat() if row.valid_from else None),
                "valid_until": (row.valid_until.isoformat() if row.valid_until else None),
            },
            ip_address=ip_address,
        )

    try:
        await session.commit()
    except IntegrityError:
        # A concurrent same-key request won the UNIQUE (tenant, key) race
        # between our fast-path miss and this commit. Roll back our row/audit
        # and replay the winner's multiplier — a concurrent retry must still
        # return the original, never surface a 409/500.
        await session.rollback()
        replay = await _find_multiplier_by_key(session, request.tenant_id, idempotency_key)
        if replay is not None:
            return replay
        raise
    await session.refresh(row)
    return row


async def list_multipliers_for_tenant(
    session: AsyncSession, tenant_id: UUID
) -> list[BonusMultiplierOut]:
    """Every multiplier in the tenant, newest first."""
    result = await session.execute(
        select(BonusMultiplier)
        .where(BonusMultiplier.tenant_id == tenant_id)
        .order_by(BonusMultiplier.created_at.desc())
    )
    return [BonusMultiplierOut.model_validate(m) for m in result.scalars().all()]


async def delete_multiplier(
    session: AsyncSession,
    multiplier_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a multiplier. 404 cross-tenant."""
    result = await session.execute(
        select(BonusMultiplier).where(
            BonusMultiplier.id == multiplier_id,
            BonusMultiplier.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise AppHTTPException(404, "multiplier_not_found", "Multiplier not found.")

    before = {
        "multiplier": str(row.multiplier),
        "rule_id": str(row.rule_id) if row.rule_id else None,
        "segment_id": str(row.segment_id) if row.segment_id else None,
    }
    await session.delete(row)

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="multiplier.deleted",
            entity_type="bonus_multiplier",
            entity_id=str(multiplier_id),
            before_state=before,
            ip_address=ip_address,
        )

    await session.commit()
