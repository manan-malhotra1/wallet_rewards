"""Finding a customer by identifier — looking up who owns a phone, email, or account number.

Validates Pay-PRD-0060: any registered identifier maps to a canonical
user_id, scoped per tenant. Phase F.4 gates this endpoint behind
`platform-admin` — end users don't need it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant, User


@pytest.mark.asyncio
async def test_resolve_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a customer can be found by their phone number"""
    identifier = test_user.identifiers[0]
    response = await async_client.get(
        f"/api/v1/identity/resolve/phone/{identifier.identifier_value}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(test_user.id)
    assert body["tenant_id"] == str(test_tenant.id)
    assert body["identifier_type"] == "phone"


@pytest.mark.asyncio
async def test_resolve_returns_404_for_unknown(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify looking up an unregistered identifier finds no customer"""
    response = await async_client.get(
        "/api/v1/identity/resolve/phone/+27 99 999 9999",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_resolve_returns_404_for_other_tenant(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a customer cannot be found from another tenant

    test_user is registered in test_tenant; resolving the same identifier in
    other_tenant must return 404, not the user_id.
    """
    identifier = test_user.identifiers[0]
    response = await async_client.get(
        f"/api/v1/identity/resolve/phone/{identifier.identifier_value}",
        headers=admin_auth_header,
        params={"tenant_id": str(other_tenant.id)},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_resolve_rejects_unauthenticated_caller(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Verify looking up a customer requires signing in"""
    response = await async_client.get(
        "/api/v1/identity/resolve/phone/+27 82 555 0000",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 401
