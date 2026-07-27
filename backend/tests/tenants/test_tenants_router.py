"""Managing tenant identity cards.

Covers the LIST endpoint plus the new GET-one and PATCH endpoints added
when the deployment_mode → business_type rename landed in migration 0016.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_list_tenants_requires_auth(async_client: AsyncClient) -> None:
    """Verify a signed-out user cannot list tenants"""
    resp = await async_client.get("/api/v1/tenants")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_tenants_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can see the tenant in the list with its business type"""
    resp = await async_client.get("/api/v1/tenants", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = [t["id"] for t in body]
    assert str(test_tenant.id) in ids
    row = next(t for t in body if t["id"] == str(test_tenant.id))
    assert row["business_type"] == "both"
    assert "keycloak_realm" in row


@pytest.mark.asyncio
async def test_get_tenant_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can open a single tenant's identity card"""
    resp = await async_client.get(f"/api/v1/tenants/{test_tenant.id}", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(test_tenant.id)
    assert body["name"] == test_tenant.name
    assert body["business_type"] == "both"


@pytest.mark.asyncio
async def test_get_tenant_unknown_id_returns_404(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify opening a tenant that does not exist is reported as not found"""
    resp = await async_client.get(f"/api/v1/tenants/{uuid4()}", headers=admin_auth_header)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "tenant_not_found"


@pytest.mark.asyncio
async def test_patch_tenant_name_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can rename a tenant"""
    new_name = f"renamed-{uuid4().hex[:8]}"
    resp = await async_client.patch(
        f"/api/v1/tenants/{test_tenant.id}",
        headers=admin_auth_header,
        json={"name": new_name},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == new_name


@pytest.mark.asyncio
async def test_patch_tenant_business_type_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can change a tenant's business type"""
    resp = await async_client.patch(
        f"/api/v1/tenants/{test_tenant.id}",
        headers=admin_auth_header,
        json={"business_type": "rewards"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["business_type"] == "rewards"


@pytest.mark.asyncio
async def test_patch_tenant_rejects_unknown_business_type(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a tenant cannot be set to an unsupported business type"""
    resp = await async_client.patch(
        f"/api/v1/tenants/{test_tenant.id}",
        headers=admin_auth_header,
        json={"business_type": "loyalty"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_tenant_rejects_extra_fields(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot change protected tenant fields through an edit"""
    resp = await async_client.patch(
        f"/api/v1/tenants/{test_tenant.id}",
        headers=admin_auth_header,
        json={"keycloak_realm": "tampered"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_tenant_duplicate_name_returns_409(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a tenant cannot be renamed to a name another tenant already uses"""
    resp = await async_client.patch(
        f"/api/v1/tenants/{test_tenant.id}",
        headers=admin_auth_header,
        json={"name": other_tenant.name},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "tenant_name_already_exists"


@pytest.mark.asyncio
async def test_patch_unknown_tenant_returns_404(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify editing a tenant that does not exist is reported as not found"""
    resp = await async_client.patch(
        f"/api/v1/tenants/{uuid4()}",
        headers=admin_auth_header,
        json={"name": "anything"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_tenant_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Verify a signed-out user cannot edit a tenant"""
    resp = await async_client.patch(
        f"/api/v1/tenants/{test_tenant.id}",
        json={"name": "anon"},
    )
    assert resp.status_code == 401
