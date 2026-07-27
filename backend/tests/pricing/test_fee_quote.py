"""Fee preview quote for any service.

`POST /api/v1/pricing/quote` previews the service charge for ANY service by
its code (== transaction_type), so new services need no new route. These
tests cover the happy path, the genericity guarantees (unconfigured service,
currency-derived account scope, explicit override), auth, validation, and
tenant isolation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Tenant,
)

QUOTE_URL = "/api/v1/pricing/quote"


async def _seed_pricing(
    session: AsyncSession,
    *,
    tenant_id,
    transaction_type: str,
    account_type: str,
    currency: str,
    fixed_fee: Decimal = Decimal("0"),
    variable_fee_pct: Decimal = Decimal("0"),
    fee_cap: Decimal | None = None,
) -> None:
    """Insert a pricing config and COMMIT so the endpoint's session sees it."""
    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type=transaction_type,
            account_type=account_type,
            currency=currency,
            fixed_fee=fixed_fee,
            variable_fee_pct=variable_fee_pct,
            fee_cap=fee_cap,
        ),
    )
    await session.commit()


@pytest.mark.asyncio
async def test_quote_returns_configured_fixed_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify the fee quoted for a transfer matches the configured price."""
    await _seed_pricing(
        db_session,
        tenant_id=test_tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        fixed_fee=Decimal("2"),
    )

    resp = await async_client.post(
        QUOTE_URL,
        headers=alice_auth_header,
        json={"service": "p2p", "amount": "25", "currency": "ZAR"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "p2p"
    assert Decimal(str(body["fee"])) == Decimal("2.000000")
    assert Decimal(str(body["total"])) == Decimal("27.000000")
    assert body["currency"] == "ZAR"


@pytest.mark.asyncio
async def test_quote_variable_fee_scales_with_amount(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a percentage-based fee grows with the transfer amount."""
    await _seed_pricing(
        db_session,
        tenant_id=test_tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        variable_fee_pct=Decimal("0.01"),  # 1%
    )

    resp = await async_client.post(
        QUOTE_URL,
        headers=alice_auth_header,
        json={"service": "p2p", "amount": "1000", "currency": "ZAR"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(str(body["fee"])) == Decimal("10.000000")  # 1% of 1000
    assert Decimal(str(body["total"])) == Decimal("1010.000000")


@pytest.mark.asyncio
async def test_quote_unconfigured_service_returns_zero(
    async_client: AsyncClient,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a service with no configured price previews a zero fee."""
    resp = await async_client.post(
        QUOTE_URL,
        headers=alice_auth_header,
        json={"service": "cashin", "amount": "25", "currency": "ZAR"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "cashin"
    assert Decimal(str(body["fee"])) == Decimal("0")
    assert Decimal(str(body["total"])) == Decimal("25")


@pytest.mark.asyncio
async def test_quote_derives_points_account_for_pts_currency(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a points redemption is quoted its own configured fee."""
    await _seed_pricing(
        db_session,
        tenant_id=test_tenant.id,
        transaction_type="redemption",
        account_type=ACCOUNT_TYPE_POINTS,
        currency="PTS",
        fixed_fee=Decimal("3"),
    )

    resp = await async_client.post(
        QUOTE_URL,
        headers=alice_auth_header,
        json={"service": "redemption", "amount": "100", "currency": "PTS"},
    )

    assert resp.status_code == 200
    assert Decimal(str(resp.json()["fee"])) == Decimal("3.000000")


@pytest.mark.asyncio
async def test_quote_honors_explicit_account_type_override(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a caller can preview the fee for a specific account type.

    The config is keyed on (ZAR, points_account) — which the ZAR default
    (financial_wallet) would miss; passing account_type explicitly hits it.
    """
    await _seed_pricing(
        db_session,
        tenant_id=test_tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_POINTS,
        currency="ZAR",
        fixed_fee=Decimal("7"),
    )

    # Default derivation (ZAR -> financial_wallet) finds no config -> fee 0.
    default_resp = await async_client.post(
        QUOTE_URL,
        headers=alice_auth_header,
        json={"service": "p2p", "amount": "10", "currency": "ZAR"},
    )
    assert Decimal(str(default_resp.json()["fee"])) == Decimal("0")

    # Explicit override hits the points-account config.
    override_resp = await async_client.post(
        QUOTE_URL,
        headers=alice_auth_header,
        json={
            "service": "p2p",
            "amount": "10",
            "currency": "ZAR",
            "account_type": ACCOUNT_TYPE_POINTS,
        },
    )
    assert override_resp.status_code == 200
    assert Decimal(str(override_resp.json()["fee"])) == Decimal("7.000000")


@pytest.mark.asyncio
async def test_quote_requires_auth(async_client: AsyncClient) -> None:
    """Verify a fee quote cannot be requested without signing in."""
    resp = await async_client.post(
        QUOTE_URL,
        json={"service": "p2p", "amount": "25", "currency": "ZAR"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_quote_rejects_non_positive_amount(
    async_client: AsyncClient, alice_auth_header: dict[str, str]
) -> None:
    """Verify a fee quote for a zero or negative amount is rejected."""
    resp = await async_client.post(
        QUOTE_URL,
        headers=alice_auth_header,
        json={"service": "p2p", "amount": "0", "currency": "ZAR"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_quote_does_not_leak_other_tenant_pricing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    other_tenant: Tenant,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify one tenant cannot see or use another tenant's pricing."""
    await _seed_pricing(
        db_session,
        tenant_id=other_tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        fixed_fee=Decimal("99"),
    )

    # alice belongs to test_tenant, which has no p2p config → fee 0, not 99.
    resp = await async_client.post(
        QUOTE_URL,
        headers=alice_auth_header,
        json={"service": "p2p", "amount": "25", "currency": "ZAR"},
    )

    assert resp.status_code == 200
    assert Decimal(str(resp.json()["fee"])) == Decimal("0")
