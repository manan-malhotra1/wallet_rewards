"""GET /segments/member-counts — per-segment and per-group membership aggregates.

Covers the happy path (manual/criteria split + group-level distinct-user
dedup), tenant isolation, and an empty tenant. See
`app.modules.segments.group_service.member_counts` for the two grouped
queries this endpoint is a thin passthrough onto.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, UserSegment
from app.shared.models.segments import USER_SEGMENT_SOURCE_CRITERIA, USER_SEGMENT_SOURCE_MANUAL


async def _make_segment(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
    *,
    tenant_id: Any,
    group_id: str,
    name: str,
) -> str:
    """POST a segment via the public API, return its id."""
    resp = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": str(tenant_id), "group_id": group_id, "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_member_counts_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_segment_group: Callable[..., Awaitable[str]],
    user_factory: Callable[..., Awaitable[Any]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify per-segment total/manual/criteria splits and per-group distinct-user dedup.

    Two segments (seg1, seg2) share group_a; a third (seg3) lives alone in
    group_b. `user_a` is manually assigned to BOTH seg1 and seg2 — proving
    group_a's `distinct_users` counts them once (DISTINCT), not twice, even
    though the per-segment totals count `user_a` in each segment's own row.
    """
    group_a = await make_segment_group(test_tenant.id, "Group A")
    group_b = await make_segment_group(test_tenant.id, "Group B")

    seg1 = await _make_segment(
        async_client, admin_auth_header, tenant_id=test_tenant.id, group_id=group_a, name="seg1"
    )
    seg2 = await _make_segment(
        async_client, admin_auth_header, tenant_id=test_tenant.id, group_id=group_a, name="seg2"
    )
    seg3 = await _make_segment(
        async_client, admin_auth_header, tenant_id=test_tenant.id, group_id=group_b, name="seg3"
    )

    user_a = await user_factory(test_tenant)
    user_b = await user_factory(test_tenant)
    user_c = await user_factory(test_tenant)
    user_d = await user_factory(test_tenant)

    # seg1 (group_a): user_a manual, user_b criteria -> total 2, manual 1, criteria 1
    db_session.add(
        UserSegment(user_id=user_a.id, segment_id=seg1, source=USER_SEGMENT_SOURCE_MANUAL)
    )
    db_session.add(
        UserSegment(user_id=user_b.id, segment_id=seg1, source=USER_SEGMENT_SOURCE_CRITERIA)
    )
    # seg2 (group_a): user_a manual too -> total 1, manual 1, criteria 0.
    # Proves group_a's distinct_users still dedupes user_a to 1, not counted
    # again for being in a second segment of the same group.
    db_session.add(
        UserSegment(user_id=user_a.id, segment_id=seg2, source=USER_SEGMENT_SOURCE_MANUAL)
    )
    # seg3 (group_b): user_c manual, user_d criteria -> total 2, manual 1, criteria 1
    db_session.add(
        UserSegment(user_id=user_c.id, segment_id=seg3, source=USER_SEGMENT_SOURCE_MANUAL)
    )
    db_session.add(
        UserSegment(user_id=user_d.id, segment_id=seg3, source=USER_SEGMENT_SOURCE_CRITERIA)
    )
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/segments/member-counts",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    segments_by_id = {s["segment_id"]: s for s in body["segments"]}
    assert segments_by_id[seg1] == {"segment_id": seg1, "total": 2, "manual": 1, "criteria": 1}
    assert segments_by_id[seg2] == {"segment_id": seg2, "total": 1, "manual": 1, "criteria": 0}
    assert segments_by_id[seg3] == {"segment_id": seg3, "total": 2, "manual": 1, "criteria": 1}

    groups_by_id = {g["group_id"]: g for g in body["groups"]}
    # group_a holds user_a (in both its segments, counted once) + user_b = 2.
    assert groups_by_id[group_a]["distinct_users"] == 2
    # group_b holds user_c + user_d = 2.
    assert groups_by_id[group_b]["distinct_users"] == 2


@pytest.mark.asyncio
async def test_member_counts_tenant_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_segment_group: Callable[..., Awaitable[str]],
    user_factory: Callable[..., Awaitable[Any]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify one tenant's memberships never leak into another tenant's counts."""
    group_mine = await make_segment_group(test_tenant.id, "Mine")
    group_theirs = await make_segment_group(other_tenant.id, "Theirs")

    seg_mine = await _make_segment(
        async_client, admin_auth_header, tenant_id=test_tenant.id, group_id=group_mine, name="mine"
    )
    seg_theirs = await _make_segment(
        async_client,
        admin_auth_header,
        tenant_id=other_tenant.id,
        group_id=group_theirs,
        name="theirs",
    )

    user_mine = await user_factory(test_tenant)
    user_theirs = await user_factory(other_tenant)

    db_session.add(
        UserSegment(user_id=user_mine.id, segment_id=seg_mine, source=USER_SEGMENT_SOURCE_MANUAL)
    )
    db_session.add(
        UserSegment(
            user_id=user_theirs.id, segment_id=seg_theirs, source=USER_SEGMENT_SOURCE_MANUAL
        )
    )
    await db_session.commit()

    mine_resp = await async_client.get(
        "/api/v1/segments/member-counts",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert mine_resp.status_code == 200
    mine_body = mine_resp.json()
    assert [s["segment_id"] for s in mine_body["segments"]] == [seg_mine]
    assert [g["group_id"] for g in mine_body["groups"]] == [group_mine]

    theirs_resp = await async_client.get(
        "/api/v1/segments/member-counts",
        headers=admin_auth_header,
        params={"tenant_id": str(other_tenant.id)},
    )
    assert theirs_resp.status_code == 200
    theirs_body = theirs_resp.json()
    assert [s["segment_id"] for s in theirs_body["segments"]] == [seg_theirs]
    assert [g["group_id"] for g in theirs_body["groups"]] == [group_theirs]


@pytest.mark.asyncio
async def test_member_counts_empty_tenant_returns_empty_arrays(
    async_client: AsyncClient,
    tenant_factory: Callable[..., Awaitable[Tenant]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a tenant with no groups/segments/memberships returns empty arrays, not a 404."""
    empty_tenant = await tenant_factory(business_type="both")

    resp = await async_client.get(
        "/api/v1/segments/member-counts",
        headers=admin_auth_header,
        params={"tenant_id": str(empty_tenant.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"segments": [], "groups": []}


@pytest.mark.asyncio
async def test_member_counts_unknown_tenant_returns_empty_arrays(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a nonexistent tenant_id also returns empty arrays (read-only aggregate, no 404)."""
    resp = await async_client.get(
        "/api/v1/segments/member-counts",
        headers=admin_auth_header,
        params={"tenant_id": str(uuid4())},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"segments": [], "groups": []}
