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
    kind: str = "base",
    base_service_code: str | None = None,
) -> Service:
    """Insert a service row directly so individual tests don't depend on POST.

    Defaults to `kind="base"` — this bypasses `ServiceCreateRequest`, so most
    callers (list / patch tests) don't need a base_service_code. Tests that
    need a deletable row must pass `kind="derived"` + `base_service_code`,
    since base rows are undeletable (spec §6).
    """
    svc = Service(
        tenant_id=tenant_id,
        code=code,
        display_name=display_name or code.upper(),
        status=status,
        kind=kind,
        base_service_code=base_service_code,
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
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can add a new derived service to the catalog"""
    await _seed_service(db_session, str(test_tenant.id), "cashout")
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "bill_pay",
            "display_name": "Bill Pay",
            "description": "Pay a registered biller.",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "bill_pay"
    assert body["status"] == "active"
    assert body["kind"] == "derived"
    assert body["base_service_code"] == "cashout"


@pytest.mark.asyncio
async def test_create_service_duplicate_code_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a service code cannot be reused within the same tenant"""
    await _seed_service(db_session, str(test_tenant.id), "cashout")
    await _seed_service(
        db_session,
        str(test_tenant.id),
        "cashout_atm",
        kind="derived",
        base_service_code="cashout",
    )
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "cashout_atm",
            "display_name": "Duplicate",
            "base_service_code": "cashout",
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
async def test_create_service_with_access_policy_persists(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can restrict a new service to given user types and channels"""
    await _seed_service(db_session, str(test_tenant.id), "cashout")
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "agent_cashout",
            "display_name": "Agent Cash-out",
            "base_service_code": "cashout",
            "allowed_user_types": ["agent"],
            "allowed_channels": ["mobile"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["allowed_user_types"] == ["agent"]
    assert body["allowed_channels"] == ["mobile"]

    # DB row carries the policy, not just the response envelope.
    svc = await db_session.get(Service, body["id"])
    assert svc is not None
    assert svc.allowed_user_types == ["agent"]
    assert svc.allowed_channels == ["mobile"]


@pytest.mark.asyncio
async def test_create_service_without_policy_is_unrestricted(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify creating a service without a policy leaves it unrestricted (null)"""
    await _seed_service(db_session, str(test_tenant.id), "cashout")
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "open_service",
            "display_name": "Open Service",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # NULL (unrestricted) is preserved as null, never coerced to [].
    assert body["allowed_user_types"] is None
    assert body["allowed_channels"] is None

    svc = await db_session.get(Service, body["id"])
    assert svc is not None
    assert svc.allowed_user_types is None
    assert svc.allowed_channels is None


@pytest.mark.asyncio
async def test_create_service_rejects_unknown_user_type(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a service cannot be restricted to a user type that does not exist"""
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "bad_policy",
            "display_name": "Bad Policy",
            "allowed_user_types": ["wizard"],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_service_rejects_unknown_channel(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a service cannot be restricted to a channel that does not exist"""
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "bad_channel",
            "display_name": "Bad Channel",
            "allowed_channels": ["telepathy"],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_service_updates_access_policy(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can change who and which channel may use a service"""
    svc = Service(
        tenant_id=test_tenant.id,
        code="p2p",
        display_name="P2P",
        allowed_user_types=["consumer"],
        allowed_channels=["mobile"],
    )
    db_session.add(svc)
    await db_session.commit()
    await db_session.refresh(svc)

    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={
            "allowed_user_types": ["agent", "super_agent"],
            "allowed_channels": ["mobile", "ussd"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed_user_types"] == ["agent", "super_agent"]
    assert body["allowed_channels"] == ["mobile", "ussd"]

    await db_session.refresh(svc)
    assert svc.allowed_user_types == ["agent", "super_agent"]
    assert svc.allowed_channels == ["mobile", "ussd"]


@pytest.mark.asyncio
async def test_patch_display_name_leaves_policy_untouched(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify renaming a service does not wipe its existing access policy"""
    svc = Service(
        tenant_id=test_tenant.id,
        code="p2p",
        display_name="P2P",
        allowed_user_types=["consumer"],
        allowed_channels=["mobile"],
    )
    db_session.add(svc)
    await db_session.commit()
    await db_session.refresh(svc)

    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"display_name": "Peer-to-Peer"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Peer-to-Peer"
    # Policy survives a partial edit that omitted the two allow-lists.
    assert body["allowed_user_types"] == ["consumer"]
    assert body["allowed_channels"] == ["mobile"]

    await db_session.refresh(svc)
    assert svc.allowed_user_types == ["consumer"]
    assert svc.allowed_channels == ["mobile"]


@pytest.mark.asyncio
async def test_patch_service_rejects_unknown_channel(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a service edit cannot introduce a channel that does not exist"""
    svc = await _seed_service(db_session, str(test_tenant.id), "p2p")
    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"allowed_channels": ["carrier_pigeon"]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_service_can_clear_user_types_to_operator_only(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can set an empty user-type list to make a service operator-only"""
    svc = Service(
        tenant_id=test_tenant.id,
        code="fund",
        display_name="Fund",
        allowed_user_types=["consumer"],
        allowed_channels=["mobile"],
    )
    db_session.add(svc)
    await db_session.commit()
    await db_session.refresh(svc)

    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        # [] is a real value (restrict-to-none), distinct from omitting the key.
        json={"allowed_user_types": [], "allowed_channels": ["admin", "api"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed_user_types"] == []
    assert body["allowed_channels"] == ["admin", "api"]

    await db_session.refresh(svc)
    assert svc.allowed_user_types == []
    assert svc.allowed_channels == ["admin", "api"]


@pytest.mark.asyncio
async def test_delete_service_removes_from_list(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a deleted service no longer appears in the catalog"""
    await _seed_service(db_session, str(test_tenant.id), "cashout")
    svc = await _seed_service(
        db_session,
        str(test_tenant.id),
        "cashout_atm",
        kind="derived",
        base_service_code="cashout",
    )
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
    # The base row is undeletable and stays; only the deleted derived row
    # must be gone from the catalog.
    codes = {s["code"] for s in list_resp.json()}
    assert codes == {"cashout"}


@pytest.mark.asyncio
async def test_delete_base_service_is_refused(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a base service cannot be deleted — it ships with the platform"""
    svc = await _seed_service(db_session, str(test_tenant.id), "cashout")
    resp = await async_client.delete(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "base_service_protected"


@pytest.mark.asyncio
async def test_delete_then_recreate_same_code_succeeds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a deleted derived service's code can be added again"""
    await _seed_service(db_session, str(test_tenant.id), "cashout")
    svc = await _seed_service(
        db_session,
        str(test_tenant.id),
        "cashout_atm",
        kind="derived",
        base_service_code="cashout",
    )
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
            "code": "cashout_atm",
            "display_name": "Reborn",
            "base_service_code": "cashout",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
