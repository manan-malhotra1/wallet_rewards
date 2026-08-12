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

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Whichever tenant is visited FIRST raises -> the other is still recomputed.

    Mirrors the outbox's poison-row isolation: one tenant's failure is
    logged (not re-raised) and the loop continues to the next tenant.

    Deliberately does NOT key the failure off `test_tenant_id`: the
    `_recompute_all` tenant query is `SELECT DISTINCT ... ` with no
    `ORDER BY`, so Postgres is free to plan it as a HashAggregate over the
    two (random) UUIDs — visitation order is not deterministic across runs.
    Failing off `test_tenant_id` specifically would only exercise the
    continue-after-failure branch on the runs where it happens to be
    visited first (~half the time), silently no-op-ing the other half.
    Instead, fail on whichever tenant is attempted FIRST, regardless of
    which one that is, so the isolation branch is exercised every run.

    IDs are captured up front: `_recompute_all`'s rollback for the poisoned
    tenant expires every ORM instance tied to this shared session (rollback
    always expires, unlike commit with `expire_on_commit=False`), so
    `test_tenant.id` / `other_tenant.id` would trigger an out-of-greenlet
    lazy-load if read after the call.
    """
    test_tenant_id, other_tenant_id = test_tenant.id, other_tenant.id
    await _dynamic_segment(db_session, test_tenant_id, name="Loyal")
    await _dynamic_segment(db_session, other_tenant_id, name="Loyal")
    await db_session.commit()

    attempted: list[UUID] = []
    calls: list[UUID] = []

    async def _spy(session: AsyncSession, tenant_id: UUID, **_: object) -> None:
        attempted.append(tenant_id)
        if len(attempted) == 1:
            raise RuntimeError("simulated poisoned-tenant failure")
        calls.append(tenant_id)

    monkeypatch.setattr(tasks, "recompute_tenant", _spy)

    # Must not raise: the poisoned tenant's exception is caught and logged.
    await tasks._recompute_all(db_session)

    # Both tenants were attempted (poison isolation didn't skip the second),
    # and the SECOND one attempted is the one that actually got recomputed.
    assert len(attempted) == 2
    assert set(attempted) == {test_tenant_id, other_tenant_id}
    assert calls == [attempted[1]]


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
