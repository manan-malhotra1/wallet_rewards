"""Managing the service catalog.

Covers list (tenant-scoped + status filter), create (happy + dup-code +
auth + validation), patch (display_name + status + 404), and soft-delete
(idempotent re-create after delete).
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Service, Tenant


async def _seed_service(
    session: AsyncSession,
    tenant_id: str,
    code: str,
    display_name: str | None = None,
    status: str = "active",
) -> Service:
    """Insert a service row directly so individual tests don't depend on POST."""
    svc = Service(
        tenant_id=tenant_id,
        code=code,
        display_name=display_name or code.upper(),
        status=status,
    )
    session.add(svc)
    await session.commit()
    await session.refresh(svc)
    return svc


@pytest.mark.asyncio
async def test_list_services_requires_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify a signed-out user cannot list services"""
    resp = await async_client.get("/api/v1/services", params={"tenant_id": str(test_tenant.id)})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_services_returns_active_and_disabled(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the catalog lists both active and disabled services by default"""
    await _seed_service(db_session, str(test_tenant.id), "p2p")
    await _seed_service(db_session, str(test_tenant.id), "legacy_fund", status="disabled")

    resp = await async_client.get(
        "/api/v1/services",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    codes = {s["code"] for s in resp.json()}
    assert codes == {"p2p", "legacy_fund"}


@pytest.mark.asyncio
async def test_list_services_status_filter(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify filtering the catalog by active status shows only active services"""
    await _seed_service(db_session, str(test_tenant.id), "p2p")
    await _seed_service(db_session, str(test_tenant.id), "legacy", status="disabled")
    resp = await async_client.get(
        "/api/v1/services",
        params={"tenant_id": str(test_tenant.id), "status": "active"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    codes = [s["code"] for s in resp.json()]
    assert codes == ["p2p"]


@pytest.mark.asyncio
async def test_list_services_tenant_isolated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify one tenant cannot see another tenant's service catalog"""
    await _seed_service(db_session, str(test_tenant.id), "p2p")
    await _seed_service(db_session, str(other_tenant.id), "p2p")
    resp = await async_client.get(
        "/api/v1/services",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    body = resp.json()
    assert len(body) == 1
    assert body[0]["tenant_id"] == str(test_tenant.id)


@pytest.mark.asyncio
async def test_create_service_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can add a new service to the catalog"""
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "bill_pay",
            "display_name": "Bill Pay",
            "description": "Pay a registered biller.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "bill_pay"
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_create_service_duplicate_code_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a service code cannot be reused within the same tenant"""
    await _seed_service(db_session, str(test_tenant.id), "p2p")
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "p2p",
            "display_name": "Duplicate",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "service_code_already_exists"


@pytest.mark.asyncio
async def test_create_service_rejects_invalid_code(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a service code must follow the allowed format"""
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "P2P",
            "display_name": "Bad case",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_service_display_name_and_status(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can rename a service and change its status without changing its code"""
    svc = await _seed_service(db_session, str(test_tenant.id), "p2p", "P2P")
    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"display_name": "Peer-to-Peer", "status": "disabled"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Peer-to-Peer"
    assert body["status"] == "disabled"
    assert body["code"] == "p2p"


@pytest.mark.asyncio
async def test_patch_unknown_service_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify editing a service that does not exist is reported as not found"""
    resp = await async_client.patch(
        f"/api/v1/services/{uuid4()}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"display_name": "x"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_rejects_code_field(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot change a service's code through an edit"""
    svc = await _seed_service(db_session, str(test_tenant.id), "p2p")
    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"code": "renamed"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_service_removes_from_list(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a deleted service no longer appears in the catalog"""
    svc = await _seed_service(db_session, str(test_tenant.id), "p2p")
    delete_resp = await async_client.delete(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert delete_resp.status_code == 200

    list_resp = await async_client.get(
        "/api/v1/services",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_then_recreate_same_code_succeeds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a deleted service code can be added again"""
    svc = await _seed_service(db_session, str(test_tenant.id), "p2p")
    await async_client.delete(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    create_resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "p2p",
            "display_name": "Reborn",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
