"""API tests for the read-only user-type catalog endpoint.

Covers the admin gate (401), tenant isolation (another tenant's custom type is
never visible), the `display_order` section ordering the picker relies on, and
the `include_retired` switch.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import USER_TYPE_STATUS_RETIRED, Tenant, UserTypeDef

pytestmark = pytest.mark.asyncio


async def test_list_requires_admin_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify the endpoint is admin-gated — no token, no catalog."""
    response = await async_client.get(f"/api/v1/user-types?tenant_id={test_tenant.id}")
    assert response.status_code == 401


async def test_list_returns_categories_and_types(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the payload carries both categories and the tenant's visible types."""
    db_session.add(
        UserTypeDef(
            tenant_id=other_tenant.id,
            code="franchisee",
            label="Franchisee",
            category_code="retail",
        )
    )
    await db_session.commit()

    response = await async_client.get(
        f"/api/v1/user-types?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["code"] for c in body["categories"]] == ["consumer", "retail", "business"]
    codes = {t["code"] for t in body["types"]}
    assert "agent" in codes
    assert "franchisee" not in codes  # tenant isolation


async def test_types_come_back_in_category_display_order(
    async_client: AsyncClient, test_tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """Verify types are sectioned by `display_order`, not alphabetically by code.

    Alphabetical `category_code` ordering would yield business, consumer, retail.
    Spec §9 renders the sections Consumers → Retail → Business, and the endpoint
    must hand the UI that order so it never re-sorts.
    """
    response = await async_client.get(
        f"/api/v1/user-types?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert response.status_code == 200, response.text
    sections = [t["category_code"] for t in response.json()["types"]]
    # Each category appears as one contiguous run, runs in display_order.
    runs = [code for i, code in enumerate(sections) if i == 0 or sections[i - 1] != code]
    assert runs == ["consumer", "retail", "business"]


async def test_retired_types_are_hidden_unless_requested(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify retired types drop out of the picker but stay fetchable for labels."""
    db_session.add(
        UserTypeDef(
            tenant_id=test_tenant.id,
            code="legacy_agent",
            label="Legacy Agent",
            category_code="retail",
            status=USER_TYPE_STATUS_RETIRED,
        )
    )
    await db_session.commit()

    default = await async_client.get(
        f"/api/v1/user-types?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert "legacy_agent" not in {t["code"] for t in default.json()["types"]}

    with_retired = await async_client.get(
        f"/api/v1/user-types?tenant_id={test_tenant.id}&include_retired=true",
        headers=admin_auth_header,
    )
    assert "legacy_agent" in {t["code"] for t in with_retired.json()["types"]}
