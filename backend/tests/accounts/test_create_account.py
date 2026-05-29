"""Tests for POST /api/v1/accounts.

Covers happy path for each account type, tenant validation, currency
normalisation, and invalid account_type rejection.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant, User


@pytest.mark.asyncio
async def test_create_financial_wallet_for_user(
    async_client: AsyncClient, test_tenant: Tenant, test_user: User
) -> None:
    """Wallet creation for a user returns 201 with the correct fields."""
    response = await async_client.post(
        "/api/v1/accounts",
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "account_type": "financial_wallet",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_type"] == "financial_wallet"
    assert body["currency"] == "ZAR"
    assert body["user_id"] == str(test_user.id)
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_create_system_points_issuance_account(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """System issuance account has no user_id or merchant_id."""
    response = await async_client.post(
        "/api/v1/accounts",
        json={
            "tenant_id": str(test_tenant.id),
            "account_type": "system_points_issuance",
            "currency": "PTS",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_type"] == "system_points_issuance"
    assert body["user_id"] is None
    assert body["merchant_id"] is None


@pytest.mark.asyncio
async def test_create_account_rejects_unknown_tenant(
    async_client: AsyncClient,
) -> None:
    """Unknown tenant_id → 404 tenant_not_found."""
    response = await async_client.post(
        "/api/v1/accounts",
        json={
            "tenant_id": str(uuid4()),
            "account_type": "financial_wallet",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "tenant_not_found"


@pytest.mark.asyncio
async def test_create_account_validates_account_type(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Unknown account_type fails Pydantic Literal."""
    response = await async_client.post(
        "/api/v1/accounts",
        json={
            "tenant_id": str(test_tenant.id),
            "account_type": "savings_account",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_account_normalises_currency_case(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Currency stored uppercase regardless of input."""
    response = await async_client.post(
        "/api/v1/accounts",
        json={
            "tenant_id": str(test_tenant.id),
            "account_type": "financial_wallet",
            "currency": "zar",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["currency"] == "ZAR"
