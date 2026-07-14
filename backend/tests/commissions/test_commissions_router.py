"""Tests for the read-only commission-config list endpoint (Epic 24 backend).

Config WRITES go through the maker-checker flow; only an admin-gated LIST is
exposed, mirroring the pricing router. Coverage: happy path, auth (401),
permission (403), tenant isolation.
"""

from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import create_commission_config
from app.shared.models import Tenant

pytestmark = pytest.mark.asyncio

URL = "/api/v1/commissions/configs"


async def _seed(session: AsyncSession, tenant_id, transaction_type: str = "cash_in") -> None:
    await create_commission_config(
        session,
        CommissionConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type=transaction_type,
            currency="ZAR",
            fixed_commission=Decimal("1"),
        ),
    )
    await session.commit()


async def test_list_returns_seeded_configs(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    await _seed(db_session, test_tenant.id)
    resp = await async_client.get(
        URL, params={"tenant_id": str(test_tenant.id)}, headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["transaction_type"] == "cash_in"
    assert body[0]["currency"] == "ZAR"


async def test_list_requires_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    resp = await async_client.get(URL, params={"tenant_id": str(test_tenant.id)})
    assert resp.status_code == 401


async def test_list_requires_platform_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    token = make_admin_token(roles=["config-approver"])  # lacks platform-admin
    resp = await async_client.get(
        URL,
        params={"tenant_id": str(test_tenant.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_is_tenant_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    await _seed(db_session, test_tenant.id, "cash_in")
    await _seed(db_session, other_tenant.id, "p2p")
    resp = await async_client.get(
        URL, params={"tenant_id": str(test_tenant.id)}, headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["transaction_type"] == "cash_in"
