"""Composite rule setup validation.

Composite rules require `composite_operator` in {AND, OR} and >= 2
sub-conditions; non-composite rules must not carry either. The persistence
of `rule_conditions` is asserted end-to-end via the create endpoint.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import RuleCondition, Tenant


@pytest.mark.asyncio
async def test_create_composite_rule_persists_conditions(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify an admin can create a combined-condition reward rule"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Fund and send combo",
            "rule_type": "composite",
            "composite_operator": "AND",
            "conditions": [
                {"transaction_type": "fund", "count_threshold": 3, "min_amount": "100"},
                {"transaction_type": "send", "count_threshold": 1},
            ],
            "reward_type": "points",
            "reward_value": "250",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["composite_operator"] == "AND"

    conditions = list(
        (
            await db_session.execute(
                select(RuleCondition).where(RuleCondition.rule_id == body["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(conditions) == 2
    assert {c.transaction_type for c in conditions} == {"fund", "send"}


@pytest.mark.asyncio
async def test_composite_without_operator_is_422(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a combined-condition rule is rejected when its and-or-or choice is missing"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "No operator",
            "rule_type": "composite",
            "conditions": [
                {"transaction_type": "fund", "count_threshold": 1},
                {"transaction_type": "send", "count_threshold": 1},
            ],
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_composite_with_single_condition_is_422(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a combined-condition rule is rejected when it has fewer than two conditions"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "One condition",
            "rule_type": "composite",
            "composite_operator": "OR",
            "conditions": [
                {"transaction_type": "fund", "count_threshold": 1},
            ],
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_non_composite_rule_rejects_conditions(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a simple rule is rejected when it carries combined-condition settings"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Milestone with conditions",
            "rule_type": "milestone",
            "transaction_type": "fund",
            "count_threshold": 5,
            "conditions": [
                {"transaction_type": "fund", "count_threshold": 1},
                {"transaction_type": "send", "count_threshold": 1},
            ],
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_non_composite_rule_rejects_composite_operator(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a simple rule is rejected when it carries an and-or-or choice"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": f"ft-{uuid4().hex[:6]}",
            "rule_type": "first_time",
            "transaction_type": "fund",
            "composite_operator": "AND",
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422
