"""Drain reward_outbox rows into the rules evaluator.

Two callers: `attempt_immediate` (post-commit fast path, for the mobile
celebration) and `recon_sweep` (Celery beat — durability + reconciliation).
Both go through `evaluate_and_issue_firings`. Double-issue safety comes from
the reward_events UNIQUE index (idx_reward_events_idempotency on
user_id+rule_id+triggering_event_id), NOT from the outbox row lock: the
per-row commit releases the Postgres FOR UPDATE lock, so the immediate path
and a recon sweep can transiently co-touch a row (worst case a spurious
FAILED flip that the next sweep retries — still idempotent at issuance).

Reversal hook (designed, NOT implemented): reward_outbox.transaction_id records
the source transaction. When reversals exist, a reversal txn will emit its own
row and a handler here will look up the original reward_events and post an
append-only claw-back. No claw-back logic is built now.
"""
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import structlog
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.events.schemas import FiringOut, NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.shared.models.rewards import (
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PROCESSED,
    RewardOutbox,
)

log = structlog.get_logger()

# Retry ceiling for the recon sweep — a row that has failed this many times is
# left alone (poison-message guard) and surfaces as a stuck-row alert instead.
MAX_ATTEMPTS = 5
# source_key stamped on internally-generated events so the evaluator/audit can
# tell a wallet-outbox firing apart from an external Kafka event.
INTERNAL_SOURCE_KEY = "internal:wallet"


def _event_from_row(row: RewardOutbox) -> NormalisedEvent:
    """Build the canonical evaluator event from a persisted outbox row.

    The event_id is the source transaction id — this is the idempotency key the
    evaluator writes into reward_events(user, rule, triggering_event_id), so the
    immediate attempt and the recon sweep for the same row can never double-issue.
    """
    return NormalisedEvent(
        event_id=str(row.transaction_id),  # idempotency key for reward_events
        source_key=INTERNAL_SOURCE_KEY,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        transaction_type=row.transaction_type,
        # The column is Numeric (Decimal at runtime) but ORM-annotated float;
        # str() round-trips it into a Decimal without float-repr drift.
        amount=Decimal(str(row.amount)),
        currency=row.currency,
        merchant_id=row.merchant_id,
        timestamp=row.created_at,
    )


async def _drain_row(session: AsyncSession, row: RewardOutbox) -> list[FiringOut]:
    """Issue rewards for one outbox row and mark it processed.

    Args:
        session: Active session; the caller owns the commit.
        row: A pending/retryable outbox row already locked FOR UPDATE.

    Returns:
        The firings issued for this row (possibly empty when no rule matched).

    Side effects:
        Mutates the row to PROCESSED + stamps processed_at. Does NOT commit.
    """
    firings = await evaluate_and_issue_firings(session, _event_from_row(row))
    row.status = OUTBOX_PROCESSED
    row.processed_at = datetime.now(UTC)
    return firings


async def _record_failure(
    session: AsyncSession, row_id: UUID, error: str
) -> None:
    """Persist failure bookkeeping for a row after its drain rolled back.

    A rolled-back session leaves the original `row` instance expired/detached,
    so mutating it would not persist. We re-select the row by id in a fresh
    transaction, bump attempts, record the (truncated) error, mark it FAILED,
    and commit — leaving it for the recon sweep to retry.

    Args:
        session: Active session, already rolled back to a clean state.
        row_id: Primary key of the outbox row that failed to drain.
        error: The exception text; truncated to the column width (500).
    """
    row = await session.get(RewardOutbox, row_id)
    if row is None:  # pragma: no cover - row cannot vanish mid-sweep
        return
    row.attempts += 1
    row.last_error = error[:500]
    row.status = OUTBOX_FAILED
    await session.commit()


