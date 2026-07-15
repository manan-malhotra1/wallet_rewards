"""Per-revision payload snapshot tests (additive to Epic 22 maker-checker).

Each edit of a config request keeps a full history of its payload: propose
snapshots revision 1, every revise snapshots the bumped revision, and the
detail endpoint returns them in revision order. Approve / request-changes /
resubmit / withdraw add NO snapshot (only propose + revise do). A delete
proposal's snapshot carries a null payload.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import ConfigChangeRevision, Tenant

MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _checker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["config-approver"], sub=CHECKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _pricing_payload(tenant_id: UUID, fixed_fee: str = "5") -> dict:
    return {
        "config_type": "pricing",
        "operation": "create",
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": "cash_in",
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "fixed_fee": fixed_fee,
        },
    }


def _revise_body(tenant_id: UUID, fixed_fee: str) -> dict:
    return {
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": "cash_in",
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "fixed_fee": fixed_fee,
        }
    }


def _url(tenant: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={tenant.id}"


async def _snapshot_count(session: AsyncSession, request_id: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(ConfigChangeRevision)
            .where(ConfigChangeRevision.request_id == UUID(request_id))
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_propose_creates_revision_1_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Propose → exactly one snapshot at revision 1 carrying the proposed payload."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id, fixed_fee="5")),
        headers=_maker(make_admin_token),
    )
    assert proposed.status_code == 201, proposed.text
    request_id = proposed.json()["id"]

    assert await _snapshot_count(db_session, request_id) == 1

    detail = await async_client.get(
        _url(test_tenant, f"/{request_id}"), headers=_maker(make_admin_token)
    )
    revisions = detail.json()["revisions"]
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    # Pricing payloads are stored as a multi-band schedule (Epic 25).
    assert revisions[0]["payload"]["bands"][0]["fixed_fee"] == "5"


@pytest.mark.asyncio
async def test_revise_adds_revision_2_snapshot_ordered(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """request-changes → revise adds a revision-2 snapshot; both returned in order."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id, fixed_fee="5")),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]

    await async_client.post(
        _url(test_tenant, f"/{request_id}/request-changes"),
        content=json.dumps({"comment": "drop to 3"}),
        headers=_checker(make_admin_token),
    )
    revised = await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps(_revise_body(test_tenant.id, "3")),
        headers=_maker(make_admin_token),
    )
    assert revised.status_code == 200, revised.text

    assert await _snapshot_count(db_session, request_id) == 2

    detail = await async_client.get(
        _url(test_tenant, f"/{request_id}"), headers=_maker(make_admin_token)
    )
    revisions = detail.json()["revisions"]
    assert [r["revision"] for r in revisions] == [1, 2]
    v1 = revisions[0]["payload"]["bands"][0]["fixed_fee"]
    v2 = revisions[1]["payload"]["bands"][0]["fixed_fee"]
    assert v1 == "5"
    assert v2 == "3"
    assert v1 != v2


@pytest.mark.asyncio
async def test_resubmit_and_approve_add_no_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Only propose + revise snapshot: resubmit and approve leave the count at 2."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id, fixed_fee="5")),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]

    await async_client.post(
        _url(test_tenant, f"/{request_id}/request-changes"),
        content=json.dumps({"comment": "drop to 3"}),
        headers=_checker(make_admin_token),
    )
    await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps(_revise_body(test_tenant.id, "3")),
        headers=_maker(make_admin_token),
    )
    # Two snapshots so far (revisions 1 and 2).
    assert await _snapshot_count(db_session, request_id) == 2

    resub = await async_client.post(
        _url(test_tenant, f"/{request_id}/resubmit"), headers=_maker(make_admin_token)
    )
    assert resub.status_code == 200, resub.text
    approved = await async_client.post(
        _url(test_tenant, f"/{request_id}/approve"), headers=_checker(make_admin_token)
    )
    assert approved.status_code == 200, approved.text

    # Resubmit + approve added nothing.
    assert await _snapshot_count(db_session, request_id) == 2


@pytest.mark.asyncio
async def test_delete_proposal_snapshot_has_null_payload(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A delete proposal carries no payload → its revision-1 snapshot is null."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(
            {
                "config_type": "pricing",
                "operation": "delete",
                "target_config_id": str(uuid4()),
            }
        ),
        headers=_maker(make_admin_token),
    )
    assert proposed.status_code == 201, proposed.text
    request_id = proposed.json()["id"]

    assert await _snapshot_count(db_session, request_id) == 1

    detail = await async_client.get(
        _url(test_tenant, f"/{request_id}"), headers=_maker(make_admin_token)
    )
    revisions = detail.json()["revisions"]
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    assert revisions[0]["payload"] is None
