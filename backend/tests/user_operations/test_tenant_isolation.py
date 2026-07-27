"""User changes stay within one tenant."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant
from tests.user_operations.conftest import (
    approve,
    create_user_payload,
    ops_url,
    propose,
)


@pytest.mark.asyncio
async def test_get_from_other_tenant_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify one tenant cannot see another tenant's user change"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    resp = await async_client.get(
        ops_url(other_tenant, f"/{proposed['id']}"), headers=maker_header
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_from_other_tenant_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify one tenant cannot approve another tenant's user change"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    resp = await approve(async_client, other_tenant, proposed["id"], checker_header)
    assert resp.status_code == 404
