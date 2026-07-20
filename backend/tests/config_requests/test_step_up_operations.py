"""Maker-checker coverage for the `step_up` config type.

Step-up PIN thresholds are governed exactly like pricing / limit / commission /
tax: a maker (platform-admin) PROPOSES a create/update/delete and a DIFFERENT
checker (config-approver) APPROVES it — only then is a `step_up_policies` row
written. Step-up is single-scope: its natural key is (transaction_type,
currency), so at most one open request per scope and one live row per scope.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import StepUpPolicy, Tenant

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


def _step_up_payload(
    tenant: Tenant,
    *,
    transaction_type: str = "p2p",
    currency: str = "ZAR",
    threshold: str = "200",
) -> dict:
    return {
        "tenant_id": str(tenant.id),
        "transaction_type": transaction_type,
        "currency": currency,
        "threshold_amount": threshold,
    }


def _create_body(tenant: Tenant, **kw: str) -> dict:
    """A `step_up` create proposal body wrapping a policy payload."""
    return {
        "config_type": "step_up",
        "operation": "create",
        "payload": _step_up_payload(tenant, **kw),
    }


async def _propose(client: AsyncClient, tenant: Tenant, body: dict, headers: dict[str, str]):
    return await client.post(_url(tenant), content=json.dumps(body), headers=headers)


async def _approve(
    client: AsyncClient, tenant: Tenant, request_id: str, headers: dict[str, str]
):
    return await client.post(_url(tenant, f"/{request_id}/approve"), headers=headers)


async def _policy_count(session: AsyncSession, tenant: Tenant) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(StepUpPolicy)
            .where(StepUpPolicy.tenant_id == tenant.id)
        )
    ).scalar_one()


# -----------------------------------------------------------------------------
# create
# -----------------------------------------------------------------------------


async def test_step_up_create_writes_no_policy_until_approved(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Propose create → no row; the checker's approval mints the policy row."""
    body = _create_body(test_tenant)
    proposed = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert proposed.status_code == 201, proposed.text

    # Nothing written before approval.
    assert await _policy_count(db_session, test_tenant) == 0

    approved = await _approve(
        async_client, test_tenant, proposed.json()["id"], _checker(make_admin_token)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPLIED"

    live = (
        await db_session.execute(
            select(StepUpPolicy).where(StepUpPolicy.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert live.transaction_type == "p2p"
    assert live.currency == "ZAR"
    assert Decimal(str(live.threshold_amount)) == Decimal("200")


# -----------------------------------------------------------------------------
# update
# -----------------------------------------------------------------------------


async def test_step_up_update_changes_threshold_on_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """An approved update replaces the scope's row with the new threshold."""
    create = await _propose(
        async_client,
        test_tenant,
        {"config_type": "step_up", "operation": "create", "payload": _step_up_payload(test_tenant)},
        _maker(make_admin_token),
    )
    await _approve(async_client, test_tenant, create.json()["id"], _checker(make_admin_token))
    live = (
        await db_session.execute(
            select(StepUpPolicy).where(StepUpPolicy.tenant_id == test_tenant.id)
        )
    ).scalar_one()

    update = await _propose(
        async_client,
        test_tenant,
        {
            "config_type": "step_up",
            "operation": "update",
            "target_config_id": str(live.id),
            "payload": _step_up_payload(test_tenant, threshold="750"),
        },
        _maker(make_admin_token),
    )
    assert update.status_code == 201, update.text
    approved = await _approve(
        async_client, test_tenant, update.json()["id"], _checker(make_admin_token)
    )
    assert approved.status_code == 200, approved.text

    # A fresh SELECT reads committed state; the update REPLACED the scope's row
    # (delete + insert), so exactly one row remains, carrying the new threshold.
    rows = list(
        (
            await db_session.execute(
                select(StepUpPolicy).where(StepUpPolicy.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(rows) == 1
    assert Decimal(str(rows[0].threshold_amount)) == Decimal("750")


async def test_step_up_update_scope_mismatch_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """An update whose payload scope differs from its target → 422 scope_mismatch."""
    create = await _propose(
        async_client,
        test_tenant,
        {"config_type": "step_up", "operation": "create", "payload": _step_up_payload(test_tenant)},
        _maker(make_admin_token),
    )
    await _approve(async_client, test_tenant, create.json()["id"], _checker(make_admin_token))
    live = (
        await db_session.execute(
            select(StepUpPolicy).where(StepUpPolicy.tenant_id == test_tenant.id)
        )
    ).scalar_one()

    # Same target row, but the payload names a DIFFERENT scope (redemption).
    resp = await _propose(
        async_client,
        test_tenant,
        {
            "config_type": "step_up",
            "operation": "update",
            "target_config_id": str(live.id),
            "payload": _step_up_payload(test_tenant, transaction_type="redemption"),
        },
        _maker(make_admin_token),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "config_request_scope_mismatch"


# -----------------------------------------------------------------------------
# delete
# -----------------------------------------------------------------------------


async def test_step_up_delete_removes_row_on_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """An approved delete removes the policy row for the target's scope."""
    create = await _propose(
        async_client,
        test_tenant,
        {"config_type": "step_up", "operation": "create", "payload": _step_up_payload(test_tenant)},
        _maker(make_admin_token),
    )
    await _approve(async_client, test_tenant, create.json()["id"], _checker(make_admin_token))
    live = (
        await db_session.execute(
            select(StepUpPolicy).where(StepUpPolicy.tenant_id == test_tenant.id)
        )
    ).scalar_one()

    delete = await _propose(
        async_client,
        test_tenant,
        {"config_type": "step_up", "operation": "delete", "target_config_id": str(live.id)},
        _maker(make_admin_token),
    )
    assert delete.status_code == 201, delete.text
    approved = await _approve(
        async_client, test_tenant, delete.json()["id"], _checker(make_admin_token)
    )
    assert approved.status_code == 200, approved.text

    # A fresh COUNT reads committed state — the policy row for the scope is gone.
    assert await _policy_count(db_session, test_tenant) == 0


# -----------------------------------------------------------------------------
# separation of duties + role gating
# -----------------------------------------------------------------------------


async def test_step_up_self_approval_forbidden(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """The maker cannot approve their own step-up request (needs config-approver + distinct)."""
    proposed = await _propose(
        async_client,
        test_tenant,
        {"config_type": "step_up", "operation": "create", "payload": _step_up_payload(test_tenant)},
        _maker(make_admin_token),
    )
    # Same admin, but even holding config-approver, self-approval is forbidden.
    self_token = make_admin_token(roles=["config-approver"], sub=MAKER_SUB)
    resp = await async_client.post(
        _url(test_tenant, f"/{proposed.json()['id']}/approve"),
        headers={"Authorization": f"Bearer {self_token}"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "self_approval_forbidden"


async def test_step_up_propose_requires_platform_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A config-approver (checker) cannot PROPOSE — propose is platform-admin only."""
    body = _create_body(test_tenant)
    resp = await _propose(async_client, test_tenant, body, _checker(make_admin_token))
    assert resp.status_code == 403, resp.text


async def test_step_up_approve_requires_config_approver(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A platform-admin (non-approver) cannot APPROVE — approve is config-approver only."""
    proposed = await _propose(
        async_client,
        test_tenant,
        {"config_type": "step_up", "operation": "create", "payload": _step_up_payload(test_tenant)},
        _maker(make_admin_token),
    )
    other_maker = make_admin_token(roles=["platform-admin"], sub=CHECKER_SUB)
    resp = await async_client.post(
        _url(test_tenant, f"/{proposed.json()['id']}/approve"),
        headers={"Authorization": f"Bearer {other_maker}"},
    )
    assert resp.status_code == 403, resp.text


# -----------------------------------------------------------------------------
# scope guard + payload validation
# -----------------------------------------------------------------------------


async def test_step_up_second_open_request_same_scope_rejected(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Two open requests for the same (transaction_type, currency) → 409 already_open."""
    body = _create_body(test_tenant)
    first = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert first.status_code == 201, first.text

    second = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "config_request_already_open"


async def test_step_up_different_scope_open_request_allowed(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A second open request on a DIFFERENT scope (currency) is not blocked."""
    zar = _create_body(test_tenant)
    usd = _create_body(test_tenant, currency="USD")
    first = await _propose(async_client, test_tenant, zar, _maker(make_admin_token))
    assert first.status_code == 201, first.text
    second = await _propose(async_client, test_tenant, usd, _maker(make_admin_token))
    assert second.status_code == 201, second.text


async def test_step_up_negative_threshold_rejected(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A negative threshold fails the create schema → 422 (before any write)."""
    body = {
        "config_type": "step_up",
        "operation": "create",
        "payload": _step_up_payload(test_tenant, threshold="-1"),
    }
    resp = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert resp.status_code == 422, resp.text


async def test_step_up_missing_field_rejected(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A payload missing transaction_type fails the create schema → 422."""
    body = {
        "config_type": "step_up",
        "operation": "create",
        "payload": {
            "tenant_id": str(test_tenant.id),
            "currency": "ZAR",
            "threshold_amount": "200",
        },
    }
    resp = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert resp.status_code == 422, resp.text
