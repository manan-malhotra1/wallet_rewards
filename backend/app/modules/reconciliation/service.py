"""Reconciliation service — sweep, manual resolve, audit log writes.

The sweep iterates PENDING redemptions older than the caller's threshold.
For each, it bumps retry_count; once retry_count reaches the provider's
configured max_retries, the redemption is escalated to MANUAL_REVIEW.

Every action — both bumps and escalations — is recorded in the immutable
`audit_log` table (PRD §6.13) so operators can review what the platform did
overnight without trusting application logs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.service import resolve_user_names
from app.modules.reconciliation.schemas import (
    AuditEntry,
    ManualReviewItem,
    PendingItem,
    ResolveRequest,
    SweepOutcome,
)
from app.shared.exceptions import (
    InvalidResolveOutcome,
    RedemptionNotFound,
    RedemptionNotInManualReview,
    TenantNotFound,
)
from app.shared.models import (
    ACTION_RECON_ESCALATED,
    ACTION_RECON_RESOLVED_COMPLETED,
    ACTION_RECON_RESOLVED_REVERSED,
    ACTION_RECON_SWEPT,
    ACTOR_ADMIN,
    ACTOR_SYSTEM,
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_REVERSED,
    REDEMPTION_STATUS_COMPLETED,
    REDEMPTION_STATUS_FAILED,
    REDEMPTION_STATUS_MANUAL_REVIEW,
    REDEMPTION_STATUS_PENDING,
    TXN_STATUS_COMPLETED,
    TXN_STATUS_REVERSED,
    AuditLog,
    LedgerEntry,
    Redemption,
    RedemptionProvider,
    Tenant,
    Transaction,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject when the tenant_id is unknown — same pattern as elsewhere."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


def _redemption_snapshot(r: Redemption) -> dict[str, Any]:
    """JSON-serialisable snapshot of a Redemption row.

    Used for audit_log before/after states. Keep the field set narrow — only
    what an auditor needs to reconstruct what changed.
    """
    return {
        "id": str(r.id),
        "status": r.status,
        "retry_count": r.retry_count,
        "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "failure_reason": r.failure_reason,
        "external_reference": r.external_reference,
    }


# -----------------------------------------------------------------------------
# Sweep
# -----------------------------------------------------------------------------


async def sweep_pending(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    threshold_minutes: int,
) -> SweepOutcome:
    """Find stale PENDING redemptions, bump retry, escalate after max.

    In Phase E.1 we don't actually call the provider's status_check_url —
    that requires HMAC-verified callbacks (Phase F). The retry counter
    increases on every sweep regardless of provider response; once it hits
    `provider.max_retries`, the redemption goes to MANUAL_REVIEW.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        threshold_minutes: Only redemptions older than this are considered.

    Returns:
        SweepOutcome with counts of scanned / bumped / escalated.

    Raises:
        TenantNotFound: unknown tenant.
    """
    await _assert_tenant_exists(session, tenant_id)

    cutoff = datetime.now(UTC) - timedelta(minutes=threshold_minutes)
    pending = (
        await session.execute(
            select(Redemption, RedemptionProvider)
            .join(RedemptionProvider, RedemptionProvider.id == Redemption.provider_id)
            .where(
                Redemption.tenant_id == tenant_id,
                Redemption.status == REDEMPTION_STATUS_PENDING,
                Redemption.created_at <= cutoff,
            )
            .order_by(Redemption.created_at)
        )
    ).all()

    scanned = len(pending)
    bumped = 0
    escalated = 0
    audit_rows: list[AuditLog] = []

    for redemption, provider in pending:
        before = _redemption_snapshot(redemption)
        redemption.retry_count += 1
        redemption.last_checked_at = datetime.now(UTC)

        if redemption.retry_count >= provider.max_retries:
            redemption.status = REDEMPTION_STATUS_MANUAL_REVIEW
            action = ACTION_RECON_ESCALATED
            escalated += 1
        else:
            action = ACTION_RECON_SWEPT
            bumped += 1

        after = _redemption_snapshot(redemption)
        audit_rows.append(
            AuditLog(
                tenant_id=tenant_id,
                actor_id=ACTOR_SYSTEM,
                actor_type=ACTOR_SYSTEM,
                action=action,
                entity_type="redemption",
                entity_id=str(redemption.id),
                before_state=before,
                after_state=after,
                note=f"threshold_minutes={threshold_minutes}",
            )
        )

    if audit_rows:
        session.add_all(audit_rows)

    await session.commit()

    return SweepOutcome(
        scanned_count=scanned,
        bumped_count=bumped,
        escalated_count=escalated,
        audit_entry_count=len(audit_rows),
    )


# -----------------------------------------------------------------------------
# Listings
# -----------------------------------------------------------------------------


async def list_pending(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    threshold_minutes: int,
) -> list[PendingItem]:
    """List PENDING redemptions older than the threshold (Pay-PRD-0750)."""
    await _assert_tenant_exists(session, tenant_id)

    cutoff = datetime.now(UTC) - timedelta(minutes=threshold_minutes)
    rows = (
        (
            await session.execute(
                select(Redemption)
                .where(
                    Redemption.tenant_id == tenant_id,
                    Redemption.status == REDEMPTION_STATUS_PENDING,
                    Redemption.created_at <= cutoff,
                )
                .order_by(Redemption.created_at)
            )
        )
        .scalars()
        .all()
    )

    names = await resolve_user_names(
        session, tenant_id=tenant_id, user_ids=[r.user_id for r in rows]
    )
    return [
        PendingItem(
            redemption_id=r.id,
            transaction_id=r.transaction_id,
            user_id=r.user_id,
            user_name=names.get(r.user_id),
            provider_id=r.provider_id,
            points_amount=Decimal(str(r.points_amount)),
            retry_count=r.retry_count,
            last_checked_at=r.last_checked_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def list_manual_review(session: AsyncSession, *, tenant_id: UUID) -> list[ManualReviewItem]:
    """List redemptions awaiting manual operator review (Pay-PRD-0790)."""
    await _assert_tenant_exists(session, tenant_id)

    rows = (
        (
            await session.execute(
                select(Redemption)
                .where(
                    Redemption.tenant_id == tenant_id,
                    Redemption.status == REDEMPTION_STATUS_MANUAL_REVIEW,
                )
                .order_by(Redemption.created_at)
            )
        )
        .scalars()
        .all()
    )

    names = await resolve_user_names(
        session, tenant_id=tenant_id, user_ids=[r.user_id for r in rows]
    )
    return [
        ManualReviewItem(
            redemption_id=r.id,
            transaction_id=r.transaction_id,
            user_id=r.user_id,
            user_name=names.get(r.user_id),
            provider_id=r.provider_id,
            points_amount=Decimal(str(r.points_amount)),
            retry_count=r.retry_count,
            last_checked_at=r.last_checked_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


# -----------------------------------------------------------------------------
# Manual resolve
# -----------------------------------------------------------------------------


async def manually_resolve(
    session: AsyncSession,
    redemption_id: UUID,
    request: ResolveRequest,
    *,
    actor_id: str = "operator-test",
) -> Redemption:
    """Operator terminates a MANUAL_REVIEW redemption (Pay-PRD-0790, 0780, 0770).

    Allowed outcomes:
      - COMPLETED: ledger entries PENDING -> COMPLETED (provider succeeded
        out-of-band, operator confirms).
      - REVERSED: ledger entries PENDING -> REVERSED, points restored.

    Writes an audit_log entry with the before/after state of the redemption.

    Args:
        session: Async DB session.
        redemption_id: Path param.
        request: ResolveRequest with tenant_id, outcome, reason.
        actor_id: For Phase E.1 this is a fixed string; Phase F resolves it
            from the authenticated admin Keycloak ID.

    Returns:
        The updated Redemption.

    Raises:
        RedemptionNotFound: 404 (also for cross-tenant — no existence leak).
        RedemptionNotInManualReview: 409 when status != MANUAL_REVIEW.
        InvalidResolveOutcome: 422 if outcome isn't COMPLETED or REVERSED
            (Pydantic Literal already validates; this is defensive).
    """
    # Find tenant-scoped.
    redemption = (
        await session.execute(
            select(Redemption).where(
                Redemption.id == redemption_id,
                Redemption.tenant_id == request.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if redemption is None:
        raise RedemptionNotFound()
    if redemption.status != REDEMPTION_STATUS_MANUAL_REVIEW:
        raise RedemptionNotInManualReview(redemption.status)

    before = _redemption_snapshot(redemption)

    if request.outcome == "COMPLETED":
        await _flip_entries(
            session,
            redemption.transaction_id,
            cast('Literal["COMPLETED", "REVERSED"]', ENTRY_STATUS_COMPLETED),
        )
        await session.execute(
            update(Transaction)
            .where(Transaction.id == redemption.transaction_id)
            .values(status=TXN_STATUS_COMPLETED)
        )
        redemption.status = REDEMPTION_STATUS_COMPLETED
        redemption.external_reference = request.external_reference
        redemption.completed_at = datetime.now(UTC)
        action = ACTION_RECON_RESOLVED_COMPLETED
    elif request.outcome == "REVERSED":
        await _flip_entries(
            session,
            redemption.transaction_id,
            cast('Literal["COMPLETED", "REVERSED"]', ENTRY_STATUS_REVERSED),
        )
        await session.execute(
            update(Transaction)
            .where(Transaction.id == redemption.transaction_id)
            .values(status=TXN_STATUS_REVERSED)
        )
        # Use REDEMPTION_STATUS_FAILED here to remain consistent with the
        # `fail_redemption` path; future work may add a dedicated MANUAL_REVERSED
        # status if business needs distinguish the two.
        redemption.status = REDEMPTION_STATUS_FAILED
        redemption.failure_reason = request.reason
        action = ACTION_RECON_RESOLVED_REVERSED
    else:
        # Pydantic Literal usually catches this; belt-and-braces.
        raise InvalidResolveOutcome()

    after = _redemption_snapshot(redemption)
    session.add(
        AuditLog(
            tenant_id=request.tenant_id,
            actor_id=actor_id,
            actor_type=ACTOR_ADMIN,
            action=action,
            entity_type="redemption",
            entity_id=str(redemption.id),
            before_state=before,
            after_state=after,
            note=request.reason,
        )
    )

    await session.commit()
    await session.refresh(redemption)
    return redemption


async def _flip_entries(
    session: AsyncSession,
    transaction_id: UUID,
    new_status: Literal["COMPLETED", "REVERSED"],
) -> None:
    """Update a transaction's ledger entries to a new terminal status.

    Per `ledger-invariants.md`, the `status` field on ledger_entries is the
    ONE thing that may change after insert.
    """
    await session.execute(
        update(LedgerEntry)
        .where(LedgerEntry.transaction_id == transaction_id)
        .values(status=new_status)
    )


# -----------------------------------------------------------------------------
# Audit query
# -----------------------------------------------------------------------------


async def query_audit_log(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
) -> list[AuditEntry]:
    """Read-side query over the audit_log table — tenant scoped.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope (required — never query without).
        entity_type: Optional filter (e.g. 'redemption').
        entity_id: Optional filter for a specific entity.
        limit: Hard cap on rows returned. Default 100.

    Returns:
        List of AuditEntry newest first.
    """
    await _assert_tenant_exists(session, tenant_id)

    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit)

    rows = (await session.execute(stmt)).scalars().all()
    return [AuditEntry.model_validate(r) for r in rows]