async def attempt_immediate(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> list[FiringOut]:
    """Fast-path drain of this user's pending rows, in a fresh session.

    Called by money services AFTER post_transaction commits. Failures are
    swallowed and recorded on the row for the recon sweep to retry — a reward
    hiccup must never surface on the money path.

    Args:
        session_factory: The app's `async_sessionmaker`; a fresh session is
            opened here so this never rides on the money-path transaction.
        tenant_id: Tenant whose pending rows to drain.
        user_id: User whose pending rows to drain.

    Returns:
        Firings issued across all of this user's drained rows (may be empty).

    Side effects:
        Commits each row independently. On failure, rolls back and records the
        error on the row (fail-open — never re-raises to the caller).
    """
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RewardOutbox)
                    .where(
                        RewardOutbox.tenant_id == tenant_id,
                        RewardOutbox.user_id == user_id,
                        RewardOutbox.status == OUTBOX_PENDING,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        all_firings: list[FiringOut] = []
        for row in rows:
            row_id = row.id  # capture before any rollback expires the instance
            try:
                firings = await _drain_row(session, row)
                await session.commit()
                all_firings.extend(firings)
            except Exception as exc:  # fail-open: recon sweep retries the row
                # The recovery itself (rollback + failure commit) can ALSO raise
                # — e.g. a broken connection, the very fault that tripped the
                # drain. attempt_immediate runs AFTER the wallet txn committed,
                # so an escape here would surface a reward hiccup on the money
                # path. Swallow the recovery too: the row stays PENDING and the
                # recon sweep re-drains it idempotently.
                try:
                    await session.rollback()
                    await _record_failure(session, row_id, str(exc))
                except Exception:  # recovery must not escape onto the money path
                    log.exception(
                        "reward_outbox_recovery_failed",
                        outbox_id=str(row_id),
                        tenant_id=str(tenant_id),
                        user_id=str(user_id),
                    )
            # Loop continues regardless; attempt_immediate always returns normally.
        return all_firings


async def recon_sweep_async(
    session_factory: async_sessionmaker[AsyncSession], *, batch: int = 100
) -> int:
    """Drain up to `batch` pending/retryable-failed rows across all tenants.

    The reconciliation: any reward missed by the immediate attempt (crash,
    transient error) is picked up here. Rows past `MAX_ATTEMPTS` are skipped as
    poison messages and left for a stuck-row alert.

    Args:
        session_factory: The app's `async_sessionmaker`; opens one session for
            the whole batch.
        batch: Max rows to claim this sweep (oldest first).

    Returns:
        Count of rows successfully processed this sweep.

    Side effects:
        Commits per row. On failure, rolls back and records the error on the row.
    """
    processed = 0
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RewardOutbox)
                    .where(
                        RewardOutbox.status.in_((OUTBOX_PENDING, OUTBOX_FAILED)),
                        RewardOutbox.attempts < MAX_ATTEMPTS,
                    )
                    .order_by(RewardOutbox.created_at)
                    .limit(batch)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row_id = row.id  # capture before any rollback expires the instance
            try:
                await _drain_row(session, row)
                await session.commit()
                processed += 1
            except Exception as exc:  # fail-open: retried on the next sweep
                await session.rollback()
                await _record_failure(session, row_id, str(exc))
    return processed


# celery's @shared_task is untyped, so under mypy --strict it flags the wrapped
# function as untyped; the ignore is scoped to that one decorator interaction.
@shared_task(name="rewards.recon_sweep")  # type: ignore[untyped-decorator]
def recon_sweep() -> int:
    """Celery entrypoint for the reward-outbox reconciliation sweep.

    Scheduled every 60s by Celery beat (see app/celery_app.py). Returns the
    number of rows processed.

    Each beat runs on a FRESH event loop via `asyncio.run`. We therefore build
    a DEDICATED asyncpg engine (NullPool) per run and dispose it in `finally`,
    rather than reusing the module-level `SessionLocal`: that shared engine's
    pooled connections bind to the first loop, so the second beat (new loop)
    would raise "Event loop is closed" and recon would silently die after one
    run. A per-run NullPool engine has no connection to carry across loops.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings

    async def _run() -> int:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            return await recon_sweep_async(factory)
        finally:
            await engine.dispose()

    return asyncio.run(_run())
