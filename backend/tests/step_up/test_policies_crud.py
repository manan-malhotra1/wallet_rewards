"""Tests for the admin CRUD endpoints on /api/v1/step-up/policies."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_create_policy_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """POST /policies returns 201 + the persisted row."""
    response = await async_client.post(
        "/api/v1/step-up/policies",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "transaction_type": "p2p",
            "currency": "ZAR",
            "threshold_amount": "200",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["transaction_type"] == "p2p"
    assert body["currency"] == "ZAR"


@pytest.mark.asyncio
async def test_create_policy_duplicate_returns_409(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """The (tenant, txn_type, currency) unique index blocks a second insert."""
    payload = {
        "tenant_id": str(test_tenant.id),
        "transaction_type": "p2p",
        "currency": "ZAR",
        "threshold_amount": "200",
    }
    first = await async_client.post(
        "/api/v1/step-up/policies", headers=admin_auth_header, json=payload
    )
    assert first.status_code == 201
    second = await async_client.post(
        "/api/v1/step-up/policies", headers=admin_auth_header, json=payload
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "step_up_policy_exists"


@pytest.mark.asyncio
async def test_create_policy_rejects_negative_threshold(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Pydantic ge=0 → negative threshold → 422."""
    response = await async_client.post(
        "/api/v1/step-up/policies",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "transaction_type": "p2p",
            "currency": "ZAR",
            "threshold_amount": "-1",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_policies_returns_only_tenant_rows(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """List endpoint is tenant-scoped — no cross-tenant leakage."""
    await async_client.post(
        "/api/v1/step-up/policies",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "transaction_type": "p2p",
            "currency": "ZAR",
            "threshold_amount": "100",
        },
    )
    await async_client.post(
        "/api/v1/step-up/policies",
        headers=admin_auth_header,
        json={
            "tenant_id": str(other_tenant.id),
            "transaction_type": "p2p",
            "currency": "ZAR",
            "threshold_amount": "500",
        },
    )
    response = await async_client.get(
        "/api/v1/step-up/policies",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert float(rows[0]["threshold_amount"]) == 100


@pytest.mark.asyncio
async def test_delete_policy_cross_tenant_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Deleting another tenant's policy must return 404 (no existence leak)."""
    create = await async_client.post(
        "/api/v1/step-up/policies",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "transaction_type": "p2p",
            "currency": "ZAR",
            "threshold_amount": "200",
        },
    )
    policy_id = create.json()["id"]

    response = await async_client.delete(
        f"/api/v1/step-up/policies/{policy_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(other_tenant.id)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_policy_unknown_id_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Unknown policy id → 404."""
    response = await async_client.delete(
        f"/api/v1/step-up/policies/{uuid4()}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 404
