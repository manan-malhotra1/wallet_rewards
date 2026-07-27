"""Step-up policies — admin viewing and change governance.

Step-up policy WRITES now flow exclusively through the config-governance
maker-checker (config type "step_up") — the direct create/delete routes were
retired, so only the tenant list stays here. Write-path behaviour (create /
update / delete via propose→approve, scope guard, payload validation) is
covered in tests/config_requests/test_step_up_operations.py.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import StepUpPolicy, Tenant


async def _seed_policy(
    session: AsyncSession,
    tenant: Tenant,
    *,
    transaction_type: str = "p2p",
    currency: str = "ZAR",
    threshold: str = "100",
) -> StepUpPolicy:
    """Insert a step-up policy row directly (bypassing the maker-checker flow)."""
    policy = StepUpPolicy(
        tenant_id=tenant.id,
        transaction_type=transaction_type,
        currency=currency,
        threshold_amount=Decimal(threshold),
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


@pytest.mark.asyncio
async def test_list_policies_returns_only_tenant_rows(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify one tenant cannot see another tenant's step-up policies."""
    await _seed_policy(db_session, test_tenant, threshold="100")
    await _seed_policy(db_session, other_tenant, threshold="500")

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
async def test_list_policies_requires_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Verify viewing step-up policies requires an admin sign-in."""
    response = await async_client.get(
        "/api/v1/step-up/policies",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_direct_create_endpoint_is_retired(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify step-up policies can no longer be created directly, only through the approval flow."""
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
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_direct_delete_endpoint_is_retired(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify step-up policies can no longer be deleted directly, only through the approval flow.

    The whole `/policies/{policy_id}` path was removed (not just the method), so
    the router no longer matches it → 404 (route gone), unlike POST /policies
    whose path still exists for GET and therefore 405s.
    """
    response = await async_client.delete(
        f"/api/v1/step-up/policies/{uuid4()}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 404
