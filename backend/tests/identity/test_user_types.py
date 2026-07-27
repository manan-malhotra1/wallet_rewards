"""Customer types and hierarchy — creating agents, merchants, and their parents.
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
    """Verify a new customer is a consumer by default"""
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
    """Verify a super agent can be created"""
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
    """Verify an agent can be created without a parent"""
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
    """Verify an agent can be created under a super agent"""
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
    """Verify a merchant can be created under a head merchant"""
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
    """Verify an agent cannot be placed under a consumer"""
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
    """Verify a consumer cannot be given a parent"""
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
    """Verify a customer cannot be placed under a parent in another tenant"""
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
    """Verify a customer cannot be placed under a parent that does not exist"""
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
    """Verify creating a customer with an unknown type is rejected"""
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
    """Verify a customer's type and parent show on their profile"""
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


@pytest.mark.asyncio
async def test_user_detail_parent_name_uses_profile(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a customer's parent is shown by their full name"""
    parent_resp = await async_client.post(
        "/api/v1/identity/users",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifiers": [{"identifier_type": "phone", "identifier_value": "+27 82 555 1020"}],
            "user_type": "super_agent",
            "profile": {"first_name": "Thandi", "last_name": "Ncube"},
        },
    )
    assert parent_resp.status_code == 201, parent_resp.text
    parent_id = parent_resp.json()["id"]

    _, child = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1021",
        user_type="agent",
        parent_user_id=parent_id,
    )

    response = await async_client.get(
        f"/api/v1/identity/users/{child['id']}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["parent_name"] == "Thandi Ncube"


@pytest.mark.asyncio
async def test_user_detail_parent_name_falls_back_to_identifier(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a customer's parent is shown by their phone number when they have no profile"""
    _, parent = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1022",
        user_type="super_agent",
    )
    _, child = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1023",
        user_type="agent",
        parent_user_id=parent["id"],
    )

    response = await async_client.get(
        f"/api/v1/identity/users/{child['id']}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    # Phone is normalised (spaces stripped) on persistence.
    assert response.json()["parent_name"] == "+27825551022"


@pytest.mark.asyncio
async def test_user_detail_parent_name_null_without_parent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a top-level customer shows no parent name"""
    _, user = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 1024",
        user_type="super_agent",
    )
    response = await async_client.get(
        f"/api/v1/identity/users/{user['id']}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["parent_user_id"] is None
    assert body["parent_name"] is None
