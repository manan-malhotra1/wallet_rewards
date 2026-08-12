"""Tests for the Celery segment-recompute tasks (Task 5).

Exercises the async helper (`tasks._recompute_all`) directly rather than the
`@shared_task`-wrapped Celery entrypoints — there's no broker running in the
test suite, and the entrypoints are themselves a thin `asyncio.run` +
engine-bootstrap shell around this helper (see `outbox.py`'s twin for the
same split). `db_session` here commits for real against the test DB (see
`tests/conftest.py` — TRUNCATE-between-tests, not SAVEPOINT-rollback), so
`_recompute_all`'s per-tenant `session.commit()` is safe to exercise as-is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from app import celery_app as celery_app_module
from app.modules.segments import tasks
from app.shared.models import Segment, SegmentGroup, Tenant


async def _dynamic_segment(db_session: AsyncSession, tenant_id: UUID, *, name: str) -> Segment:
    """Create + flush a minimal dynamic (criteria-non-null) segment for a tenant.

    The group and criteria content don't matter for these tests — only that
    `Segment.criteria IS NOT NULL`, which is what `_recompute_all`'s tenant
    query filters on.
    """
    group = SegmentGroup(tenant_id=tenant_id, name=f"group-{name}")
    db_session.add(group)
    await db_session.flush()
    segment = Segment(
        tenant_id=tenant_id,
        group_id=group.id,
        name=name,
        criteria={"v": 1, "op": "AND", "conditions": [{"metric": "txn_count", "gte": 1}]},
    )
    db_session.add(segment)
    await db_session.flush()
    return segment


@pytest.mark.asyncio
async def test_recompute_all_skips_when_no_dynamic_segments(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No tenant has a dynamic segment -> `recompute_tenant` is never called."""
    calls: list[UUID] = []

    async def _spy(session: AsyncSession, tenant_id: UUID, **_: object) -> None:
        calls.append(tenant_id)

    monkeypatch.setattr(tasks, "recompute_tenant", _spy)
    await tasks._recompute_all(db_session)

    assert calls == []


