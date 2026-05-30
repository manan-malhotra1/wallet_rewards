"""Tests for the role CRUD admin endpoints (Phase F.3).

These hit `/api/v1/roles/*` and `/api/v1/users/{id}/roles*` — all gated by
the `platform-admin` Keycloak realm role from Phase F.1. The auth header is
attached by the package-local conftest's `async_client` fixture.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant, User


# -----------------------------------------------------------------------------
# Role CRUD
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_role_happy_path(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    response = await async_client.post(
        "/api/v1/roles",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "merchant",
            "description": "Can accept bill payments.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "merchant"
    assert body["status"] == "active"
    assert body["tenant_id"] == str(test_tenant.id)


@pytest.mark.asyncio
async def test_create_role_duplicate_name_rejected(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    payload = {"tenant_id": str(test_tenant.id), "name": "dupe"}
    first = await async_client.post("/api/v1/roles", json=payload)
    assert first.status_code == 201
    second = await async_client.post("/api/v1/roles", json=payload)
    assert second.status_code == 409
    assert second.json()["error_code"] == "role_already_exists"


@pytest.mark.asyncio
async def test_create_role_unknown_tenant(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(uuid4()), "name": "x"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_roles_tenant_scoped(
    async_client: AsyncClient, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "A-role"},
    )
    await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(other_tenant.id), "name": "B-role"},
    )
    a_list = await async_client.get(
        "/api/v1/roles", params={"tenant_id": str(test_tenant.id)}
    )
    names = [r["name"] for r in a_list.json()]
    assert "A-role" in names
    assert "B-role" not in names


@pytest.mark.asyncio
async def test_update_role_status_to_inactive(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "frozen"},
    )
    role_id = create.json()["id"]
    update = await async_client.patch(
        f"/api/v1/roles/{role_id}",
        params={"tenant_id": str(test_tenant.id)},
        json={"status": "inactive"},
    )
    assert update.status_code == 200
    assert update.json()["status"] == "inactive"


# -----------------------------------------------------------------------------
# Permissions on a role
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_permission_creates_then_updates(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "perm-test"},
    )
    role_id = create.json()["id"]

    first = await async_client.post(
        f"/api/v1/roles/{role_id}/permissions",
        params={"tenant_id": str(test_tenant.id)},
        json={"transaction_type": "p2p", "permitted": True},
    )
    assert first.status_code == 201

    # Re-set updates in place, doesn't create a duplicate.
    second = await async_client.post(
        f"/api/v1/roles/{role_id}/permissions",
        params={"tenant_id": str(test_tenant.id)},
        json={"transaction_type": "p2p", "permitted": False},
    )
    assert second.status_code == 201

    perms = await async_client.get(
        f"/api/v1/roles/{role_id}/permissions",
        params={"tenant_id": str(test_tenant.id)},
    )
    rows = perms.json()
    assert len(rows) == 1
    assert rows[0]["permitted"] is False


@pytest.mark.asyncio
async def test_remove_permission(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "rm-test"},
    )
    role_id = create.json()["id"]
    await async_client.post(
        f"/api/v1/roles/{role_id}/permissions",
        params={"tenant_id": str(test_tenant.id)},
        json={"transaction_type": "redemption", "permitted": True},
    )
    delete = await async_client.delete(
        f"/api/v1/roles/{role_id}/permissions/redemption",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert delete.status_code == 204

    perms = await async_client.get(
        f"/api/v1/roles/{role_id}/permissions",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert perms.json() == []


# -----------------------------------------------------------------------------
# User-role assignment
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_role_to_user(
    async_client: AsyncClient, test_tenant: Tenant, test_user: User
) -> None:
    role_resp = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "extra-role"},
    )
    role_id = role_resp.json()["id"]
    assign = await async_client.post(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
        json={"role_id": role_id},
    )
    assert assign.status_code == 201
    listing = await async_client.get(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
    )
    role_ids = {r["role_id"] for r in listing.json()}
    assert role_id in role_ids


@pytest.mark.asyncio
async def test_assign_role_idempotent(
    async_client: AsyncClient, test_tenant: Tenant, test_user: User
) -> None:
    """Re-assigning the same role returns the existing row, doesn't duplicate."""
    role_resp = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "idem-role"},
    )
    role_id = role_resp.json()["id"]
    first = await async_client.post(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
        json={"role_id": role_id},
    )
    second = await async_client.post(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
        json={"role_id": role_id},
    )
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_remove_role_from_user(
    async_client: AsyncClient, test_tenant: Tenant, test_user: User
) -> None:
    """User starts with default role from fixture; remove it; list is empty."""
    listing = await async_client.get(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert len(listing.json()) == 1
    default_role_id = listing.json()[0]["role_id"]

    delete = await async_client.delete(
        f"/api/v1/users/{test_user.id}/roles/{default_role_id}",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert delete.status_code == 204

    after = await async_client.get(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert after.json() == []


@pytest.mark.asyncio
async def test_assign_cross_tenant_user_rejects(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
) -> None:
    """Assigning a role from tenant A to a user in tenant B (or vice versa) → 404."""
    role_resp = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(other_tenant.id), "name": "x-tenant-role"},
    )
    other_role_id = role_resp.json()["id"]
    # test_user is in test_tenant; trying to assign other_tenant's role under
    # other_tenant's scope where test_user doesn't exist → 404.
    assign = await async_client.post(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(other_tenant.id)},
        json={"role_id": other_role_id},
    )
    assert assign.status_code == 404
    assert assign.json()["error_code"] == "user_not_found"


# -----------------------------------------------------------------------------
# Auth gate
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_crud_requires_admin(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token
) -> None:
    """A token without `platform-admin` role gets 403."""
    response = await async_client.post(
        "/api/v1/roles",
        headers={"Authorization": f"Bearer {make_admin_token(roles=['support-agent'])}"},
        json={"tenant_id": str(test_tenant.id), "name": "support-cannot-create"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "insufficient_role"
