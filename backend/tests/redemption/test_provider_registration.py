"""Redemption provider setup — onboarding reward partners."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_PROVIDER_REDEMPTION,
    Account,
    Tenant,
)


@pytest.mark.asyncio
async def test_register_provider_creates_wallet(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify registering a redemption provider sets up its rewards wallet automatically"""
    response = await async_client.post(
        "/api/v1/redemption/providers",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Mukuru Voucher",
            "max_retries": 3,
            "retry_interval_secs": 300,
            "escalate_after_mins": 60,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Mukuru Voucher"
    assert body["status"] == "active"

    # Verify the wallet account was created and matches.
    wallet = (
        await db_session.execute(
            select(Account).where(Account.id == body["redemption_wallet_account_id"])
        )
    ).scalar_one_or_none()
    assert wallet is not None
    assert wallet.account_type == ACCOUNT_TYPE_PROVIDER_REDEMPTION
    assert wallet.currency == "PTS"
    assert wallet.user_id is None


@pytest.mark.asyncio
async def test_register_provider_rejects_unknown_tenant(
    async_client: AsyncClient,
) -> None:
    """Verify a provider cannot be registered under a business that does not exist"""
    response = await async_client.post(
        "/api/v1/redemption/providers",
        json={
            "tenant_id": str(uuid4()),
            "name": "Some Provider",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "tenant_not_found"
