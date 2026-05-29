"""Tests for `get_current_admin` + `require_admin_role` as a FastAPI dependency.

Exercises the dependency end-to-end through an httpx request to a
reconciliation endpoint (which we picked as the Phase F.1 pilot surface).
"""
from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_missing_authorization(
    async_client: AsyncClient,
) -> None:
    """Hitting an admin endpoint with no Authorization header → 401."""
    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(uuid4()), "threshold_minutes": 5},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "invalid_authorization_header"


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_wrong_role(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Sweep requires platform-admin — support-agent gets 403."""
    token = make_admin_token(roles=["support-agent"])
    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        headers={"Authorization": f"Bearer {token}"},
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "insufficient_role"


@pytest.mark.asyncio
async def test_admin_endpoint_accepts_platform_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Same call with platform-admin → 200."""
    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "scanned_count" in body


@pytest.mark.asyncio
async def test_read_endpoint_accepts_finance_reviewer(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Read endpoints (pending list) accept finance-reviewer."""
    token = make_admin_token(roles=["finance-reviewer"])
    response = await async_client.get(
        "/api/v1/reconciliation/pending",
        params={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_read_endpoint_rejects_no_role(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Token with empty roles → 403 on read endpoint."""
    token = make_admin_token(roles=[])
    response = await async_client.get(
        "/api/v1/reconciliation/pending",
        params={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "insufficient_role"


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_expired_token(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Expired token → 401 token_expired."""
    token = make_admin_token(roles=["platform-admin"], exp_seconds=-10)
    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        headers={"Authorization": f"Bearer {token}"},
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "token_expired"


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_garbage_token(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Random string as token → 401, not 500."""
    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        headers={"Authorization": "Bearer not.a.real.jwt"},
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    assert response.status_code == 401
