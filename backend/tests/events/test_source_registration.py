"""Event source registration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_register_source_happy_path(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify a new event source can be registered and is immediately active"""
    response = await async_client.post(
        "/api/v1/events/sources",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Sasai Bank Receipts",
            "source_key": "sasai-bank-receipts",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_key"] == "sasai-bank-receipts"
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_register_source_rejects_duplicate_key(
    async_client: AsyncClient, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Verify an event source key cannot be registered twice"""
    first = await async_client.post(
        "/api/v1/events/sources",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Source A",
            "source_key": "shared-key",
        },
    )
    assert first.status_code == 201

    second = await async_client.post(
        "/api/v1/events/sources",
        json={
            "tenant_id": str(other_tenant.id),
            "name": "Source B",
            "source_key": "shared-key",
        },
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "source_key_already_in_use"


@pytest.mark.asyncio
async def test_register_source_rejects_unknown_tenant(
    async_client: AsyncClient,
) -> None:
    """Verify an event source cannot be registered for an unknown tenant"""
    response = await async_client.post(
        "/api/v1/events/sources",
        json={
            "tenant_id": str(uuid4()),
            "name": "Source",
            "source_key": "unknown-tenant-source",
        },
    )
    assert response.status_code == 404
