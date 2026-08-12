"""Celery tasks for segment recomputation (beat: hourly; manual: API enqueue).

Two entrypoints, mirroring `app/modules/rewards/outbox.py`'s task shape:
`recompute_all_segments` (Celery beat — periodic refresh across every
tenant) and `recompute_one_tenant` (manual/API-triggered enqueue for a
single tenant, e.g. right after an admin edits a segment's criteria). Both
bootstrap a dedicated per-run async engine/session exactly like
`rewards.recon_sweep` does — see that task's docstring for why a shared
module-level engine can't be reused across Celery beat's `asyncio.run` calls.

Commit granularity: `_recompute_all` commits ONCE PER TENANT rather than once
for the whole batch. This trades a little more round-trip chatter for
poison-tenant isolation — mirroring the outbox's per-row commit pattern (see
that module's docstring): one tenant with corrupt/unparseable criteria (or
any other failure) must not roll back every other tenant's freshly computed
membership. Each tenant's recompute is wrapped in its own try/except that
logs and continues.

Time limits: `evaluator.recompute_tenant` takes a blocking `FOR UPDATE` on
the tenant's dynamic segment rows for the whole recompute (see that module's
concurrency note), so an unbounded run risks piling up overlapping/queued
work under Celery beat's fixed interval. Both tasks set
`soft_time_limit=540, time_limit=600`. `rewards/outbox.py`'s recon_sweep sets
no time limit at all; segment recompute needs one because its per-tenant
metric maps are memory-heavier — `evaluator._compute_all_metric_keys`'s
docstring notes ~22MB per 100k-user metric map, and a tenant with many
segments x many distinct metric/window combinations can hold several such
maps at once. A hard ceiling bounds worst-case worker memory and lets Celery
reclaim a stuck run instead of letting it wedge the beat schedule
indefinitely.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments.evaluator import recompute_tenant
from app.shared.models import Segment

log = structlog.get_logger()

# Celery time limits (seconds) for both segment-recompute tasks. See the
# module docstring's "Time limits" note: the evaluator's per-tenant FOR
# UPDATE lock plus its memory footprint mean a run must not be allowed to
# run indefinitely. soft_time_limit raises a catchable SoftTimeLimitExceeded
# first; time_limit is the hard SIGKILL backstop.
SOFT_TIME_LIMIT = 540
TIME_LIMIT = 600


async def _recompute_all(session: AsyncSession) -> None:
    """Recompute every tenant that has at least one dynamic segment.

    Args:
        session: Active async session. Reused across tenants but committed
            (or rolled back) independently per tenant — see the module
            docstring's "Commit granularity" note.

    Side effects:
        For each tenant with dynamic segments, delegates to
        `evaluator.recompute_tenant` (inserts/deletes `user_segments`,
        stamps `last_evaluated_at`, writes audit rows) and commits. A
        tenant whose recompute raises is rolled back, logged, and skipped —
        it never prevents the remaining tenants from being recomputed.
    """
    tenant_ids = (
        (
            await session.execute(
                select(Segment.tenant_id).where(Segment.criteria.is_not(None)).distinct()
            )
        )
        .scalars()
        .all()
    )
    for tenant_id in tenant_ids:
        try:
            await recompute_tenant(session, tenant_id)
            await session.commit()
        except Exception:
            # Poison-tenant isolation (mirrors outbox row isolation): one
            # tenant's failure — bad criteria, a transient DB hiccup, etc —
            # must not roll back or block every other tenant's recompute.
            await session.rollback()
            log.exception("segment_recompute_tenant_failed", tenant_id=str(tenant_id))


# celery's @shared_task is untyped, so under mypy --strict it flags the wrapped
# function as untyped; the ignore is scoped to that one decorator interaction
# (see rewards/outbox.py's recon_sweep for the same pattern).
@shared_task(  # type: ignore[untyped-decorator]
    name="segments.recompute_all", soft_time_limit=SOFT_TIME_LIMIT, time_limit=TIME_LIMIT
)
def recompute_all_segments() -> None:
    """Celery entrypoint: recompute dynamic segment membership for every tenant.

    Scheduled by Celery beat (see `app/celery_app.py`, default hourly,
    overridable via `SEGMENT_RECOMPUTE_INTERVAL_SECS`). Each beat run gets a
    FRESH event loop via `asyncio.run`, so — exactly like
    `rewards.recon_sweep` — this builds a dedicated NullPool asyncpg engine
    per run and disposes it in `finally`, rather than reusing a module-level
    session factory bound to a possibly-closed event loop.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings

    async def _run() -> None:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                await _recompute_all(session)
        finally:
            await engine.dispose()

    asyncio.run(_run())


@shared_task(  # type: ignore[untyped-decorator]
    name="segments.recompute_tenant", soft_time_limit=SOFT_TIME_LIMIT, time_limit=TIME_LIMIT
)
def recompute_one_tenant(tenant_id: str) -> None:
    """Celery entrypoint: recompute dynamic segment membership for one tenant.

    Intended for manual/API-triggered enqueue (e.g. an admin edits a
    segment's criteria and wants membership refreshed sooner than the next
    hourly beat) rather than the periodic schedule. See
    `recompute_all_segments` for the event-loop/engine bootstrap rationale —
    identical here.

    Args:
        tenant_id: Stringified UUID of the tenant to recompute. Celery task
            arguments must be JSON-serializable, so the caller passes
            `str(tenant_id)` rather than a `UUID` object.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings

    async def _run() -> None:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                await recompute_tenant(session, UUID(tenant_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())
