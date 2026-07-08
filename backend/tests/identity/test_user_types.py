"""Tests for the user-types foundation on POST /api/v1/identity/users
and GET /api/v1/identity/users/{id} (Epic 12).

Covers the default type, explicit types, and the parent-compatibility rules
(Decision D4): agent -> super_agent, merchant -> head_merchant, same tenant;
consumer / super_agent / head_merchant must have a NULL parent.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant


async def _create_user(
    client: AsyncClient,
    headers: dict[str, str],
    tenant: Tenant,
    *,
    phone: str,
    user_type: str | None = None,
    parent_user_id: str | None = None,
) -> tuple[int, dict]:
    """POST a user and return (status_code, body). Keeps each test terse."""
    payload: dict = {
        "tenant_id": str(tenant.id),
        "identifiers": [{"identifier_type": "phone", "identifier_value": phone}],
    }
    if user_type is not None:
        payload["user_type"] = user_type
    if parent_user_id is not None:
        payload["parent_user_id"] = parent_user_id
    response = await client.post("/api/v1/identity/users", headers=headers, json=payload)
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_create_user_defaults_to_consumer(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Omitting user_type creates a consumer with no parent (backwards compatible)."""
    status, body = await _create_user(
        async_client, admin_auth_header, test_tenant, phone="+27 82 555 1000"
    )
    assert status == 201, body
    assert body["user_type"] == "consumer"
    assert body["parent_user_id"] is None


@pytest.mark.asyncio
async def test_create_super_agent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A super_agent is a top-level type — created with no parent."""
    status, body = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1001",
        user_type="super_agent",
    )
    assert status == 201, body
    assert body["user_type"] == "super_agent"


@pytest.mark.asyncio
async def test_create_agent_without_parent_allowed(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A parent is optional for agent — creation without one succeeds."""
    status, body = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1002",
        user_type="agent",
    )
    assert status == 201, body
    assert body["user_type"] == "agent"
    assert body["parent_user_id"] is None


@pytest.mark.asyncio
async def test_create_agent_under_super_agent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """An agent may hang under a super_agent parent in the same tenant."""
    _, parent = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1003",
        user_type="super_agent",
    )
    status, body = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1004",
        user_type="agent",
        parent_user_id=parent["id"],
    )
    assert status == 201, body
    assert body["parent_user_id"] == parent["id"]


@pytest.mark.asyncio
async def test_create_merchant_under_head_merchant(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A merchant may hang under a head_merchant parent."""
    _, parent = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1005",
        user_type="head_merchant",
    )
    status, body = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1006",
        user_type="merchant",
        parent_user_id=parent["id"],
    )
    assert status == 201, body
    assert body["parent_user_id"] == parent["id"]


@pytest.mark.asyncio
async def test_agent_parent_must_be_super_agent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """An agent whose parent is a consumer is rejected 422."""
    _, parent = await _create_user(
        async_client, admin_auth_header, test_tenant, phone="+27 82 555 1007"
    )  # consumer
    status, body = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1008",
        user_type="agent",
        parent_user_id=parent["id"],
    )
    assert status == 422, body
    assert body["error_code"] == "user_type_invalid_parent"


@pytest.mark.asyncio
async def test_consumer_cannot_have_parent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A consumer given any parent is rejected 422 (no hierarchy slot)."""
    _, parent = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1009",
        user_type="super_agent",
    )
    status, body = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1010",
        user_type="consumer",
        parent_user_id=parent["id"],
    )
    assert status == 422, body
    assert body["error_code"] == "user_type_invalid_parent"


@pytest.mark.asyncio
async def test_parent_must_be_same_tenant(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A cross-tenant parent is rejected 422 (no cross-tenant hierarchy)."""
    _, foreign_parent = await _create_user(
        async_client,
        admin_auth_header,
        other_tenant,
        phone="+27 82 555 1011",
        user_type="super_agent",
    )
    status, body = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1012",
        user_type="agent",
        parent_user_id=foreign_parent["id"],
    )
    assert status == 422, body
    assert body["error_code"] == "user_type_invalid_parent"


@pytest.mark.asyncio
async def test_missing_parent_reference_rejected(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """An agent pointing at a non-existent parent id is rejected 422."""
    status, body = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1013",
        user_type="agent",
        parent_user_id=str(uuid4()),
    )
    assert status == 422, body
    assert body["error_code"] == "user_type_invalid_parent"


@pytest.mark.asyncio
async def test_invalid_user_type_rejected(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """An unknown user_type fails Pydantic Literal validation (422)."""
    status, _ = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1014",
        user_type="wholesaler",
    )
    assert status == 422


@pytest.mark.asyncio
async def test_user_detail_exposes_type_and_parent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """GET /users/{id} surfaces user_type + parent_user_id for the admin drawer."""
    _, parent = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1015",
        user_type="super_agent",
    )
    _, child = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1016",
        user_type="agent",
        parent_user_id=parent["id"],
    )

    response = await async_client.get(
        f"/api/v1/identity/users/{child['id']}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_type"] == "agent"
    assert body["parent_user_id"] == parent["id"]
