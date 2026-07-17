"""Revise trust-boundary tests — a revise must re-run propose's scope/tenant guards.

`revise_config_request` edits a CHANGES_REQUESTED request's payload before it is
resubmitted and (on approval) applied. It is a governance trust boundary just
like propose: a revised payload must not carry a band for another tenant, and —
for an update — must not move the request's scope onto a different config than
the one the request names. The UI locks scope, but the backend is the boundary.

Mirrors propose's `config_request_tenant_mismatch` / `config_request_scope_mismatch`
guards (see test_update_operation.py::test_update_scope_mismatch_rejected_matching_succeeds).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import ConfigChangeRevision, LimitConfig, Tenant

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


def _revise_payload(tenant_id: UUID, max_amount: str) -> dict:
    """A same-scope (p2p) revise body for a limit request."""
    return {
        "payload": _limit_body(tenant_id, operation="update", max_amount=max_amount)["payload"]
    }


async def _snapshot_count(session: AsyncSession, request_id: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(ConfigChangeRevision)
            .where(ConfigChangeRevision.request_id == UUID(request_id))
        )
    ).scalar_one()


async def _create_live_limit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    make_admin_token: Callable[..., str],
    max_amount: str,
) -> LimitConfig:
    """Propose + approve a create so a live limit config (scope p2p) exists."""
    proposed = await async_client.post(
        _url(tenant),
        content=json.dumps(_limit_body(tenant.id, operation="create", max_amount=max_amount)),
        headers=_maker(make_admin_token),
    )
    assert proposed.status_code == 201, proposed.text
    approved = await async_client.post(
        _url(tenant, f"/{proposed.json()['id']}/approve"),
        headers=_checker(make_admin_token),
    )
    assert approved.status_code == 200, approved.text
    return (
        await db_session.execute(select(LimitConfig).where(LimitConfig.tenant_id == tenant.id))
    ).scalar_one()


async def _propose_update_changes_requested(
    async_client: AsyncClient,
    tenant: Tenant,
    make_admin_token: Callable[..., str],
    target_id: str,
) -> str:
    """Propose an update (scope p2p) and drive it to CHANGES_REQUESTED; return its id."""
    proposed = await async_client.post(
        _url(tenant),
        content=json.dumps(
            _limit_body(tenant.id, operation="update", max_amount="2000", target=target_id)
        ),
        headers=_maker(make_admin_token),
    )
    assert proposed.status_code == 201, proposed.text
    request_id = proposed.json()["id"]
    rc = await async_client.post(
        _url(tenant, f"/{request_id}/request-changes"),
        content=json.dumps({"comment": "adjust it"}),
        headers=_checker(make_admin_token),
    )
    assert rc.status_code == 200, rc.text
    return request_id


async def test_revise_update_scope_mismatch_rejected_matching_succeeds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Revising an update with a payload whose scope differs from the target → 422.

    Without the guard the revised payload could move the request's scope so that
    on approval it replaces a DIFFERENT config than the request names. A same-
    scope revise still succeeds (revision bumps, snapshot added).
    """
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, "1000"
    )
    request_id = await _propose_update_changes_requested(
        async_client, test_tenant, make_admin_token, str(live.id)
    )

    # Revise with a payload whose transaction_type (scope) differs from the target.
    mismatched = await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps(
            {
                "payload": {
                    "tenant_id": str(test_tenant.id),
                    "transaction_type": "fund",  # scope B — target is scope A ("p2p")
                    "account_type": "financial_wallet",
                    "currency": "ZAR",
                    "max_amount": "3000",
                }
            }
        ),
        headers=_maker(make_admin_token),
    )
    assert mismatched.status_code == 422, mismatched.text
    assert mismatched.json()["error_code"] == "config_request_scope_mismatch"
    # The rejected revise added no snapshot and did not bump the revision.
    assert await _snapshot_count(db_session, request_id) == 1

    # A same-scope revise against the same target still succeeds.
    ok = await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps(_revise_payload(test_tenant.id, "3000")),
        headers=_maker(make_admin_token),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["revision"] == 2
    assert await _snapshot_count(db_session, request_id) == 2


async def test_revise_scope_mismatch_leaves_target_untouched_after_approve(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A same-scope revise applies to the named config; the cap lands, one row."""
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, "1000"
    )
    request_id = await _propose_update_changes_requested(
        async_client, test_tenant, make_admin_token, str(live.id)
    )
    revised = await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps(_revise_payload(test_tenant.id, "3000")),
        headers=_maker(make_admin_token),
    )
    assert revised.status_code == 200, revised.text
    resub = await async_client.post(
        _url(test_tenant, f"/{request_id}/resubmit"), headers=_maker(make_admin_token)
    )
    assert resub.status_code == 200, resub.text
    approved = await async_client.post(
        _url(test_tenant, f"/{request_id}/approve"), headers=_checker(make_admin_token)
    )
    assert approved.status_code == 200, approved.text

    rows = list(
        (
            await db_session.execute(
                select(LimitConfig).where(LimitConfig.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].max_amount == Decimal("3000")


async def test_revise_with_foreign_tenant_band_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Revising with a band carrying a foreign tenant_id → 422 tenant_mismatch.

    Mirrors propose's tenant-match guard: a revised payload's band tenant_id must
    equal the request's tenant.
    """
    # A create proposal is enough to exercise the tenant-match guard on revise.
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_limit_body(test_tenant.id, operation="create", max_amount="1000")),
        headers=_maker(make_admin_token),
    )
    assert proposed.status_code == 201, proposed.text
    request_id = proposed.json()["id"]
    rc = await async_client.post(
        _url(test_tenant, f"/{request_id}/request-changes"),
        content=json.dumps({"comment": "fix it"}),
        headers=_checker(make_admin_token),
    )
    assert rc.status_code == 200, rc.text

    # Revise with a band whose tenant_id points at another tenant.
    foreign = await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps(
            {"payload": _limit_body(uuid4(), operation="create", max_amount="1500")["payload"]}
        ),
        headers=_maker(make_admin_token),
    )
    assert foreign.status_code == 422, foreign.text
    assert foreign.json()["error_code"] == "config_request_tenant_mismatch"
    # Rejected revise added no snapshot.
    assert await _snapshot_count(db_session, request_id) == 1
