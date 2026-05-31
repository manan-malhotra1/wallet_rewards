"""Events service — source registration and event ingestion pipeline.

Phase C delivers:
  - `register_source` — add an external system to `external_event_sources`.
  - `process_external_event` — the full pipeline: validate source, dedupe via
    `event_ingestion_log`, normalise, run rules engine, issue rewards.

The same `process_external_event` is called by:
  - the test HTTP endpoint (`POST /api/v1/events/external`)
  - the Kafka consumer script (`scripts/run_consumer.py`)
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.normaliser import normalise
from app.modules.events.schemas import (
    FiringOut,
    IngestResponse,
    RawExternalEvent,
    SourceRegistrationRequest,
)
from app.modules.rewards.service import issue_points_reward
from app.modules.rules.evaluator import (
    RuleFiring,
    evaluate_active_rules_for_event,
)
from app.shared.exceptions import (
    SourceKeyAlreadyInUse,
    TenantNotFound,
)
from app.shared.models import (
    INGESTION_STATUS_DUPLICATE,
    INGESTION_STATUS_PROCESSED,
    INGESTION_STATUS_REJECTED,
    EventIngestionLog,
    ExternalEventSource,
    Tenant,
)

# -----------------------------------------------------------------------------
# Source registration
# -----------------------------------------------------------------------------


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject if the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def register_source(
    session: AsyncSession, request: SourceRegistrationRequest
) -> ExternalEventSource:
    """Idempotent-ish: registers a new source or 409 if source_key is taken.

    Args:
        session: Async DB session.
        request: Validated registration payload.

    Returns:
        The persisted ExternalEventSource row.

    Raises:
        TenantNotFound: 404 when tenant_id is unknown.
        SourceKeyAlreadyInUse: 409 when source_key is already registered.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    source = ExternalEventSource(
        tenant_id=request.tenant_id,
        name=request.name,
        source_key=request.source_key,
        field_mapping=request.field_mapping,
        shared_secret=request.shared_secret,
    )
    session.add(source)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise SourceKeyAlreadyInUse() from exc
    await session.refresh(source)
    return source


async def find_source(
    session: AsyncSession, source_key: str
) -> ExternalEventSource | None:
    """Return the source row for a given source_key, or None."""
    result = await session.execute(
        select(ExternalEventSource).where(
            ExternalEventSource.source_key == source_key
        )
    )
    return result.scalar_one_or_none()


# -----------------------------------------------------------------------------
# Event ingestion pipeline
# -----------------------------------------------------------------------------


async def _log_rejected(
    session: AsyncSession,
    raw: RawExternalEvent,
    reason: str,
) -> None:
    """Best-effort insert into event_ingestion_log with status REJECTED.

    Rejection happens BEFORE rule processing (e.g. unregistered source,
    tenant mismatch). We attempt to record the rejection — but if the same
    `(source_key, event_id)` was already logged, the unique constraint
    swallows it (no-op).
    """
    try:
        session.add(
            EventIngestionLog(
                external_event_id=raw.event_id,
                source_key=raw.source_key,
                tenant_id=raw.tenant_id,
                status=INGESTION_STATUS_REJECTED,
                failure_reason=reason,
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()


async def process_external_event(
    session: AsyncSession, raw: RawExternalEvent
) -> IngestResponse:
    """The full ingestion pipeline for one external event.

    Steps (matches the Phase C threat model §2 data flow):
      1. Look up the source by source_key.
      2. Reject if source is missing, inactive, or belongs to another tenant.
      3. (Future) HMAC verify when source.shared_secret is set.
      4. Dedup via event_ingestion_log: try INSERT; on conflict return DUPLICATE.
      5. Normalise the event.
      6. Evaluate every active rule that could match.
      7. For each firing: issue_points_reward (writes reward_events + ledger).
      8. Commit (the ingestion log row, progress updates, and reward rows).

    Idempotency at every layer:
      - event_ingestion_log: UNIQUE(source_key, external_event_id)
      - reward_events: UNIQUE(user_id, rule_id, triggering_event_id)
      - ledger: post_transaction uses a deterministic idempotency_key

    Args:
        session: Async DB session.
        raw: Validated RawExternalEvent.

    Returns:
        IngestResponse describing the outcome and any rule firings.
    """
    # 1. Source lookup
    source = await find_source(session, raw.source_key)
    if source is None or source.status != "active":
        await _log_rejected(session, raw, "source_not_registered")
        return IngestResponse(
            outcome="rejected",
            event_id=raw.event_id,
            rejection_reason="source_not_registered",
        )

    # 2. Tenant scope check — source registration is per-tenant.
    if source.tenant_id != raw.tenant_id:
        await _log_rejected(session, raw, "source_tenant_mismatch")
        return IngestResponse(
            outcome="rejected",
            event_id=raw.event_id,
            rejection_reason="source_tenant_mismatch",
        )

    # 3. (Phase F) HMAC verify when source.shared_secret is set.
    #    For Phase C, this is a no-op when no secret is set; if a secret is
    #    set, we still don't enforce — but log that this needs Phase F.

    # 4. Dedup via the unique constraint on event_ingestion_log.
    log_row = EventIngestionLog(
        external_event_id=raw.event_id,
        source_key=raw.source_key,
        tenant_id=raw.tenant_id,
        status=INGESTION_STATUS_PROCESSED,  # tentative; flipped below if needed
    )
    session.add(log_row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        # Already processed — replay; no-op.
        # We still record the duplicate attempt for audit, but only if it
        # doesn't itself collide. Pragmatic: just return.
        return IngestResponse(outcome="duplicate", event_id=raw.event_id)

    # 5. Normalise
    event = normalise(raw, source.field_mapping)

    # 6. Run the rules engine — evaluator returns the list of firings.
    firings: list[RuleFiring] = await evaluate_active_rules_for_event(
        session, event
    )

    # 7. Issue rewards for each firing. Each call uses post_transaction (which
    #    commits) so the log_row + progress updates + ledger entries land
    #    atomically per firing.
    issued: list[FiringOut] = []
    for firing in firings:
        await issue_points_reward(
            session,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            rule=firing.rule,
            triggering_event_id=event.event_id,
            reward_value=firing.reward_value,
        )
        issued.append(
            FiringOut(
                rule_id=firing.rule.id,
                rule_name=firing.rule.name,
                reward_type=firing.rule.reward_type,
                reward_value=firing.reward_value,
            )
        )

    # 8. If no rules fired, we still need to commit the log_row + any progress
    #    updates that happened in the evaluator (milestone counters).
    await session.commit()

    return IngestResponse(
        outcome="processed",
        event_id=raw.event_id,
        rules_fired=issued,
    )


# Suppress unused-import warning for the DUPLICATE constant; kept for clarity
# at the call site if we later distinguish DUPLICATE vs PROCESSED there.
_ = INGESTION_STATUS_DUPLICATE
