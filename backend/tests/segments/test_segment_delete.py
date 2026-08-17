"""DELETE /api/v1/segments/{id} — guarded segment delete (Story B1.3).

Mirrors `test_group_api.py`'s delete coverage one level down: a segment can
only be removed once nothing still binds to it (a rule, a bonus multiplier)
and it isn't `is_system`-protected.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, BonusMultiplier, Rule, Segment, Tenant, User, UserSegment


async def _create_segment(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
    tenant_id: str,
    group_id: str,
    name: str,
) -> str:
    """POST a segment via the public API, return its id."""
    resp = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": tenant_id, "group_id": group_id, "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_delete_segment_happy_path_removes_memberships(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_segment_group: str,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify deleting a segment removes it AND its user_segments memberships, and is audited."""
    seg_id = await _create_segment(
        async_client, admin_auth_header, str(test_tenant.id), test_segment_group, "to-delete"
    )
    await async_client.post(
        f"/api/v1/segments/{seg_id}/users",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"user_id": str(test_user.id)},
    )

    resp = await async_client.delete(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 204, resp.text

    remaining_segment = (
        await db_session.execute(select(Segment).where(Segment.id == seg_id))
    ).scalar_one_or_none()
    assert remaining_segment is None

    remaining_membership = (
        await db_session.execute(select(UserSegment).where(UserSegment.segment_id == seg_id))
    ).scalar_one_or_none()
    assert remaining_membership is None

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "segment.deleted",
                AuditLog.entity_id == seg_id,
            )
        )
    ).scalar_one_or_none()
    assert audit_row is not None
    assert audit_row.before_state["name"] == "to-delete"
    assert audit_row.before_state["member_count"] == 1


@pytest.mark.asyncio
async def test_delete_segment_bound_to_rule_409_then_succeeds_after_unbind(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a segment referenced by a rule can't be deleted until unbound."""
    seg_id = await _create_segment(
        async_client, admin_auth_header, str(test_tenant.id), test_segment_group, "rule-bound"
    )

    rule_resp = await async_client.post(
        "/api/v1/rules",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "name": "rule-bound-to-segment",
            "rule_type": "first_time",
            "transaction_type": "fund",
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert rule_resp.status_code == 201, rule_resp.text
    rule_id = rule_resp.json()["id"]
    rule = (await db_session.execute(select(Rule).where(Rule.id == rule_id))).scalar_one()
    rule.segment_id = seg_id
    await db_session.commit()

    blocked = await async_client.delete(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert blocked.status_code == 409
    body = blocked.json()
    assert body["error_code"] == "segment_in_use"
    assert "1 rule(s)" in body["message"]
    assert "0 multiplier(s)" in body["message"]

    rule.segment_id = None
    await db_session.commit()

    resp = await async_client.delete(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_delete_segment_bound_to_multiplier_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a segment referenced by a bonus multiplier can't be deleted."""
    seg_id = await _create_segment(
        async_client, admin_auth_header, str(test_tenant.id), test_segment_group, "multiplier-bound"
    )

    multiplier_resp = await async_client.post(
        "/api/v1/multipliers",
        headers={**admin_auth_header, "Idempotency-Key": f"idem-{uuid4().hex}"},
        json={"tenant_id": str(test_tenant.id), "segment_id": seg_id, "multiplier": "1.5"},
    )
    assert multiplier_resp.status_code == 201, multiplier_resp.text

    resp = await async_client.delete(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "segment_in_use"
    assert "0 rule(s)" in body["message"]
    assert "1 multiplier(s)" in body["message"]

    # Cleanup guard: the multiplier still exists — proves the row was never
    # touched (the segment delete failed closed, not as a side effect).
    remaining = (
        await db_session.execute(
            select(BonusMultiplier).where(BonusMultiplier.segment_id == seg_id)
        )
    ).scalar_one_or_none()
    assert remaining is not None


@pytest.mark.asyncio
async def test_delete_segment_protected_409_for_system_segment(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an is_system segment cannot be deleted."""
    segment = Segment(
        tenant_id=test_tenant.id,
        group_id=test_segment_group,
        name="Gold",
        is_system=True,
    )
    db_session.add(segment)
    await db_session.commit()
    await db_session.refresh(segment)

    resp = await async_client.delete(
        f"/api/v1/segments/{segment.id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "segment_protected"


@pytest.mark.asyncio
async def test_delete_segment_404_unknown_and_cross_tenant(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify deleting an unknown segment, or one owned by another tenant, 404s."""
    unknown = await async_client.delete(
        f"/api/v1/segments/{uuid4()}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error_code"] == "segment_not_found"

    seg_id = await _create_segment(
        async_client, admin_auth_header, str(test_tenant.id), test_segment_group, "mine"
    )

    cross_tenant = await async_client.delete(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(other_tenant.id)},
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["error_code"] == "segment_not_found"
