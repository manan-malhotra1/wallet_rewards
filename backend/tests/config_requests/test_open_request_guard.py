"""One change at a time — blocking a second pending edit on the same config.

A maker must NOT be able to stack multiple in-flight change requests on the same
config scope (tenant_id, config_type, scope). Before a new proposal is created,
`propose_config_change` rejects it (409 `config_request_already_open`) if an OPEN
request — status PENDING or CHANGES_REQUESTED — already exists for the same
scope. The maker must approve, reject, or withdraw (or revise) the in-flight one
first.

Only PENDING + CHANGES_REQUESTED conflict. APPLIED / WITHDRAWN are terminal and
never block a fresh proposal for the same scope.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import LimitConfig, Tenant

pytestmark = pytest.mark.asyncio

MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _checker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["config-approver"], sub=CHECKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _url(tenant: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={tenant.id}"


async def _propose(client: AsyncClient, tenant: Tenant, body: dict, headers: dict[str, str]):
    return await client.post(_url(tenant), content=json.dumps(body), headers=headers)


async def _approve(
    client: AsyncClient, tenant: Tenant, request_id: str, headers: dict[str, str]
) -> None:
    resp = await client.post(_url(tenant, f"/{request_id}/approve"), headers=headers)
    assert resp.status_code == 200, resp.text


# -----------------------------------------------------------------------------
# Payload builders
# -----------------------------------------------------------------------------


def _limit_body(
    tenant_id: UUID,
    *,
    operation: str,
    max_amount: str,
    transaction_type: str = "p2p",
    target: str | None = None,
) -> dict:
    body: dict = {
        "config_type": "limit",
        "operation": operation,
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": transaction_type,
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "max_amount": max_amount,
        },
    }
    if target is not None:
        body["target_config_id"] = target
    return body


async def _create_live_limit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    make_admin_token: Callable[..., str],
    *,
    max_amount: str,
    transaction_type: str = "p2p",
) -> LimitConfig:
    """Propose + approve a create so a live limit config exists; return it."""
    proposed = await _propose(
        async_client,
        tenant,
        _limit_body(
            tenant.id,
            operation="create",
            max_amount=max_amount,
            transaction_type=transaction_type,
        ),
        _maker(make_admin_token),
    )
    assert proposed.status_code == 201, proposed.text
    await _approve(async_client, tenant, proposed.json()["id"], _checker(make_admin_token))
    return (
        await db_session.execute(
            select(LimitConfig).where(
                LimitConfig.tenant_id == tenant.id,
                LimitConfig.transaction_type == transaction_type,
            )
        )
    ).scalar_one()


# -----------------------------------------------------------------------------
# A second open change on the same scope is rejected
# -----------------------------------------------------------------------------


async def test_second_update_same_scope_is_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a second edit is blocked while one is already awaiting approval for that config."""
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, max_amount="1000"
    )
    first = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="2000", target=str(live.id)),
        _maker(make_admin_token),
    )
    assert first.status_code == 201, first.text

    second = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="3000", target=str(live.id)),
        _maker(make_admin_token),
    )
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "config_request_already_open"


async def test_create_vs_create_same_scope_is_409(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a second create proposal is blocked while one is already pending for that scope."""
    first = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="create", max_amount="1000"),
        _maker(make_admin_token),
    )
    assert first.status_code == 201, first.text

    second = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="create", max_amount="2000"),
        _maker(make_admin_token),
    )
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "config_request_already_open"


async def test_delete_when_update_open_same_scope_is_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a delete is blocked while an edit is already pending for the same config."""
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, max_amount="1000"
    )
    update = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="2000", target=str(live.id)),
        _maker(make_admin_token),
    )
    assert update.status_code == 201, update.text

    delete = await _propose(
        async_client,
        test_tenant,
        {"config_type": "limit", "operation": "delete", "target_config_id": str(live.id)},
        _maker(make_admin_token),
    )
    assert delete.status_code == 409, delete.text
    assert delete.json()["error_code"] == "config_request_already_open"


async def test_changes_requested_blocks_new_propose(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a new proposal is blocked while an earlier one is still awaiting the maker's edits.

    The maker must REVISE the in-flight request, not stack a fresh one.
    """
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, max_amount="1000"
    )
    first = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="2000", target=str(live.id)),
        _maker(make_admin_token),
    )
    request_id = first.json()["id"]
    rc = await async_client.post(
        _url(test_tenant, f"/{request_id}/request-changes"),
        content=json.dumps({"comment": "Try 2500 instead."}),
        headers=_checker(make_admin_token),
    )
    assert rc.status_code == 200, rc.text

    second = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="2500", target=str(live.id)),
        _maker(make_admin_token),
    )
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "config_request_already_open"


# -----------------------------------------------------------------------------
# Resolving the open request frees the scope again
# -----------------------------------------------------------------------------


async def test_new_propose_succeeds_after_withdraw(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify withdrawing a pending change frees the config for a new proposal."""
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, max_amount="1000"
    )
    first = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="2000", target=str(live.id)),
        _maker(make_admin_token),
    )
    request_id = first.json()["id"]
    wd = await async_client.post(
        _url(test_tenant, f"/{request_id}/withdraw"), headers=_maker(make_admin_token)
    )
    assert wd.status_code == 200, wd.text

    second = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="3000", target=str(live.id)),
        _maker(make_admin_token),
    )
    assert second.status_code == 201, second.text


async def test_new_propose_succeeds_after_approve(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify approving a pending change frees the config for a new proposal."""
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, max_amount="1000"
    )
    first = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="2000", target=str(live.id)),
        _maker(make_admin_token),
    )
    await _approve(async_client, test_tenant, first.json()["id"], _checker(make_admin_token))

    # The applied update minted a new live row for the scope; edit THAT one.
    new_live = (
        await db_session.execute(
            select(LimitConfig).where(LimitConfig.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert new_live.max_amount == Decimal("2000")

    second = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id, operation="update", max_amount="4000", target=str(new_live.id)
        ),
        _maker(make_admin_token),
    )
    assert second.status_code == 201, second.text


# -----------------------------------------------------------------------------
# A different scope is never blocked
# -----------------------------------------------------------------------------


async def test_different_scope_unaffected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a pending change on one config does not block changes to a different config."""
    p2p = await _create_live_limit(
        async_client,
        db_session,
        test_tenant,
        make_admin_token,
        max_amount="1000",
        transaction_type="p2p",
    )
    fund = await _create_live_limit(
        async_client,
        db_session,
        test_tenant,
        make_admin_token,
        max_amount="5000",
        transaction_type="fund",
    )

    open_a = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id,
            operation="update",
            max_amount="2000",
            transaction_type="p2p",
            target=str(p2p.id),
        ),
        _maker(make_admin_token),
    )
    assert open_a.status_code == 201, open_a.text

    open_b = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id,
            operation="update",
            max_amount="6000",
            transaction_type="fund",
            target=str(fund.id),
        ),
        _maker(make_admin_token),
    )
    assert open_b.status_code == 201, open_b.text
