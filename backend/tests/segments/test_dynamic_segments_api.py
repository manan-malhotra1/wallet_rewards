"""Dynamic segment API — criteria create/patch, vocabulary, preview, recompute (Task 7)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments import tasks as tasks_module
from app.modules.segments.criteria import ALL_METRICS
from app.shared.models import AuditLog, Segment, Tenant, User

# A minimal, always-satisfiable criteria document — every user is at least
# zero days old, so `account_age_days gte 0` matches everyone.
_ANY_USER_CRITERIA = {
    "v": 1,
    "op": "AND",
    "conditions": [{"metric": "account_age_days", "gte": 0}],
}

# A criteria document referencing a metric outside the DSL vocabulary —
# every "invalid criteria" test reuses this shape.
_INVALID_CRITERIA = {
    "v": 1,
    "op": "AND",
    "conditions": [{"metric": "shoe_size", "gte": 1}],
}


# -----------------------------------------------------------------------------
# Create — dynamic segments
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_dynamic_segment_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify creating a segment with group_id + priority + criteria returns the full shape."""
    resp = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "dynamic-vips",
            "priority": 3,
            "criteria": _ANY_USER_CRITERIA,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["group_id"] == test_segment_group
    assert body["priority"] == 3
    assert body["criteria"]["op"] == "AND"
    assert body["criteria"]["conditions"][0]["metric"] == "account_age_days"
    assert body["is_system"] is False
    assert body["last_evaluated_at"] is None


@pytest.mark.asyncio
async def test_create_segment_invalid_criteria_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an unknown metric name in criteria is rejected by validation."""
    resp = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "bad-criteria",
            "criteria": _INVALID_CRITERIA,
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_segment_cross_tenant_group_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_segment_group: Callable[..., Awaitable[str]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a group_id belonging to another tenant 404s (no cross-tenant existence leak)."""
    foreign_group_id = await make_segment_group(other_tenant.id)

    resp = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": foreign_group_id,
            "name": "cross-tenant-group",
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "segment_group_not_found"


# -----------------------------------------------------------------------------
# GET /segments/metrics
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_metrics_vocabulary(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the metric vocabulary matches criteria.ALL_METRICS with correct filter flags."""
    resp = await async_client.get("/api/v1/segments/metrics", headers=admin_auth_header)
    assert resp.status_code == 200
    body = resp.json()

    names = [m["name"] for m in body]
    assert names == sorted(ALL_METRICS)

    by_name = {m["name"]: m for m in body}
    assert by_name["txn_count"]["supports_txn_type"] is True
    assert by_name["txn_count"]["supports_window"] is True
    assert by_name["wallet_balance"]["supports_txn_type"] is False
    assert by_name["wallet_balance"]["supports_window"] is False


# -----------------------------------------------------------------------------
# POST /segments/preview
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_criteria_returns_match_count(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify preview counts at least the always-satisfiable seeded test user."""
    resp = await async_client.post(
        "/api/v1/segments/preview",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "criteria": _ANY_USER_CRITERIA},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["match_count"] >= 1


@pytest.mark.asyncio
async def test_preview_requires_auth_401(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Verify preview cannot be called without a valid admin token."""
    resp = await async_client.post(
        "/api/v1/segments/preview",
        headers={"Authorization": ""},
        json={"tenant_id": str(test_tenant.id), "criteria": _ANY_USER_CRITERIA},
    )
    assert resp.status_code == 401


# -----------------------------------------------------------------------------
# POST /segments/recompute
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recompute_enqueues_task_with_tenant_id(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify POST /segments/recompute enqueues the Celery task with str(tenant_id)."""
    calls: list[str] = []

    def _spy(tenant_id_str: str) -> None:
        calls.append(tenant_id_str)

    monkeypatch.setattr(tasks_module.recompute_one_tenant, "delay", _spy)

    resp = await async_client.post(
        "/api/v1/segments/recompute",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"status": "enqueued"}
    assert calls == [str(test_tenant.id)]


# -----------------------------------------------------------------------------
# PATCH /segments/{segment_id}
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_segment_updates_criteria_and_priority_and_audits(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify PATCH can set criteria + priority on an existing (static) segment and audits it."""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "to-go-dynamic",
        },
    )
    seg_id = create.json()["id"]
    assert create.json()["criteria"] is None
    assert create.json()["priority"] == 0

    resp = await async_client.patch(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"priority": 5, "criteria": _ANY_USER_CRITERIA},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["priority"] == 5
    assert body["criteria"]["conditions"][0]["metric"] == "account_age_days"

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "segment.updated",
                AuditLog.entity_id == seg_id,
            )
        )
    ).scalar_one_or_none()
    assert audit_row is not None
    assert audit_row.before_state is not None and audit_row.before_state["priority"] == 0
    assert audit_row.after_state is not None and audit_row.after_state["priority"] == 5


@pytest.mark.asyncio
async def test_patch_segment_moves_group_for_non_system_segment(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_segment_group: Callable[..., Awaitable[str]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a non-system segment can be moved to a different group via PATCH."""
    group_a = await make_segment_group(test_tenant.id)
    group_b = await make_segment_group(test_tenant.id)

    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "group_id": group_a, "name": "movable"},
    )
    seg_id = create.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"group_id": group_b},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["group_id"] == group_b


@pytest.mark.asyncio
async def test_patch_segment_group_move_blocked_for_system_segment_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_segment_group: Callable[..., Awaitable[str]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a system-seeded segment cannot be moved to another group.

    Created directly via the ORM (not the create API, which has no way to
    set `is_system`) — mirrors how `test_group_api.py` builds a system-seeded
    row for its own protected-delete test.
    """
    group_a = await make_segment_group(test_tenant.id)
    group_b = await make_segment_group(test_tenant.id)

    segment = Segment(tenant_id=test_tenant.id, group_id=UUID(group_a), name="Gold", is_system=True)
    db_session.add(segment)
    await db_session.commit()
    await db_session.refresh(segment)

    resp = await async_client.patch(
        f"/api/v1/segments/{segment.id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"group_id": group_b},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "segment_protected"


@pytest.mark.asyncio
async def test_patch_segment_clear_criteria_turns_dynamic_static(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify clear_criteria=True nulls out criteria in the response AND persists SQL NULL.

    The SQL-NULL check re-queries via a session that has never loaded this
    row before (`db_session` here only ever touches it after the PATCH), so
    it can't be fooled by a stale, never-refreshed identity-map object.
    """
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "was-dynamic",
            "criteria": _ANY_USER_CRITERIA,
        },
    )
    seg_id = create.json()["id"]
    assert create.json()["criteria"] is not None

    resp = await async_client.patch(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"clear_criteria": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["criteria"] is None

    persisted = (
        await db_session.execute(select(Segment).where(Segment.id == UUID(seg_id)))
    ).scalar_one()
    assert persisted.criteria is None


@pytest.mark.asyncio
async def test_patch_segment_invalid_criteria_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify PATCHing an unknown metric into criteria is rejected by validation."""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "will-reject-patch",
        },
    )
    seg_id = create.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"criteria": _INVALID_CRITERIA},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_segment_cross_tenant_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify PATCHing a segment scoped to another tenant 404s."""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "belongs-to-test-tenant",
        },
    )
    seg_id = create.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(other_tenant.id)},
        json={"priority": 7},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "segment_not_found"


@pytest.mark.asyncio
async def test_patch_segment_unknown_id_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify PATCHing a nonexistent segment id 404s."""
    resp = await async_client.patch(
        f"/api/v1/segments/{uuid4()}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"priority": 1},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "segment_not_found"
