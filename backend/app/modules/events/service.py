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

from decimal import Decimal
from uuid import UUID

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hmac import verify_signature
from app.auth.principals import AdminPrincipal
from app.auth.secret_box import decrypt_secret, encrypt_secret
from app.modules.audit.service import record_audit_for_admin, record_audit_for_system
from app.modules.events.normaliser import normalise
from app.modules.events.schemas import (
    FiringOut,
    IngestResponse,
    NormalisedEvent,
    RawExternalEvent,
    SourceRegistrationRequest,
)
from app.modules.rewards.service import issue_cashback_reward, issue_points_reward
from app.modules.rules.evaluator import (
    RuleFiring,
    evaluate_active_rules_for_event,
)
from app.shared.models.rules import REWARD_TYPE_CASHBACK
from app.shared.exceptions import (
    AppHTTPException,
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
from app.shared.tenant_mode import external_events_allowed

# -----------------------------------------------------------------------------
# Source registration
# -----------------------------------------------------------------------------


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject if the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def register_source(
    session: AsyncSession,
    request: SourceRegistrationRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> ExternalEventSource:
    """Idempotent-ish: registers a new source or 409 if source_key is taken.

    Args:
        session: Async DB session.
        request: Validated registration payload.
        admin: Authenticated admin (audit context). Optional for internal callers.
        ip_address: Caller IP (audit context).

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
        # Operator supplies plaintext; persist it Fernet-encrypted (Decision
        # D3). NULL stays NULL — a source may run in unverified test mode.
        shared_secret_encrypted=(
            encrypt_secret(request.shared_secret) if request.shared_secret else None
        ),
    )
    session.add(source)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise SourceKeyAlreadyInUse() from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="event_source.registered",
            entity_type="external_event_source",
            entity_id=str(source.id),
            after_state={
                "source_key": source.source_key,
                "name": source.name,
                "shared_secret_configured": source.shared_secret_encrypted is not None,
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(source)
    return source


async def find_source(session: AsyncSession, source_key: str) -> ExternalEventSource | None:
    """Return the source row for a given source_key, or None."""
    result = await session.execute(
        select(ExternalEventSource).where(ExternalEventSource.source_key == source_key)
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


async def evaluate_and_issue_firings(
    session: AsyncSession, event: NormalisedEvent
) -> list[FiringOut]:
    """Evaluate active rules for an event and issue points for each firing.

    Shared by the external Kafka path (process_external_event) and the internal
    wallet outbox drainer. Does NOT commit — the caller owns the transaction.
    Idempotent via reward_events(user, rule, triggering_event_id).
    """
    firings: list[RuleFiring] = await evaluate_active_rules_for_event(session, event)
    issued: list[FiringOut] = []
    for firing in firings:
        # Dispatch on the rule's configured reward_type. A cashback rule must
        # credit real money to the financial wallet — NOT points. (Both the
        # internal outbox drainer and the external Kafka path share this core, so
        # dispatching here fixes cashback issuance everywhere.) Cashback pays in
        # the qualifying event's currency (the user holds that wallet — they just
        # transacted in it) and, per Pay-PRD-0623, applies NO bonus multiplier.
        if firing.rule.reward_type == REWARD_TYPE_CASHBACK:
            reward_event = await issue_cashback_reward(
                session,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                currency=event.currency,
                amount=firing.reward_value,
                rule_id=firing.rule.id,
                triggering_event_id=event.event_id,
            )
        else:
            # issue_points_reward applies any active bonus multiplier INTERNALLY
            # and credits the MULTIPLIED value to the ledger, returning the
            # RewardEvent whose `reward_value` is that actual post-multiplier
            # credited amount. Report THAT, not the pre-multiplier base
            # (firing.reward_value), so both the external path's `rules_fired`
            # and the internal `earned_points` reflect what truly hit the account.
            reward_event = await issue_points_reward(
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
                # RewardEvent.reward_value is a Numeric column (Decimal at
                # runtime, float-annotated); wrap to satisfy the Decimal field,
                # mirroring the evaluator's own Decimal(rule.reward_value) style.
                reward_value=Decimal(reward_event.reward_value),
            )
        )
    return issued


async def process_external_event(
    session: AsyncSession,
    raw: RawExternalEvent,
    *,
    raw_body: bytes | None = None,
    signature_header: str | None = None,
) -> IngestResponse:
    """The full ingestion pipeline for one external event.

    Steps (matches the Phase C threat model §2 data flow + Phase F.5 HMAC):
      1. Look up the source by source_key.
      2. Reject if source is missing, inactive, or belongs to another tenant.
      3. HMAC verify when source.shared_secret_encrypted is set (Phase F.5).
      4. Dedup via event_ingestion_log: try INSERT; on conflict return DUPLICATE.
      5. Normalise the event.
      6. Evaluate every active rule that could match.
      7. For each firing: issue_points_reward (writes reward_events + ledger).
      8. Commit (the ingestion log row, progress updates, and reward rows).

    Args:
        session: Async DB session.
        raw: Validated RawExternalEvent.
        raw_body: Optional raw request/Kafka payload bytes. REQUIRED when the
            source has a `shared_secret` configured — without these bytes we
            can't compute the HMAC. Callers from trusted admin paths (the
            admin-gated HTTP endpoint) can omit this; HMAC verify is then
            skipped.
        signature_header: Optional `X-Sasai-Signature` value. Same rules
            as `raw_body`.

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

    # 2b. Deployment-mode gate: external Kafka events may issue rewards ONLY for
    #     `rewards`-mode tenants. In `both` mode rewards come from internal wallet
    #     activity; in `wallet` mode there are no rewards. This is enforced in code
    #     here — not merely by which consumer process runs — so an event that slips
    #     into the wrong tenant's stream is rejected and audit-logged, never issued.
    if not await external_events_allowed(session, source.tenant_id):
        await _log_rejected(session, raw, "wrong_mode")
        return IngestResponse(
            outcome="rejected",
            event_id=raw.event_id,
            rejection_reason="wrong_mode",
        )

    # 3. Phase F.5: HMAC verify when source.shared_secret_encrypted is set.
    #    If the source has no secret configured, HMAC is skipped (e.g. for
    #    trusted internal sources or admin-gated test ingestion). If a
    #    secret IS set but the caller didn't supply raw_body + signature, we
    #    reject — silent skip would be a security regression.
    if source.shared_secret_encrypted:
        try:
            source_secret = decrypt_secret(source.shared_secret_encrypted)
        except InvalidToken:
            # Stored secret can't be decrypted (e.g. SECRET_KEY rotated) —
            # unverifiable. Reject rather than silently skipping verification.
            await _log_rejected(session, raw, "integrity_check_failed")
            record_audit_for_system(
                session,
                tenant_id=source.tenant_id,
                actor_id=f"source:{source.source_key}",
                action="event.rejected.integrity_failed",
                entity_type="external_event",
                entity_id=raw.event_id,
                note="shared secret could not be decrypted",
            )
            await session.commit()
            return IngestResponse(
                outcome="rejected",
                event_id=raw.event_id,
                rejection_reason="integrity_check_failed",
            )
        if raw_body is None or signature_header is None:
            await _log_rejected(session, raw, "integrity_check_missing")
            record_audit_for_system(
                session,
                tenant_id=source.tenant_id,
                actor_id=f"source:{source.source_key}",
                action="event.rejected.integrity_failed",
                entity_type="external_event",
                entity_id=raw.event_id,
                note="raw_body or signature header missing",
            )
            await session.commit()
            return IngestResponse(
                outcome="rejected",
                event_id=raw.event_id,
                rejection_reason="integrity_check_missing",
            )
        try:
            verify_signature(
                header=signature_header,
                raw_body=raw_body,
                secret=source_secret,
            )
        except AppHTTPException as exc:
            await _log_rejected(session, raw, "integrity_check_failed")
            record_audit_for_system(
                session,
                tenant_id=source.tenant_id,
                actor_id=f"source:{source.source_key}",
                action="event.rejected.integrity_failed",
                entity_type="external_event",
                entity_id=raw.event_id,
                note=exc.error_code,
            )
            await session.commit()
            return IngestResponse(
                outcome="rejected",
                event_id=raw.event_id,
                rejection_reason="integrity_check_failed",
            )

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

    # 6-7. Evaluate active rules and issue a points reward per firing. Shared
    #      with the internal wallet outbox drainer (DRY). Does not commit.
    issued = await evaluate_and_issue_firings(session, event)

    # 8. Commit the log_row + any progress updates that happened in the
    #    evaluator (milestone counters) + reward rows atomically.
    await session.commit()

    return IngestResponse(
        outcome="processed",
        event_id=raw.event_id,
        rules_fired=issued,
    )


# Suppress unused-import warning for the DUPLICATE constant; kept for clarity
# at the call site if we later distinguish DUPLICATE vs PROCESSED there.
_ = INGESTION_STATUS_DUPLICATE
