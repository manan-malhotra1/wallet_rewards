"""Maker-checker tests for the `user_type` config type.

User types join the config-request registry alongside pricing / limit /
wallet_limit / commission / tax / step_up / conversion_rate (spec D4): a maker
(platform-admin) proposes a create or an update, and a DIFFERENT checker
(config-approver) approves before any `user_types` row is written.

Delete is deliberately unsupported — spec D3 retires a type, never deletes it —
so a delete proposal is refused at propose time rather than blowing up on a
missing dispatch entry at approve time.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    USER_TYPE_STATUS_ACTIVE,
    USER_TYPE_STATUS_RETIRED,
    Tenant,
    UserTypeDef,
)

pytestmark = pytest.mark.asyncio

MAKER_SUB = "33333333-3333-4000-8000-000000000003"
CHECKER_SUB = "44444444-4444-4000-8000-000000000004"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """Headers for the proposing admin (platform-admin)."""
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _checker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """Headers for the approving admin — a DIFFERENT principal (config-approver)."""
    token = make_admin_token(roles=["config-approver"], sub=CHECKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _url(tenant: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={tenant.id}"


def _type_payload(tenant: Tenant, **overrides: object) -> dict:
    """A `user_types` create/update payload — the full desired row."""
    payload: dict = {
        "tenant_id": str(tenant.id),
        "code": "distributor",
        "label": "Distributor",
        "category_code": "retail",
    }
    payload.update(overrides)
    return payload


async def _propose(
    client: AsyncClient, tenant: Tenant, body: dict, headers: dict[str, str]
) -> object:
    return await client.post(_url(tenant), content=json.dumps(body), headers=headers)


async def _approve(
    client: AsyncClient, tenant: Tenant, request_id: str, headers: dict[str, str]
) -> object:
    return await client.post(_url(tenant, f"/{request_id}/approve"), headers=headers)


async def _load_type(session: AsyncSession, code: str) -> UserTypeDef | None:
    """Re-read a type row from the DB, bypassing the test session's identity map.

    `populate_existing` forces the already-loaded instance to refresh from the
    row the API's own session just wrote; without it the assertions would read
    stale in-memory attributes.
    """
    stmt = (
        select(UserTypeDef)
        .where(UserTypeDef.code == code)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# -----------------------------------------------------------------------------
# create
# -----------------------------------------------------------------------------


async def test_propose_and_approve_creates_the_type(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a proposed type only exists after a distinct admin approves it."""
    body = {
        "config_type": "user_type",
        "operation": "create",
        "payload": _type_payload(test_tenant),
    }
    proposed = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert proposed.status_code == 201, proposed.text
    request_id = proposed.json()["id"]

    # Nothing is written until a checker approves.
    assert await _load_type(db_session, "distributor") is None

    approved = await _approve(async_client, test_tenant, request_id, _checker(make_admin_token))
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPLIED"

    row = await _load_type(db_session, "distributor")
    assert row is not None
    assert row.label == "Distributor"
    assert row.tenant_id == test_tenant.id
    assert row.is_system is False


async def test_propose_requires_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify an unauthenticated user_type proposal is refused (401)."""
    body = {
        "config_type": "user_type",
        "operation": "create",
        "payload": _type_payload(test_tenant),
    }
    response = await async_client.post(
        _url(test_tenant), content=json.dumps(body), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 401


async def test_payload_for_another_tenant_is_refused(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a payload naming a different tenant cannot ride a request's scope.

    Tenant isolation (NFR-0220): the request is scoped by the `tenant_id` query
    param, so a payload pointing elsewhere must be rejected outright rather than
    quietly writing a type into the other tenant's catalog.
    """
    body = {
        "config_type": "user_type",
        "operation": "create",
        "payload": _type_payload(other_tenant),
    }
    response = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "config_request_tenant_mismatch"
    assert await _load_type(db_session, "distributor") is None


# -----------------------------------------------------------------------------
# update (relabel / retire)
# -----------------------------------------------------------------------------


async def test_approved_update_relabels_and_retires_in_place(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify an update edits the live row in place, keeping its id (spec D3/D5)."""
    row = UserTypeDef(
        tenant_id=test_tenant.id,
        code="distributor",
        label="Distributor",
        category_code="retail",
    )
    db_session.add(row)
    await db_session.commit()
    original_id = row.id

    body = {
        "config_type": "user_type",
        "operation": "update",
        "target_config_id": str(original_id),
        "payload": _type_payload(
            test_tenant, label="Regional Distributor", status=USER_TYPE_STATUS_RETIRED
        ),
    }
    proposed = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert proposed.status_code == 201, proposed.text

    approved = await _approve(
        async_client, test_tenant, proposed.json()["id"], _checker(make_admin_token)
    )
    assert approved.status_code == 200, approved.text

    updated = await _load_type(db_session, "distributor")
    assert updated is not None
    # Same row, not delete-and-reinsert: `users.user_type` and every config row
    # reference the code with no FK, so the id and created_at must survive.
    assert updated.id == original_id
    assert updated.label == "Regional Distributor"
    assert updated.status == USER_TYPE_STATUS_RETIRED


async def test_update_targeting_another_tenants_type_is_not_found(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify one tenant cannot edit another tenant's type (tenant isolation)."""
    foreign = UserTypeDef(
        tenant_id=other_tenant.id,
        code="franchisee",
        label="Franchisee",
        category_code="retail",
    )
    db_session.add(foreign)
    await db_session.commit()

    body = {
        "config_type": "user_type",
        "operation": "update",
        "target_config_id": str(foreign.id),
        "payload": _type_payload(test_tenant, code="franchisee", label="Hijacked"),
    }
    response = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert response.status_code == 404, response.text

    unchanged = await _load_type(db_session, "franchisee")
    assert unchanged is not None
    assert unchanged.label == "Franchisee"
    assert unchanged.status == USER_TYPE_STATUS_ACTIVE


# -----------------------------------------------------------------------------
# delete — never supported (spec D3)
# -----------------------------------------------------------------------------


async def test_delete_operation_is_refused(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify user types can never be deleted, only retired (spec D3).

    `user_type` is absent from `_DELETE_SCOPE_DISPATCH` on purpose; the maker
    must hear a clean refusal at propose time, not a KeyError 500 at approve.
    """
    body = {
        "config_type": "user_type",
        "operation": "delete",
        "target_config_id": "00000000-0000-0000-0000-000000000001",
    }
    response = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "config_delete_not_supported"
    assert "retire" in response.json()["message"].lower()


async def test_delete_still_works_for_types_that_support_it(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify the new refusal did not break delete for the other config types.

    A tax delete against a missing target must still reach the existing
    propose contract (accepted, 404s at apply) rather than the new 422.
    """
    body = {
        "config_type": "tax",
        "operation": "delete",
        "target_config_id": "00000000-0000-0000-0000-000000000001",
    }
    response = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert response.status_code == 201, response.text
