"""Tests for POST /api/v1/rules (Phase C rule CRUD)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_create_first_time_rule_happy_path(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """A valid first_time rule persists with status='active'."""
    response = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "First top-up bonus",
            "rule_type": "first_time",
            "transaction_type": "top_up",
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rule_type"] == "first_time"
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_create_milestone_rule_happy_path(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """A valid milestone rule with threshold persists."""
    response = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "5 P2P milestone",
            "rule_type": "milestone",
            "transaction_type": "p2p",
            "count_threshold": 5,
            "reward_type": "points",
            "reward_value": "200",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["count_threshold"] == 5


@pytest.mark.asyncio
async def test_create_milestone_rule_requires_count_threshold(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Milestone without count_threshold fails validation."""
    response = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Bad milestone",
            "rule_type": "milestone",
            "transaction_type": "p2p",
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_first_time_rule_rejects_count_threshold(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """First-time rules must NOT specify count_threshold."""
    response = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Bad first-time",
            "rule_type": "first_time",
            "transaction_type": "top_up",
            "count_threshold": 1,
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_rule_rejects_unknown_tenant(
    async_client: AsyncClient,
) -> None:
    """Unknown tenant_id → 404."""
    response = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(uuid4()),
            "name": "Rule",
            "rule_type": "first_time",
            "transaction_type": "top_up",
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_rules_returns_only_tenant_rules(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """GET /rules filters by tenant_id — no cross-tenant leakage."""
    # Create rule in test_tenant.
    await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Tenant A rule",
            "rule_type": "first_time",
            "transaction_type": "top_up",
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    # Create rule in other_tenant.
    await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(other_tenant.id),
            "name": "Tenant B rule",
            "rule_type": "first_time",
            "transaction_type": "top_up",
            "reward_type": "points",
            "reward_value": "75",
        },
    )

    response = await async_client.get(
        "/api/v1/rules", params={"tenant_id": str(test_tenant.id)}
    )
    assert response.status_code == 200
    names = [r["name"] for r in response.json()]
    assert names == ["Tenant A rule"]
