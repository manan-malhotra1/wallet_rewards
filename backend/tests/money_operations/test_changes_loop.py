"""Treasury moves: request changes, revise, resubmit, withdraw.

Covers the mandatory request-changes comment, the maker-only revise/resubmit/
withdraw guard, and — the key N-eyes property — that a resubmit RESETS the
approval round: prior approvals no longer count and the same checker may approve
the fresh round.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import ApprovalPolicy, Tenant
from tests.money_operations.conftest import (
    CHECKER_SUB,
    approve,
    ops_url,
    propose,
    txn_count,
)


def _mirror(name: str) -> dict:
    return {"currency": "ZAR", "name": name}


async def _request_changes(
    client: AsyncClient, tenant: Tenant, op_id: str, header: dict[str, str], comment: str
):
    return await client.post(
        ops_url(tenant, f"/{op_id}/request-changes"),
        content=json.dumps({"comment": comment}),
        headers=header,
    )


@pytest.mark.asyncio
async def test_request_changes_requires_comment(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify asking for changes on a move requires a comment explaining why"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror("C")
    )
    resp = await async_client.post(
        ops_url(test_tenant, f"/{proposed['id']}/request-changes"),
        content=json.dumps({"comment": ""}),
        headers=checker_header,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_request_changes_moves_to_changes_requested(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify a checker can send a move back to the proposer with a comment"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror("C")
    )
    resp = await _request_changes(
        async_client, test_tenant, proposed["id"], checker_header, "Rename it."
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "CHANGES_REQUESTED"
    assert body["reviews"][-1]["action"] == "changes_requested"
    assert body["reviews"][-1]["comment"] == "Rename it."


@pytest.mark.asyncio
async def test_revise_resubmit_resets_approval_round(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
    checker2_header: dict[str, str],
) -> None:
    """Verify resubmitting a revised move clears earlier approvals and starts fresh

    A resubmit resets the round: a prior approval no longer counts, and the
    same checker may approve the fresh round."""
    db_session.add(
        ApprovalPolicy(tenant_id=test_tenant.id, operation=None, required_approvals=2)
    )
    await db_session.commit()

    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror("Round1")
    )
    op_id = proposed["id"]

    # Round 1: one approval (1 of 2), then a change request.
    first = await approve(async_client, test_tenant, op_id, checker_header)
    assert first.json()["approvals_count"] == 1
    rc = await _request_changes(async_client, test_tenant, op_id, checker2_header, "tweak name")
    assert rc.json()["status"] == "CHANGES_REQUESTED"

    # Maker revises + resubmits → PENDING, round reset to 0 approvals.
    revised = await async_client.patch(
        ops_url(test_tenant, f"/{op_id}"),
        content=json.dumps({"payload": _mirror("Round2")}),
        headers=maker_header,
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["payload"]["name"] == "Round2"

    resub = await async_client.post(
        ops_url(test_tenant, f"/{op_id}/resubmit"), headers=maker_header
    )
    assert resub.status_code == 200, resub.text
    assert resub.json()["status"] == "PENDING"
    assert resub.json()["approvals_count"] == 0  # reset

    # The SAME checker who approved round 1 may approve the fresh round.
    r1 = await approve(async_client, test_tenant, op_id, checker_header)
    assert r1.json()["status"] == "PENDING"
    assert r1.json()["approvals_count"] == 1
    r2 = await approve(async_client, test_tenant, op_id, checker2_header)
    assert r2.json()["status"] == "APPLIED"


@pytest.mark.asyncio
async def test_revise_by_non_maker_forbidden(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
    make_admin_token,
) -> None:
    """Verify only the admin who proposed a move can revise it"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror("C")
    )
    await _request_changes(async_client, test_tenant, proposed["id"], checker_header, "change")
    token = make_admin_token(roles=["platform-admin"], sub="55555555-5555-4000-8000-000000000005")
    other_maker = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = await async_client.patch(
        ops_url(test_tenant, f"/{proposed['id']}"),
        content=json.dumps({"payload": _mirror("Hijack")}),
        headers=other_maker,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_withdraw_is_terminal_no_execution(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify a withdrawn move can no longer be approved or executed"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror("Gone")
    )
    withdrawn = await async_client.post(
        ops_url(test_tenant, f"/{proposed['id']}/withdraw"), headers=maker_header
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"

    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "money_operation_invalid_state"
    assert await txn_count(db_session, test_tenant) == 0


@pytest.mark.asyncio
async def test_withdraw_by_non_maker_forbidden(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    make_admin_token,
) -> None:
    """Verify only the admin who proposed a move can withdraw it"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror("C")
    )
    token = make_admin_token(roles=["platform-admin"], sub="66666666-6666-4000-8000-000000000006")
    other = {"Authorization": f"Bearer {token}"}
    resp = await async_client.post(
        ops_url(test_tenant, f"/{proposed['id']}/withdraw"), headers=other
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_review_thread_records_whole_loop(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify the move keeps a full history of every step from proposal to completion

    The append-only thread captures submitted → changes → revised → resubmitted
    → approved → applied for a two-eyes op."""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror("Thread")
    )
    op_id = proposed["id"]
    await _request_changes(async_client, test_tenant, op_id, checker_header, "fix")
    await async_client.patch(
        ops_url(test_tenant, f"/{op_id}"),
        content=json.dumps({"payload": _mirror("Thread2")}),
        headers=maker_header,
    )
    await async_client.post(ops_url(test_tenant, f"/{op_id}/resubmit"), headers=maker_header)
    approved = await approve(async_client, test_tenant, op_id, checker_header)
    assert approved.json()["status"] == "APPLIED"

    detail = await async_client.get(ops_url(test_tenant, f"/{op_id}"), headers=maker_header)
    actions = [r["action"] for r in detail.json()["reviews"]]
    assert actions == [
        "submitted",
        "changes_requested",
        "revised",
        "resubmitted",
        "approved",
        "applied",
    ]
    # The lone approval after the resubmit is what counts (distinct-approver reset).
    assert CHECKER_SUB in {
        r["actor_admin_id"] for r in detail.json()["reviews"] if r["action"] == "approved"
    }
