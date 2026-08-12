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
logs and continues — EXCEPT `SoftTimeLimitExceeded`, which logs and
RE-RAISES instead (see "Time limits" below); everything already committed
for prior tenants in the loop stays committed either way.

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
indefinitely. `_recompute_all` explicitly catches
`celery.exceptions.SoftTimeLimitExceeded` (see its docstring) — the soft
limit only DOES anything useful because that catch exists; left uncaught,
Celery's own SIGTERM-based enforcement still applies, but the sweep would
lose the chance to log which tenants got through before the cutoff.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, select
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

    Ordering: STALEST FIRST — tenants are visited by ascending
    `MIN(Segment.last_evaluated_at)` (NULLS FIRST, so a tenant that has
    never been recomputed at all is always visited before one that has).
    This is a no-op today (every tenant gets recomputed every run), but it
    turns any FUTURE fan-out truncation (e.g. a per-run tenant cap, or the
    soft time limit cutting a run short — see below) into round-robin
    fairness instead of the same unlucky tenants at the tail of an
    unordered scan starving indefinitely. Fan-out threshold: once a
    tenant's own count regularly pushes total sweep runtime close to
    `SOFT_TIME_LIMIT`, stop growing this single sweep and instead dispatch
    one `recompute_one_tenant.delay(str(tenant_id))` per tenant (each gets
    its own time budget and failure isolation at the Celery level, not just
    the in-process try/except below).

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
        `SoftTimeLimitExceeded` is the one exception NOT swallowed this way:
        it is caught separately (rollback, `log.warning`, then RE-RAISE) so
        Celery's own soft-limit handling still applies — letting the
        generic `except Exception` below catch it instead would silently
        absorb the timeout and defeat the whole point of setting one (see
        the module docstring's "Time limits" note). Logs one ops-visibility
        summary line at the end (`tenants` attempted, `failed` count) at
        `warning` level if anything failed, `info` otherwise, so a beat run
        that silently poisoned every tenant is still visible in aggregate,
        not just as N buried exception logs.
    """
    stalest_first = (
        select(Segment.tenant_id)
        .where(Segment.criteria.is_not(None))
        .group_by(Segment.tenant_id)
        .order_by(func.min(Segment.last_evaluated_at).nulls_first())
    )
    tenant_ids = (await session.execute(stalest_first)).scalars().all()
    n_succeeded = 0
    n_failed = 0
    for tenant_id in tenant_ids:
        try:
            await recompute_tenant(session, tenant_id)
            await session.commit()
            n_succeeded += 1
        except SoftTimeLimitExceeded:
            # Celery's soft limit fired mid-sweep. Roll back the IN-FLIGHT
            # tenant's uncommitted work — every tenant already counted in
            # n_succeeded/n_failed committed/rolled-back and stays that way
            # — log how far the sweep got, and RE-RAISE. This must reach
            # Celery so the task is recorded as timed-out, not as a clean
            # success with a swallowed error.
            await session.rollback()
            log.warning(
                "segments_recompute_sweep_timed_out",
                tenants=len(tenant_ids),
                succeeded=n_succeeded,
                failed=n_failed,
            )
            raise
        except Exception:
            # Poison-tenant isolation (mirrors outbox row isolation): one
            # tenant's failure — bad criteria, a transient DB hiccup, etc —
            # must not roll back or block every other tenant's recompute.
            await session.rollback()
            n_failed += 1
            log.exception("segment_recompute_tenant_failed", tenant_id=str(tenant_id))
    log_fn = log.warning if n_failed > 0 else log.info
    log_fn("segments_recompute_sweep_done", tenants=len(tenant_ids), failed=n_failed)


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


async def _recompute_one(session: AsyncSession, tenant_id: str) -> None:
    """Recompute one tenant, given its stringified UUID, and commit.

    Split out from `recompute_one_tenant` (the Celery entrypoint) purely so
    the UUID-parse + recompute + commit sequence is unit-testable without a
    broker — mirrors `_recompute_all`'s split for the beat entrypoint.

    Args:
        session: Active async session; committed here on success.
        tenant_id: Stringified UUID (Celery task arguments must be
            JSON-serializable, so callers pass `str(tenant_id)` rather than
            a `UUID` object).

    Side effects:
        Delegates to `evaluator.recompute_tenant` and commits. Does NOT
        catch exceptions — a single manual/API-triggered recompute has no
        sibling tenant to isolate from, so a failure should surface to
        Celery (and, if the caller awaits the AsyncResult, to the caller)
        rather than being silently swallowed.
    """
    await recompute_tenant(session, UUID(tenant_id))
    await session.commit()


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
                await _recompute_one(session, tenant_id)
        finally:
            await engine.dispose()

    asyncio.run(_run())
