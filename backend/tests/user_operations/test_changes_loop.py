"""User changes: request changes, revise, resubmit, withdraw.

Covers the mandatory-comment guard, the CHANGES_REQUESTED transition, that a
resubmit resets the approval round (an approval before it doesn't count), and
that withdraw is terminal and applies nothing.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant
from tests.user_operations.conftest import (
    approve,
    create_user_payload,
    ops_url,
    propose,
    request_changes,
    user_count,
)


@pytest.mark.asyncio
async def test_request_changes_moves_to_changes_requested(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify a checker can send a user change back to the proposer with a comment"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    resp = await request_changes(
        async_client, test_tenant, proposed["id"], checker_header, "Fix the name."
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "CHANGES_REQUESTED"
    assert body["reviews"][-1]["action"] == "changes_requested"
    assert body["reviews"][-1]["comment"] == "Fix the name."


@pytest.mark.asyncio
async def test_request_changes_requires_comment(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify asking for changes on a user change requires a comment explaining why"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    resp = await async_client.post(
        ops_url(test_tenant, f"/{proposed['id']}/request-changes"),
        content=json.dumps({"comment": ""}),
        headers={**checker_header, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_revise_then_resubmit_resets_round(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
    checker2_header: dict[str, str],
) -> None:
    """Verify resubmitting a revised user change clears earlier approvals and starts fresh

    A resubmit starts a new round, so `checker` (who acted only as change
    requester before) approving after the resubmit applies the op cleanly.
    """
    before = await user_count(db_session, test_tenant)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    await request_changes(async_client, test_tenant, proposed["id"], checker_header, "Change type.")

    # Maker revises the payload in place.
    revise = await async_client.patch(
        ops_url(test_tenant, f"/{proposed['id']}"),
        content=json.dumps({"payload": create_user_payload(user_type="super_agent")}),
        headers=maker_header,
    )
    assert revise.status_code == 200, revise.text
    assert revise.json()["status"] == "CHANGES_REQUESTED"

    # Maker resubmits → PENDING, fresh round.
    resubmit = await async_client.post(
        ops_url(test_tenant, f"/{proposed['id']}/resubmit"), headers=maker_header
    )
    assert resubmit.status_code == 200
    assert resubmit.json()["status"] == "PENDING"
    assert resubmit.json()["approvals_count"] == 0

    # A distinct checker approves the fresh round → APPLIED.
    resp = await approve(async_client, test_tenant, proposed["id"], checker2_header)
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPLIED"
    assert await user_count(db_session, test_tenant) == before + 1


@pytest.mark.asyncio
async def test_withdraw_is_terminal_and_applies_nothing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify a withdrawn user change can no longer be approved or applied"""
    before = await user_count(db_session, test_tenant)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    withdraw = await async_client.post(
        ops_url(test_tenant, f"/{proposed['id']}/withdraw"), headers=maker_header
    )
    assert withdraw.status_code == 200
    assert withdraw.json()["status"] == "WITHDRAWN"

    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 409
    assert await user_count(db_session, test_tenant) == before


@pytest.mark.asyncio
async def test_withdraw_only_by_maker(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    make_admin_token,
) -> None:
    """Verify only the admin who proposed a user change can withdraw it"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    token = make_admin_token(roles=["platform-admin"], sub="55555555-5555-4000-8000-000000000005")
    resp = await async_client.post(
        ops_url(test_tenant, f"/{proposed['id']}/withdraw"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
