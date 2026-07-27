"""Gating administrator actions by role.

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
    """Verify an administrator action is rejected without a sign-in"""
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
    """Verify an administrator without the right role is refused"""
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
    """Verify a platform administrator can perform a privileged action"""
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
    """Verify a finance reviewer can view pending items"""
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
    """Verify an administrator with no role cannot view pending items"""
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
    """Verify an expired administrator sign-in is rejected"""
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
    """Verify a malformed administrator sign-in is rejected safely"""
    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        headers={"Authorization": "Bearer not.a.real.jwt"},
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    assert response.status_code == 401