@pytest.mark.asyncio
async def test_recompute_all_calls_each_tenant_with_dynamic_segments(
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two tenants each have a dynamic segment -> both are recomputed exactly once."""
    test_tenant_id, other_tenant_id = test_tenant.id, other_tenant.id
    await _dynamic_segment(db_session, test_tenant_id, name="Loyal")
    await _dynamic_segment(db_session, other_tenant_id, name="Loyal")
    await db_session.commit()

    calls: list[UUID] = []

    async def _spy(session: AsyncSession, tenant_id: UUID, **_: object) -> None:
        calls.append(tenant_id)

    monkeypatch.setattr(tasks, "recompute_tenant", _spy)
    await tasks._recompute_all(db_session)

    # Order isn't guaranteed by the DISTINCT query, so compare as a set, and
    # separately confirm no tenant was recomputed more than once.
    assert len(calls) == 2
    assert set(calls) == {test_tenant_id, other_tenant_id}


@pytest.mark.asyncio
async def test_recompute_all_isolates_a_poisoned_tenant(
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whichever tenant is visited FIRST raises AFTER a partial write -> that
    write is rolled back, while the survivor's own write commits for real.

    Mirrors the outbox's poison-row isolation: one tenant's failure is
    logged (not re-raised) and the loop continues to the next tenant. This
    proves TRANSACTIONAL isolation, not just control flow: both spies
    perform a real write (stamping their own tenant's `Segment.
    last_evaluated_at`) before the first-attempted one raises. Asserting
    only on the Python call list (as an earlier version of this test did)
    would pass even if `_recompute_all`'s `session.rollback()` were a no-op
    that merely swallowed the exception without undoing the DB write — only
    re-querying the row proves the rollback actually happened.

    Deliberately does NOT key the failure off `test_tenant_id`: the
    `_recompute_all` tenant query has no tenant-id-based `ORDER BY` (it
    orders by staleness, and both segments start equally stale/NULL), so
    which tenant is visited first isn't pinned to a specific fixture.
    Failing off `test_tenant_id` specifically would only exercise the
    continue-after-failure branch on the runs where it happens to be
    visited first. Instead, fail on whichever tenant is attempted FIRST,
    regardless of which one that is, so the isolation branch — and the
    rollback-really-happened assertion below — is exercised every run.

    IDs are captured up front: `_recompute_all`'s rollback for the poisoned
    tenant expires every ORM instance tied to this shared session (rollback
    always expires, unlike commit with `expire_on_commit=False`), so
    reading `test_tenant.id` / `other_tenant.id`, or the `Segment` objects'
    attributes, after the call would trigger an out-of-greenlet lazy-load —
    hence the fresh `select(...)` re-queries below instead of attribute
    access on the original ORM instances.
    """
    test_tenant_id, other_tenant_id = test_tenant.id, other_tenant.id
    seg_a = await _dynamic_segment(db_session, test_tenant_id, name="A")
    seg_b = await _dynamic_segment(db_session, other_tenant_id, name="B")
    segment_id_by_tenant = {test_tenant_id: seg_a.id, other_tenant_id: seg_b.id}
    await db_session.commit()

    attempted: list[UUID] = []
    stamp = datetime.now(UTC)

    async def _spy(session: AsyncSession, tenant_id: UUID, **_: object) -> None:
        attempted.append(tenant_id)
        # Real write, mirroring what evaluator.recompute_tenant actually
        # does (stamps Segment.last_evaluated_at) — this is the write whose
        # fate (rolled back vs. committed) the assertions below check.
        segment = await session.get(Segment, segment_id_by_tenant[tenant_id])
        assert segment is not None
        segment.last_evaluated_at = stamp
        if len(attempted) == 1:
            raise RuntimeError("simulated poisoned-tenant failure after a partial write")

    monkeypatch.setattr(tasks, "recompute_tenant", _spy)

    # Must not raise: the poisoned tenant's exception is caught and logged.
    await tasks._recompute_all(db_session)

    assert len(attempted) == 2
    assert set(attempted) == {test_tenant_id, other_tenant_id}
    poisoned_id, survivor_id = attempted[0], attempted[1]

    poisoned_stamp = (
        await db_session.execute(
            select(Segment.last_evaluated_at).where(Segment.id == segment_id_by_tenant[poisoned_id])
        )
    ).scalar_one()
    survivor_stamp = (
        await db_session.execute(
            select(Segment.last_evaluated_at).where(Segment.id == segment_id_by_tenant[survivor_id])
        )
    ).scalar_one()

    # The poisoned tenant's in-flight write never committed (rolled back);
    # the survivor's write is durably persisted.
    assert poisoned_stamp is None
    assert survivor_stamp == stamp


@pytest.mark.asyncio
async def test_recompute_one_forwards_parsed_uuid_and_commits(
    db_session: AsyncSession, test_tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_recompute_one` parses the stringified UUID, forwards a real `UUID`,
    and commits — not just flushes.

    The spy performs a real write (stamps `Segment.last_evaluated_at`)
    rather than a no-op, so a fresh re-query after `_recompute_one` returns
    proves the session was actually COMMITTED (a flush-only bug would still
    show the value via `expire_on_commit=False` on the SAME session/object,
    but a fresh `select(...)` — as used here — only sees committed data).
    """
    test_tenant_id = test_tenant.id
    segment = await _dynamic_segment(db_session, test_tenant_id, name="Loyal")
    segment_id = segment.id
    await db_session.commit()

    forwarded: list[UUID] = []
    stamp = datetime.now(UTC)

    async def _spy(session: AsyncSession, tenant_id: UUID, **_: object) -> None:
        forwarded.append(tenant_id)
        seg = await session.get(Segment, segment_id)
        assert seg is not None
        seg.last_evaluated_at = stamp

    monkeypatch.setattr(tasks, "recompute_tenant", _spy)
    await tasks._recompute_one(db_session, str(test_tenant_id))

    # Forwarded a real UUID (not the raw string) matching the tenant.
    assert forwarded == [test_tenant_id]
    assert isinstance(forwarded[0], UUID)

    persisted = (
        await db_session.execute(select(Segment.last_evaluated_at).where(Segment.id == segment_id))
    ).scalar_one()
    assert persisted == stamp


@pytest.mark.asyncio
async def test_recompute_all_summary_log_level_reflects_failures(
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sweep-summary log is `warning` when any tenant failed, `info` otherwise.

    Uses `structlog.testing.capture_logs()`, not `caplog` — this repo's
    structlog isn't wired through stdlib `logging`, so `caplog` sees
    nothing (see `test_evaluator.py`'s note on the same limitation).
    `capture_logs()` needs no configuration wiring, so asserting on the log
    line directly (rather than only its observable side effects) is cheap
    here — unlike the evaluator's poison-log case, this one didn't need
    skipping.
    """
    test_tenant_id, other_tenant_id = test_tenant.id, other_tenant.id
    await _dynamic_segment(db_session, test_tenant_id, name="Loyal")
    await db_session.commit()

    async def _ok(session: AsyncSession, tenant_id: UUID, **_: object) -> None:
        return None

    monkeypatch.setattr(tasks, "recompute_tenant", _ok)
    with capture_logs() as clean_run_logs:
        await tasks._recompute_all(db_session)
    summary = next(e for e in clean_run_logs if e["event"] == "segments_recompute_sweep_done")
    assert summary["log_level"] == "info"
    assert summary["failed"] == 0

    await _dynamic_segment(db_session, other_tenant_id, name="Loyal")
    await db_session.commit()

    async def _one_fails(session: AsyncSession, tenant_id: UUID, **_: object) -> None:
        if tenant_id == other_tenant_id:
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(tasks, "recompute_tenant", _one_fails)
    with capture_logs() as failing_run_logs:
        await tasks._recompute_all(db_session)
    summary = next(e for e in failing_run_logs if e["event"] == "segments_recompute_sweep_done")
    assert summary["log_level"] == "warning"
    assert summary["failed"] == 1


def test_beat_schedule_registers_segments_recompute() -> None:
    """`celery_app` wires the hourly segment recompute into beat + include.

    Asserts the schedule reads LIVE from `settings.SEGMENT_RECOMPUTE_INTERVAL_SECS`
    (not just that SOME float is present) — a hard-coded `3600.0` in
    `celery_app.py` would otherwise still pass this test.
    """
    from app.config import settings

    beat_entry = celery_app_module.celery_app.conf.beat_schedule["segments-recompute"]
    assert beat_entry["task"] == "segments.recompute_all"
    assert beat_entry["schedule"] == float(settings.SEGMENT_RECOMPUTE_INTERVAL_SECS)
    assert "app.modules.segments.tasks" in celery_app_module.celery_app.conf.include


def test_shared_tasks_bind_to_configured_celery_app() -> None:
    """Both `@shared_task` entrypoints resolve against `app.celery_app`, not
    Celery's bare default app.

    Regression guard for the `app.main` import-order fix (see that module's
    comment): a `@shared_task`-decorated function binds to whichever Celery
    app was "current" at decoration time. `celery -A app.celery_app
    worker/beat` always gets this for free (it IS the entry module), but the
    `uvicorn app.main:app` web process only does if `app.celery_app` is
    imported before any router that transitively pulls in a `@shared_task`
    module — without that import, `.delay()` calls from the web process
    silently bind to a broker-less default app and raise a connection error
    instead of reaching Redis (exactly the bug the Task 12 live smoke test
    caught: `POST /api/v1/segments/recompute` 500ing). Asserting `.app is
    celery_app` here catches a regression of that import ordering without
    needing a running worker or broker.
    """
    from app.celery_app import celery_app

    assert tasks.recompute_one_tenant.app is celery_app
    assert tasks.recompute_all_segments.app is celery_app
