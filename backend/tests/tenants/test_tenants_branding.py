"""Per-tenant branding columns persist and round-trip, plus the admin API.

The branding fields (`brand_accent_color`, `brand_light_color`,
`brand_icon_url`, `brand_glass_transparency`) drive the admin UI's per-tenant
theme. They must persist a set value and default to NULL when never assigned,
so the UI can distinguish a branded tenant from one that should fall back to
the app default. The GET/PUT `/api/v1/tenants/{id}/branding` endpoints
(platform-admin only, direct cosmetic edit) let operators read and change them.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_branding_fields_round_trip(db_session: AsyncSession) -> None:
    """Verify a tenant's brand colours and logo URL are saved and read back unchanged"""
    tenant = Tenant(
        name=f"branded-{uuid4().hex[:8]}",
        business_type="both",
        base_currency="ZAR",
        brand_accent_color="#243B8F",
        brand_light_color="#FFF0C9",
        brand_icon_url="https://cdn.example.com/logos/sasai-za.png",
    )
    db_session.add(tenant)
    await db_session.commit()

    db_session.expunge_all()
    fetched = (await db_session.execute(select(Tenant).where(Tenant.id == tenant.id))).scalar_one()

    assert fetched.brand_accent_color == "#243B8F"
    assert fetched.brand_light_color == "#FFF0C9"
    assert fetched.brand_icon_url == "https://cdn.example.com/logos/sasai-za.png"


@pytest.mark.asyncio
async def test_branding_fields_default_to_null(db_session: AsyncSession) -> None:
    """Verify a tenant created without any brand set leaves all three branding fields empty"""
    tenant = Tenant(
        name=f"unbranded-{uuid4().hex[:8]}",
        business_type="both",
        base_currency="ZAR",
    )
    db_session.add(tenant)
    await db_session.commit()

    db_session.expunge_all()
    fetched = (await db_session.execute(select(Tenant).where(Tenant.id == tenant.id))).scalar_one()

    assert fetched.brand_accent_color is None
    assert fetched.brand_light_color is None
    assert fetched.brand_icon_url is None


# -----------------------------------------------------------------------------
# GET / PUT /api/v1/tenants/{id}/branding — platform-admin, direct cosmetic edit
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_branding_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a platform admin can read a tenant's current branding"""
    resp = await async_client.get(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "brand_accent_color",
        "brand_light_color",
        "brand_icon_url",
        "brand_glass_transparency",
    }


@pytest.mark.asyncio
async def test_put_branding_persists_and_returns(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Verify a platform admin can set a tenant's brand colours and logo, and they stick"""
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={
            "brand_accent_color": "#243B8F",
            "brand_light_color": "#FFF0C9",
            "brand_icon_url": "https://cdn.example.com/logos/sasai.png",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["brand_accent_color"] == "#243B8F"
    assert body["brand_light_color"] == "#FFF0C9"
    assert body["brand_icon_url"] == "https://cdn.example.com/logos/sasai.png"

    db_session.expunge_all()
    fetched = (
        await db_session.execute(select(Tenant).where(Tenant.id == test_tenant.id))
    ).scalar_one()
    assert fetched.brand_accent_color == "#243B8F"
    assert fetched.brand_light_color == "#FFF0C9"
    assert fetched.brand_icon_url == "https://cdn.example.com/logos/sasai.png"


@pytest.mark.asyncio
async def test_put_branding_null_clears_a_field(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify sending null for a branding field clears it back to the app default"""
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={
            "brand_accent_color": None,
            "brand_light_color": None,
            "brand_icon_url": None,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["brand_accent_color"] is None
    assert body["brand_light_color"] is None
    assert body["brand_icon_url"] is None


@pytest.mark.asyncio
async def test_get_branding_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Verify a signed-out user cannot read a tenant's branding"""
    resp = await async_client.get(f"/api/v1/tenants/{test_tenant.id}/branding")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_put_branding_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Verify a signed-out user cannot change a tenant's branding"""
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        json={"brand_accent_color": "#243B8F"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_put_branding_wrong_role_forbidden(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify an admin without the platform-admin role cannot change branding"""
    token = make_admin_token(roles=["support-agent"])
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers={"Authorization": f"Bearer {token}"},
        json={"brand_accent_color": "#243B8F"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_branding_unknown_tenant_returns_404(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify reading branding for a tenant that does not exist is reported as not found"""
    resp = await async_client.get(
        f"/api/v1/tenants/{uuid4()}/branding",
        headers=admin_auth_header,
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "tenant_not_found"


@pytest.mark.asyncio
async def test_put_branding_unknown_tenant_returns_404(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify changing branding for a tenant that does not exist is reported as not found"""
    resp = await async_client.put(
        f"/api/v1/tenants/{uuid4()}/branding",
        headers=admin_auth_header,
        json={"brand_accent_color": "#243B8F"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_put_branding_rejects_malformed_hex_colour(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a colour that is not valid hex is rejected before anything is saved"""
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={"brand_accent_color": "teal"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_branding_rejects_non_http_icon_url(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a logo URL that is not http(s) is rejected before anything is saved"""
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={"brand_icon_url": "javascript:alert(1)"},
    )
    assert resp.status_code == 422


# -----------------------------------------------------------------------------
# brand_glass_transparency — 0-100 slider driving the glassmorphism panel alpha
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_branding_sets_and_reads_glass_transparency(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Verify a platform admin can set the glass transparency slider and it sticks"""
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={"brand_glass_transparency": 30},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["brand_glass_transparency"] == 30

    get_resp = await async_client.get(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["brand_glass_transparency"] == 30

    db_session.expunge_all()
    fetched = (
        await db_session.execute(select(Tenant).where(Tenant.id == test_tenant.id))
    ).scalar_one()
    assert fetched.brand_glass_transparency == 30


@pytest.mark.asyncio
async def test_put_branding_rejects_glass_transparency_above_100(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a transparency value above the 0-100 range is rejected as invalid"""
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={"brand_glass_transparency": 101},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_branding_rejects_glass_transparency_below_zero(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a negative transparency value is rejected as invalid"""
    resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={"brand_glass_transparency": -1},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_branding_null_clears_glass_transparency(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify sending null for the transparency field clears it back to the default"""
    set_resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={"brand_glass_transparency": 30},
    )
    assert set_resp.status_code == 200, set_resp.text

    clear_resp = await async_client.put(
        f"/api/v1/tenants/{test_tenant.id}/branding",
        headers=admin_auth_header,
        json={"brand_glass_transparency": None},
    )
    assert clear_resp.status_code == 200, clear_resp.text
    assert clear_resp.json()["brand_glass_transparency"] is None
