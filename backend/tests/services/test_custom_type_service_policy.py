"""A custom user type must be grantable on a service's access policy.

`services.allowed_user_types` was the fifth table left behind when user types
became runtime data. Its Pydantic validator checked every element against the
five-element `USER_TYPES` tuple, so a tenant's own type was refused with a 422
even though the admin UI offers every active catalog type as a chip.

The consequence is worse than a rejected form. `identity.list_my_services` and
`services.assert_service_allowed` gate access with membership of that array, so
a user carrying a custom type was permanently locked out of every service with
a restricted allow-list — with no way for an operator to add them.

Migration 0064 made the same trade for the four config tables: a static
allowlist the database could not keep current is replaced by service-layer
validation that reads the tenant's live catalog. `services` carries no CHECK on
`allowed_user_types` (see `\\d services` / migration 0049 — the column was added
unconstrained), so this fix is code-only.

These tests pin both halves of the trade:
  - a custom type can be granted at create and at patch, and a user of that
    type then sees the service (the feature), and
  - a bogus type, and another tenant's custom type, are still refused with a
    422 `unknown_user_type` (the guarantee).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.service import list_my_services
from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type
from app.shared.models import CATEGORY_RETAIL, Service, Tenant

pytestmark = pytest.mark.asyncio

# A code that is not one of the five seeded system types, so the old tuple
# validator rejected it outright.
CUSTOM = "distributor"
BOGUS = "no_such_type"


async def _make_custom_type(session: AsyncSession, tenant: Tenant, code: str = CUSTOM) -> str:
    """Create an active, tenant-owned Retail type and return its code.

    Args:
        session: Async DB session (the call commits).
        tenant: The tenant that owns the type.
        code: The type code to create.

    Returns:
        The created type's code, for use in an allow-list.
    """
    await create_user_type(
        session,
        UserTypeCreateRequest(
            tenant_id=tenant.id,
            code=code,
            label=code.title(),
            category_code=CATEGORY_RETAIL,
        ),
    )
    return code


async def _seed_service(
    session: AsyncSession,
    tenant: Tenant,
    code: str,
    *,
    allowed_user_types: list[str] | None = None,
    allowed_channels: list[str] | None = None,
) -> Service:
    """Insert one base service row directly, bypassing the create endpoint.

    Args:
        session: Async DB session (the call commits).
        tenant: The owning tenant.
        code: The service code.
        allowed_user_types: The WHO allow-list, or None for unrestricted.
        allowed_channels: The HOW allow-list, or None for unrestricted.

    Returns:
        The persisted `Service` row.
    """
    svc = Service(
        tenant_id=tenant.id,
        code=code,
        display_name=code.upper(),
        allowed_user_types=allowed_user_types,
        allowed_channels=allowed_channels,
    )
    session.add(svc)
    await session.commit()
    await session.refresh(svc)
    return svc


async def test_custom_type_can_be_granted_on_an_existing_service(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an operator can add a tenant's own type to a service allow-list"""
    custom = await _make_custom_type(db_session, test_tenant)
    svc = await _seed_service(db_session, test_tenant, "cashout", allowed_user_types=["consumer"])

    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"allowed_user_types": ["consumer", custom]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed_user_types"] == ["consumer", custom]

    await db_session.refresh(svc)
    assert svc.allowed_user_types == ["consumer", custom]


async def test_a_user_of_a_custom_type_then_reaches_the_service(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify granting the type actually unlocks the service for that user type

    The 422 was only the visible half. `list_my_services` gates on membership of
    `allowed_user_types`, so before the grant is possible a custom-type user is
    locked out of every restricted service.
    """
    custom = await _make_custom_type(db_session, test_tenant)
    tenant_id = test_tenant.id
    svc = await _seed_service(
        db_session,
        test_tenant,
        "cashout",
        allowed_user_types=["consumer"],
        allowed_channels=["mobile"],
    )

    # Before the grant the custom type sees nothing.
    assert await list_my_services(db_session, tenant_id=tenant_id, user_type=custom) == []

    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(tenant_id)},
        headers=admin_auth_header,
        json={"allowed_user_types": ["consumer", custom]},
    )
    assert resp.status_code == 200, resp.text

    # The endpoint committed on its own session; drop this one's cached copy so
    # the re-query reads the row the endpoint actually wrote.
    await db_session.refresh(svc)
    visible = await list_my_services(db_session, tenant_id=tenant_id, user_type=custom)
    assert [s.code for s in visible] == ["cashout"]


async def test_custom_type_can_be_set_when_creating_a_derived_service(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a new derived service can be restricted to a tenant's own type"""
    custom = await _make_custom_type(db_session, test_tenant)
    await _seed_service(db_session, test_tenant, "cashout")

    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "distributor_cashout",
            "display_name": "Distributor Cash-out",
            "base_service_code": "cashout",
            "allowed_user_types": [custom],
            "allowed_channels": ["mobile"],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["allowed_user_types"] == [custom]


async def test_bogus_user_type_is_still_refused_at_create(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a type that resolves nowhere is still a 422 unknown_user_type"""
    await _seed_service(db_session, test_tenant, "cashout")

    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "bad_policy",
            "display_name": "Bad Policy",
            "base_service_code": "cashout",
            "allowed_user_types": [BOGUS],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "unknown_user_type"


async def test_bogus_user_type_is_still_refused_at_patch(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify patching in a nonexistent type is refused and changes nothing"""
    svc = await _seed_service(db_session, test_tenant, "cashout", allowed_user_types=["consumer"])

    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"allowed_user_types": ["consumer", BOGUS]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "unknown_user_type"

    await db_session.refresh(svc)
    assert svc.allowed_user_types == ["consumer"]


async def test_another_tenants_custom_type_is_refused(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a type owned by a different tenant never resolves here (NFR-0220)"""
    foreign = await _make_custom_type(db_session, other_tenant, code="foreign_type")
    svc = await _seed_service(db_session, test_tenant, "cashout", allowed_user_types=["consumer"])

    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"allowed_user_types": [foreign]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "unknown_user_type"


async def test_retired_custom_type_cannot_be_granted(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a retired type is refused on a new allow-list, like every config write

    `assert_user_type_valid` is deliberately stricter than `get_user_type`: a
    retired type still resolves for reads so existing rows keep rendering, but
    it may not be assigned to anything new (spec §11).
    """
    from app.modules.user_types.service import replace_user_type_for_scope
    from app.shared.models import USER_TYPE_STATUS_RETIRED

    custom = await _make_custom_type(db_session, test_tenant)
    await replace_user_type_for_scope(
        db_session,
        [
            UserTypeCreateRequest(
                tenant_id=test_tenant.id,
                code=custom,
                label=custom.title(),
                category_code=CATEGORY_RETAIL,
                status=USER_TYPE_STATUS_RETIRED,
            )
        ],
    )
    svc = await _seed_service(db_session, test_tenant, "cashout", allowed_user_types=["consumer"])

    resp = await async_client.patch(
        f"/api/v1/services/{svc.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"allowed_user_types": [custom]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "unknown_user_type"
