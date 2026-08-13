"""Segment targeting on rules via the admin API (Epic 10 / WAL-79).

`rules.segment_id` gates eligibility in the evaluator (only members of the
bound segment can fire the rule). These tests cover the API surface that
sets and clears that binding: create with a segment, reject an unknown or
cross-tenant segment (404, no existence leak — NFR-0220), and retarget /
clear via PATCH. The evaluator behaviour itself is covered in
tests/segments/test_segment_binding_on_rule.py.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Segment, SegmentGroup, Tenant


async def _make_segment(session: AsyncSession, tenant: Tenant, name: str) -> Segment:
    """Helper — persist a group + one segment in it, return the segment."""
    group = SegmentGroup(tenant_id=tenant.id, name=f"{name}-group")
    session.add(group)
    await session.flush()
    segment = Segment(tenant_id=tenant.id, group_id=group.id, name=name)
    session.add(segment)
    await session.commit()
    return segment


def _campaign_payload(tenant: Tenant, name: str, **extra: object) -> dict[str, object]:
    """Helper — a valid time-boxed campaign create payload."""
    return {
        "tenant_id": str(tenant.id),
        "name": name,
        "rule_type": "campaign",
        "transaction_type": "p2p",
        "campaign_start_date": "2026-08-01",
        "campaign_end_date": "2026-12-31",
        "reward_type": "points",
        "reward_value": "50",
        **extra,
    }


@pytest.mark.asyncio
async def test_create_campaign_targeting_a_segment(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify an admin can target a campaign at one segment on creation"""
    segment = await _make_segment(db_session, test_tenant, "Gold")

    resp = await async_client.post(
        "/api/v1/rules",
        json=_campaign_payload(test_tenant, "Gold-only promo", segment_id=str(segment.id)),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["segment_id"] == str(segment.id)


@pytest.mark.asyncio
async def test_create_rule_without_segment_targets_everyone(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a campaign created without a segment reports a null binding"""
    resp = await async_client.post(
        "/api/v1/rules", json=_campaign_payload(test_tenant, "Open promo")
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["segment_id"] is None


@pytest.mark.asyncio
async def test_create_rule_rejects_unknown_segment(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a campaign cannot target a segment that does not exist"""
    resp = await async_client.post(
        "/api/v1/rules",
        json=_campaign_payload(test_tenant, "Ghost promo", segment_id=str(uuid4())),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "segment_not_found"


@pytest.mark.asyncio
async def test_create_rule_rejects_cross_tenant_segment(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Verify another tenant's segment cannot be targeted (404, no leak)"""
    foreign = await _make_segment(db_session, other_tenant, "Foreign Gold")

    resp = await async_client.post(
        "/api/v1/rules",
        json=_campaign_payload(test_tenant, "Leaky promo", segment_id=str(foreign.id)),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "segment_not_found"


@pytest.mark.asyncio
async def test_patch_rule_retargets_then_clears_segment(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify targeting can be added to a live campaign and cleared again"""
    segment = await _make_segment(db_session, test_tenant, "Silver")
    created = await async_client.post(
        "/api/v1/rules", json=_campaign_payload(test_tenant, "Retargetable promo")
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    retarget = await async_client.patch(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(test_tenant.id)},
        json={"segment_id": str(segment.id)},
    )
    assert retarget.status_code == 200, retarget.text
    assert retarget.json()["segment_id"] == str(segment.id)

    # An explicit null clears the binding — back to all users.
    cleared = await async_client.patch(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(test_tenant.id)},
        json={"segment_id": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["segment_id"] is None


@pytest.mark.asyncio
async def test_patch_rule_rejects_unknown_segment(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a retarget to a nonexistent segment is refused"""
    created = await async_client.post(
        "/api/v1/rules", json=_campaign_payload(test_tenant, "Unpatchable promo")
    )
    assert created.status_code == 201, created.text

    resp = await async_client.patch(
        f"/api/v1/rules/{created.json()['id']}",
        params={"tenant_id": str(test_tenant.id)},
        json={"segment_id": str(uuid4())},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "segment_not_found"
