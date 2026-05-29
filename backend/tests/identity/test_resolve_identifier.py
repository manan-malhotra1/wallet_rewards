"""Tests for GET /api/v1/identity/resolve/{type}/{value}.

Validates Pay-PRD-0060: any registered identifier maps to a canonical
user_id, scoped per tenant.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant, User


@pytest.mark.asyncio
async def test_resolve_happy_path(
    async_client: AsyncClient, test_tenant: Tenant, test_user: User
) -> None:
    """A registered phone resolves to its user_id."""
    # test_user has an auto-assigned phone in the conftest fixture; fetch it.
    identifier = test_user.identifiers[0]
    response = await async_client.get(
        f"/api/v1/identity/resolve/phone/{identifier.identifier_value}",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(test_user.id)
    assert body["tenant_id"] == str(test_tenant.id)
    assert body["identifier_type"] == "phone"


@pytest.mark.asyncio
async def test_resolve_returns_404_for_unknown(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """An unregistered identifier returns 404 user_not_found."""
    response = await async_client.get(
        "/api/v1/identity/resolve/phone/+27 99 999 9999",
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
) -> None:
    """Cross-tenant lookups must NOT leak data (NFR-0220).

    test_user is registered in test_tenant; resolving the same identifier in
    other_tenant must return 404, not the user_id.
    """
    identifier = test_user.identifiers[0]
    response = await async_client.get(
        f"/api/v1/identity/resolve/phone/{identifier.identifier_value}",
        params={"tenant_id": str(other_tenant.id)},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_found"
