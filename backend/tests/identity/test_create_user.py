"""Tests for POST /api/v1/identity/users.

Covers happy path, validation, duplicate identifier rejection (Pay-PRD-0070),
and cross-tenant identifier reuse (allowed — Pay-PRD-0070 is per-tenant).
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_create_user_happy_path(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """A valid payload creates a user with the requested identifier."""
    response = await async_client.post(
        "/api/v1/identity/users",
        json={
            "tenant_id": str(test_tenant.id),
            "identifiers": [
                {
                    "identifier_type": "phone",
                    "identifier_value": "+27 82 555 0142",
                    "verified": True,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tenant_id"] == str(test_tenant.id)
    assert body["status"] == "active"
    assert len(body["identifiers"]) == 1
    assert body["identifiers"][0]["identifier_value"] == "+27 82 555 0142"


@pytest.mark.asyncio
async def test_create_user_rejects_unknown_tenant(async_client: AsyncClient) -> None:
    """Unknown tenant_id returns 404 tenant_not_found."""
    response = await async_client.post(
        "/api/v1/identity/users",
        json={
            "tenant_id": str(uuid4()),
            "identifiers": [
                {"identifier_type": "phone", "identifier_value": "+27 82 555 9999"}
            ],
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "tenant_not_found"


@pytest.mark.asyncio
async def test_create_user_validates_empty_identifiers(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Empty identifiers list fails Pydantic validation (422)."""
    response = await async_client.post(
        "/api/v1/identity/users",
        json={"tenant_id": str(test_tenant.id), "identifiers": []},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_user_validates_identifier_type(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Unknown identifier_type fails Pydantic Literal validation."""
    response = await async_client.post(
        "/api/v1/identity/users",
        json={
            "tenant_id": str(test_tenant.id),
            "identifiers": [
                {"identifier_type": "passport", "identifier_value": "X1234567"}
            ],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_phone_in_same_tenant(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Re-registering the same phone within one tenant returns 409 (Pay-PRD-0070)."""
    payload = {
        "tenant_id": str(test_tenant.id),
        "identifiers": [
            {"identifier_type": "phone", "identifier_value": "+27 82 555 0001"}
        ],
    }
    first = await async_client.post("/api/v1/identity/users", json=payload)
    assert first.status_code == 201

    second = await async_client.post("/api/v1/identity/users", json=payload)
    assert second.status_code == 409
    body = second.json()
    assert body["error_code"] == "identifier_already_in_use"


@pytest.mark.asyncio
async def test_create_user_allows_same_phone_in_different_tenant(
    async_client: AsyncClient, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """The unique constraint is per-tenant, not global."""
    phone = "+27 82 555 0002"
    a = await async_client.post(
        "/api/v1/identity/users",
        json={
            "tenant_id": str(test_tenant.id),
            "identifiers": [
                {"identifier_type": "phone", "identifier_value": phone}
            ],
        },
    )
    assert a.status_code == 201, a.text

    b = await async_client.post(
        "/api/v1/identity/users",
        json={
            "tenant_id": str(other_tenant.id),
            "identifiers": [
                {"identifier_type": "phone", "identifier_value": phone}
            ],
        },
    )
    assert b.status_code == 201, b.text
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.asyncio
async def test_create_user_with_profile(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Optional profile data is accepted and persisted."""
    response = await async_client.post(
        "/api/v1/identity/users",
        json={
            "tenant_id": str(test_tenant.id),
            "identifiers": [
                {"identifier_type": "email", "identifier_value": "jane@example.com"}
            ],
            "profile": {
                "first_name": "Jane",
                "last_name": "Mokoena",
                "date_of_birth": "1989-04-21",
            },
        },
    )
    assert response.status_code == 201, response.text
