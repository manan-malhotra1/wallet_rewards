"""Internal redemption — points → own-wallet value (Module 11b).

Covers the Pay-PRD-1200–1290 acceptance criteria: the happy path posts a
cross-referenced burn/payout pair at the configured rate; the flow FAILS
CLOSED on a missing conversion rate and on missing pricing/limit configs;
an underfunded cashback wallet 409s and the burn is compensated (points come
back); replays are idempotent. Reuses the external-redemption test helpers
(points seeding, config seeding, user session auth).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.redemption.internal import get_or_create_system_account
from app.shared.models import (
    ACCOUNT_TYPE_CASHBACK_PROVIDER,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Account,
    PointsConversionRate,
    Tenant,
    Transaction,
    User,
)
from tests.redemption.test_initiate_redemption import (
    _credit_user_points,
    _seed_redemption_configs,
    _user_auth_header,
)


async def _seed_rate(
    session: AsyncSession,
    tenant: Tenant,
    *,
    currency: str = "ZAR",
    points_per_unit: str = "100",
    value_per_unit: str = "10",
    status: str = "active",
) -> None:
    """Insert a conversion rate row directly (config-request path has own tests)."""
    session.add(
        PointsConversionRate(
            tenant_id=tenant.id,
            currency=currency,
            points_per_unit=Decimal(points_per_unit),
            value_per_unit=Decimal(value_per_unit),
            status=status,
        )
    )
    await session.commit()


async def _ensure_zar_wallet(session: AsyncSession, tenant: Tenant, user: User) -> Account:
    """Fetch-or-create the user's ZAR financial wallet (payout destination)."""
    existing = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.user_id == user.id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                Account.currency == "ZAR",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    await session.commit()
    await session.refresh(wallet)
    return wallet


async def _points_balance(session: AsyncSession, tenant: Tenant, user: User) -> Decimal:
    """The user's derived available points balance."""
    points = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.user_id == user.id,
                Account.account_type == ACCOUNT_TYPE_POINTS,
            )
        )
    ).scalar_one()
    balance, reserved = await derive_balance(session, points.id)
    return balance - reserved


async def _redeem(
    client: AsyncClient,
    user: User,
    *,
    points: str = "200",
    currency: str = "ZAR",
    key: str | None = None,
):
    """POST /redemption/internal as `user`; returns the raw response."""
    return await client.post(
        "/api/v1/redemption/internal",
        json={"points_amount": points, "currency": currency},
        headers={
            **(await _user_auth_header(user)),
            "Idempotency-Key": key or uuid4().hex,
        },
    )


@pytest.mark.asyncio
async def test_internal_redemption_credits_wallet_at_configured_rate(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer converts points into wallet money at the tenant's rate"""
    await _seed_redemption_configs(db_session, test_tenant)
    await _seed_rate(db_session, test_tenant)  # 100 PTS = 10 ZAR
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("500"))
    wallet = await _ensure_zar_wallet(db_session, test_tenant, test_user)

    resp = await _redeem(async_client, test_user, points="200")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["fiat_amount"]) == Decimal("20.00")
    assert body["currency"] == "ZAR"

    # Balances moved on both sides of the pair.
    assert await _points_balance(db_session, test_tenant, test_user) == Decimal("300")
    wallet_bal, _ = await derive_balance(db_session, wallet.id)
    assert wallet_bal == Decimal("20.00")

    # Cross-reference (Pay-PRD-1260): both transactions name the pair row.
    for txn_id in (body["points_transaction_id"], body["payout_transaction_id"]):
        txn = (
            await db_session.execute(select(Transaction).where(Transaction.id == txn_id))
        ).scalar_one()
        assert txn.external_reference == f"internal_redemption:{body['id']}"
        assert txn.status == "COMPLETED"


@pytest.mark.asyncio
async def test_internal_redemption_fails_closed_without_rate(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a redemption into a currency with no configured rate is rejected"""
    await _seed_redemption_configs(db_session, test_tenant)
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("500"))
    await _ensure_zar_wallet(db_session, test_tenant, test_user)

    resp = await _redeem(async_client, test_user)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "conversion_rate_missing"
    # Fail-closed BEFORE any ledger write — the points are untouched.
    assert await _points_balance(db_session, test_tenant, test_user) == Decimal("500")


@pytest.mark.asyncio
async def test_internal_redemption_inactive_rate_fails_closed(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify an INACTIVE rate does not permit redemption"""
    await _seed_redemption_configs(db_session, test_tenant)
    await _seed_rate(db_session, test_tenant, status="inactive")
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("500"))
    await _ensure_zar_wallet(db_session, test_tenant, test_user)

    resp = await _redeem(async_client, test_user)
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "conversion_rate_missing"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_pricing,with_limit", [(False, True), (True, False)])
async def test_internal_redemption_fails_closed_without_configs(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    with_pricing: bool,
    with_limit: bool,
) -> None:
    """Verify the invariant-12 gate rejects when pricing or limits are missing"""
    await _seed_redemption_configs(
        db_session, test_tenant, with_pricing=with_pricing, with_limit=with_limit
    )
    await _seed_rate(db_session, test_tenant)
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("500"))
    await _ensure_zar_wallet(db_session, test_tenant, test_user)

    resp = await _redeem(async_client, test_user)
    assert resp.status_code == 422, resp.text
    assert await _points_balance(db_session, test_tenant, test_user) == Decimal("500")


