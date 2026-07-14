"""Tests for the per-rule GET / PATCH / DELETE endpoints + budget_scope.

DELETE is soft — sets status='inactive'. Hard-delete is rejected by the
FK on `reward_events.rule_id` once the rule has fired.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    BUDGET_STATUS_ACTIVE,
    BUDGET_WINDOW_ROLLING_24H,
    RewardBudget,
    Rule,
    Tenant,
)


async def _create_rule(client: AsyncClient, tenant: Tenant, name: str) -> str:
    """Helper — create a first_time rule and return its id."""
    resp = await client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(tenant.id),
            "name": name,
            "rule_type": "first_time",
            "transaction_type": "fund",
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# -----------------------------------------------------------------------------
# GET /rules/{rule_id}
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_rule_returns_full_payload(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Single-rule fetch returns all fields including type-specific ones."""
    rule_id = await _create_rule(async_client, test_tenant, "fetchable")
    resp = await async_client.get(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == rule_id
    assert body["name"] == "fetchable"
    assert body["rule_type"] == "first_time"


@pytest.mark.asyncio
async def test_get_rule_cross_tenant_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Fetching a rule from another tenant must return 404."""
    rule_id = await _create_rule(async_client, test_tenant, "cross-tenant-fetch")
    resp = await async_client.get(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(other_tenant.id)},
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# PATCH /rules/{rule_id}
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_rule_updates_reward_value(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Changing reward_value persists + the GET reflects it."""
    rule_id = await _create_rule(async_client, test_tenant, "patchable")
    resp = await async_client.patch(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(test_tenant.id)},
        json={"reward_value": "250"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reward_value"] == "250.000000"


@pytest.mark.asyncio
async def test_patch_rule_rejects_zero_reward(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """reward_value <= 0 → 422."""
    rule_id = await _create_rule(async_client, test_tenant, "zero-reward")
    resp = await async_client.patch(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(test_tenant.id)},
        json={"reward_value": "0"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_rule_cross_tenant_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Patching another tenant's rule must return 404 — no existence leak."""
    rule_id = await _create_rule(async_client, test_tenant, "cross-tenant-patch")
    resp = await async_client.patch(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(other_tenant.id)},
        json={"name": "stolen"},
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# DELETE /rules/{rule_id}
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_rule_soft_deletes(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """DELETE returns 204 and the row keeps existing with status='inactive'."""
    rule_id = await _create_rule(async_client, test_tenant, "to-delete")
    resp = await async_client.delete(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 204

    rule = (await db_session.execute(select(Rule).where(Rule.id == rule_id))).scalar_one()
    assert rule.status == "inactive"


@pytest.mark.asyncio
async def test_delete_rule_is_idempotent(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Deleting an already-inactive rule returns 204 (no-op)."""
    rule_id = await _create_rule(async_client, test_tenant, "to-delete-twice")
    a = await async_client.delete(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(test_tenant.id)},
    )
    b = await async_client.delete(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert a.status_code == 204 and b.status_code == 204


@pytest.mark.asyncio
async def test_delete_rule_cross_tenant_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Cross-tenant delete must 404."""
    rule_id = await _create_rule(async_client, test_tenant, "cross-tenant-delete")
    resp = await async_client.delete(
        f"/api/v1/rules/{rule_id}",
        params={"tenant_id": str(other_tenant.id)},
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# budget_scope on the performance endpoint
# -----------------------------------------------------------------------------


async def _seed_budget(
    session: AsyncSession,
    tenant: Tenant,
    *,
    scope_id=None,
    cap: str = "1000",
) -> None:
    """Insert a budget row. scope_id=None → tenant-wide; else per-rule."""
    session.add(
        RewardBudget(
            tenant_id=tenant.id,
            scope_type="rule" if scope_id else "tenant",
            scope_id=scope_id,
            currency="PTS",
            window_type=BUDGET_WINDOW_ROLLING_24H,
            cap_amount=cap,
            status=BUDGET_STATUS_ACTIVE,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_budget_scope_none(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """No budgets configured → budget_scope is 'none'."""
    rule_id = await _create_rule(async_client, test_tenant, "scope-none")
    resp = await async_client.get(
        f"/api/v1/rules/{rule_id}/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.json()["budget_scope"] == "none"


@pytest.mark.asyncio
async def test_budget_scope_tenant_only(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Only a tenant-wide budget → 'tenant_only'."""
    rule_id = await _create_rule(async_client, test_tenant, "scope-tenant")
    await _seed_budget(db_session, test_tenant, scope_id=None)
    resp = await async_client.get(
        f"/api/v1/rules/{rule_id}/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.json()["budget_scope"] == "tenant_only"


@pytest.mark.asyncio
async def test_budget_scope_rule_only(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Only a rule-scoped budget → 'rule_only'."""
    rule_id = await _create_rule(async_client, test_tenant, "scope-rule")
    await _seed_budget(db_session, test_tenant, scope_id=rule_id)
    resp = await async_client.get(
        f"/api/v1/rules/{rule_id}/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.json()["budget_scope"] == "rule_only"


@pytest.mark.asyncio
async def test_budget_scope_both(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Tenant + rule-scoped budgets → 'both'."""
    rule_id = await _create_rule(async_client, test_tenant, "scope-both")
    await _seed_budget(db_session, test_tenant, scope_id=None)
    await _seed_budget(db_session, test_tenant, scope_id=rule_id)
    resp = await async_client.get(
        f"/api/v1/rules/{rule_id}/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.json()["budget_scope"] == "both"


@pytest.mark.asyncio
async def test_budget_scope_batch_endpoint(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Batch endpoint surfaces the same scope info per row."""
    rule_a = await _create_rule(async_client, test_tenant, "batch-a")
    rule_b = await _create_rule(async_client, test_tenant, "batch-b")
    # Tenant-wide budget → both rules get 'tenant_only'.
    await _seed_budget(db_session, test_tenant, scope_id=None)
    # Plus a rule-scoped budget on rule_b → 'both' for rule_b.
    await _seed_budget(db_session, test_tenant, scope_id=rule_b)

    resp = await async_client.get(
        "/api/v1/rules/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    rows = {r["rule_id"]: r["budget_scope"] for r in resp.json()}
    assert rows[rule_a] == "tenant_only"
    assert rows[rule_b] == "both"