async def _drain_cashback_wallet(session: AsyncSession, tenant: Tenant) -> None:
    """Debit the pre-funded cashback wallet to exactly zero (floor allows 0)."""
    from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
    from app.shared.models import ACCOUNT_TYPE_OPERATOR_ADJUSTMENT

    wallet = await get_or_create_system_account(
        session,
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_CASHBACK_PROVIDER,
        currency="ZAR",
    )
    mirror = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.currency == "ZAR",
                Account.name == "__test_cashback_seed__",
            )
        )
    ).scalar_one()
    balance, _ = await derive_balance(session, wallet.id)
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"drain-{uuid4().hex}",
            transaction_type="treasury.adjust",
            currency="ZAR",
            amount=balance,
            entries=[
                LedgerEntryRequest(account_id=wallet.id, entry_type="DEBIT", amount=balance),
                LedgerEntryRequest(account_id=mirror.id, entry_type="CREDIT", amount=balance),
            ],
        ),
    )


@pytest.mark.asyncio
async def test_internal_redemption_underfunded_cashback_wallet_compensates_burn(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify an underfunded cashback wallet 409s and the points come back"""
    await _seed_redemption_configs(db_session, test_tenant)
    await _seed_rate(db_session, test_tenant)
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("500"))
    await _ensure_zar_wallet(db_session, test_tenant, test_user)
    # Empty the wallet so the payout trips the choke-point floor AFTER the
    # burn — exercising the compensating unwind.
    await _drain_cashback_wallet(db_session, test_tenant)

    resp = await _redeem(async_client, test_user, points="200")
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "insufficient_cashback_funds"
    # The burn was compensated append-only — full points balance restored.
    assert await _points_balance(db_session, test_tenant, test_user) == Decimal("500")


@pytest.mark.asyncio
async def test_internal_redemption_idempotent_replay(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a replayed Idempotency-Key returns the same pair, no double burn"""
    await _seed_redemption_configs(db_session, test_tenant)
    await _seed_rate(db_session, test_tenant)
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("500"))
    wallet = await _ensure_zar_wallet(db_session, test_tenant, test_user)

    key = uuid4().hex
    first = await _redeem(async_client, test_user, points="200", key=key)
    replay = await _redeem(async_client, test_user, points="200", key=key)
    assert first.status_code == 201 and replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]

    assert await _points_balance(db_session, test_tenant, test_user) == Decimal("300")
    wallet_bal, _ = await derive_balance(db_session, wallet.id)
    assert wallet_bal == Decimal("20.00")


@pytest.mark.asyncio
async def test_internal_redemption_insufficient_points(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify redeeming more points than the balance is rejected"""
    await _seed_redemption_configs(db_session, test_tenant)
    await _seed_rate(db_session, test_tenant)
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("50"))
    await _ensure_zar_wallet(db_session, test_tenant, test_user)

    resp = await _redeem(async_client, test_user, points="200")
    assert resp.status_code == 409, resp.text
    assert await _points_balance(db_session, test_tenant, test_user) == Decimal("50")


@pytest.mark.asyncio
async def test_conversion_rates_listing_returns_active_only(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify the user rates endpoint offers only ACTIVE currencies"""
    await _seed_rate(db_session, test_tenant, currency="ZAR")
    await _seed_rate(
        db_session, test_tenant, currency="INR", points_per_unit="10", status="inactive"
    )

    resp = await async_client.get(
        "/api/v1/redemption/conversion-rates", headers=await _user_auth_header(test_user)
    )
    assert resp.status_code == 200, resp.text
    currencies = [r["currency"] for r in resp.json()]
    assert currencies == ["ZAR"]


@pytest.mark.asyncio
async def test_internal_redemption_requires_user_auth(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the endpoint rejects a request without a user session"""
    resp = await async_client.post(
        "/api/v1/redemption/internal",
        json={"points_amount": "10", "currency": "ZAR"},
        headers={"Idempotency-Key": uuid4().hex, "Authorization": "Bearer not-a-session"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cashback_wallet_lazy_creation_is_idempotent(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify get_or_create returns the SAME cashback wallet on repeat calls"""
    first = await get_or_create_system_account(
        db_session,
        tenant_id=test_tenant.id,
        account_type=ACCOUNT_TYPE_CASHBACK_PROVIDER,
        currency="zar",
    )
    second = await get_or_create_system_account(
        db_session,
        tenant_id=test_tenant.id,
        account_type=ACCOUNT_TYPE_CASHBACK_PROVIDER,
        currency="ZAR",
    )
    assert first.id == second.id
    # Sanity: the test tenant's wallet is the pre-funded one.
    balance, _ = await derive_balance(db_session, first.id)
    assert balance > 0
