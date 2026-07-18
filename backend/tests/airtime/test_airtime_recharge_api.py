"""Integration tests for the airtime recharge API (Epic 17 S4).

POST /api/v1/airtime/recharge reserves funds (DEBIT user wallet / CREDIT the
airtime merchant's holding account) then makes an after-commit provider call.
The bundled simulator is driven by the msisdn suffix:
  - normal  -> success  -> 200 COMPLETED
  - ...0001 -> failure  -> 200 REVERSED (user refunded)
  - ...0002 -> pending  -> 202 PENDING (callback/poll finalises later)
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.shared.models import (
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    MERCHANT_CATEGORY_AIRTIME,
    MERCHANT_MODE_SIMULATOR,
    TXN_STATUS_COMPLETED,
    USER_TYPE_MERCHANT,
    Account,
    AirtimeRecharge,
    MerchantProfile,
    Tenant,
    User,
)

_SUCCESS_MSISDN = "+27825551234"
_FAIL_MSISDN = "+27820000001"  # simulator: ...0001 -> failure
_PENDING_MSISDN = "+27820000002"  # simulator: ...0002 -> pending


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def airtime_merchant(db_session: AsyncSession, test_tenant: Tenant) -> MerchantProfile:
    """An active airtime merchant (user_type=merchant) + profile for test_tenant."""
    merchant = User(tenant_id=test_tenant.id, user_type=USER_TYPE_MERCHANT)
    db_session.add(merchant)
    await db_session.flush()
    profile = MerchantProfile(
        tenant_id=test_tenant.id,
        user_id=merchant.id,
        business_name="Default Airtime Merchant",
        category=MERCHANT_CATEGORY_AIRTIME,
        service_code="airtime_recharge",
        mode=MERCHANT_MODE_SIMULATOR,
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)
    return profile


async def _fund(session: AsyncSession, tenant: Tenant, wallet: Account, amount: Decimal) -> None:
    """Credit a wallet with a COMPLETED cash-inflow leg (test funding helper)."""
    inflow = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
                Account.currency == wallet.currency,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if inflow is None:
        inflow = Account(
            tenant_id=tenant.id,
            account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
            currency=wallet.currency,
        )
        session.add(inflow)
        await session.flush()
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"fund-{wallet.id}",
            transaction_type="fund",
            currency=wallet.currency,
            status=TXN_STATUS_COMPLETED,
            entries=[
                LedgerEntryRequest(account_id=inflow.id, entry_type=ENTRY_DEBIT, amount=amount),
                LedgerEntryRequest(account_id=wallet.id, entry_type=ENTRY_CREDIT, amount=amount),
            ],
        ),
    )


@pytest_asyncio.fixture
async def funded_wallet(
    db_session: AsyncSession, test_tenant: Tenant, user_wallet: Account
) -> Account:
    """test_user's ZAR wallet, funded with R500."""
    await _fund(db_session, test_tenant, user_wallet, Decimal("500"))
    return user_wallet


@pytest_asyncio.fixture
async def airtime_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Seed a zero-fee airtime pricing + limit config for ZAR.

    Invariant #12 makes the pricing+limit gate unconditional, so any test that
    actually transacts a recharge must seed BOTH configs for the scope first.
    Zero fee keeps the balance assertions (wallet 500 → 400, holding 100)
    unaffected. Negative-config tests deliberately DON'T request this fixture.
    """
    from app.modules.limits.schemas import LimitConfigCreateRequest
    from app.modules.limits.service import create_limit_config
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config
    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET

    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    # Step-up is FAIL-CLOSED: with no airtime_recharge policy the user would be
    # prompted for a PIN on any amount, turning these money-flow tests into
    # 401s. Seed a policy with a threshold far above the R100 amounts so the
    # below-threshold path is taken and no PIN is required. (Step-up runs before
    # the wallet overdraft check, so this also keeps the insufficient-funds test
    # reaching its 409 rather than a 401.)
    from app.shared.models import StepUpPolicy

    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge",
            currency="ZAR",
            threshold_amount=Decimal("100000000"),
        )
    )
    await db_session.commit()


@pytest_asyncio.fixture
async def unpermitted_auth_header(db_session: AsyncSession, test_tenant: Tenant) -> dict[str, str]:
    """A session for a user with no role — fails the airtime permission check."""
    from app.auth.sessions import create_session

    user = User(tenant_id=test_tenant.id)
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    token = await create_session(user.id, test_tenant.id, "mobile")
    return {"Authorization": f"Bearer {token}"}


def _body(msisdn: str = _SUCCESS_MSISDN, amount: str = "100") -> dict:
    return {"msisdn": msisdn, "network": "MTN", "amount": amount, "currency": "ZAR"}


def _headers(auth: dict[str, str], idem: str = "airtime-idem-1") -> dict[str, str]:
    return {**auth, "Idempotency-Key": idem, "Content-Type": "application/json"}


async def _balance(session: AsyncSession, account_id) -> Decimal:
    balance, _reserved = await derive_balance(session, account_id)
    return balance


async def _merchant_holding(
    session: AsyncSession, tenant: Tenant, merchant: MerchantProfile
) -> Account:
    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.user_id == merchant.user_id,
                Account.account_type == ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
            )
        )
    ).scalar_one()


# -----------------------------------------------------------------------------
# Happy path + outcomes
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recharge_success_debits_user_credits_merchant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """A fast (synchronous) success returns 200 COMPLETED and moves money."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["provider_reference"] is not None

    holding = await _merchant_holding(db_session, test_tenant, airtime_merchant)
    assert await _balance(db_session, funded_wallet.id) == Decimal("400")  # 500 - 100
    assert await _balance(db_session, holding.id) == Decimal("100")


@pytest.mark.asyncio
async def test_recharge_provider_failure_reverses_and_refunds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """A provider failure returns 200 REVERSED and refunds the user in full."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body(msisdn=_FAIL_MSISDN)),
        headers=_headers(alice_auth_header),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "REVERSED"

    holding = await _merchant_holding(db_session, test_tenant, airtime_merchant)
    assert await _balance(db_session, funded_wallet.id) == Decimal("500")  # refunded
    assert await _balance(db_session, holding.id) == Decimal("0")


@pytest.mark.asyncio
async def test_recharge_pending_returns_202(
    async_client: AsyncClient,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """A provider 'pending' returns 202 and leaves the recharge PENDING."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body(msisdn=_PENDING_MSISDN)),
        headers=_headers(alice_auth_header),
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "PENDING"

    # Poll GET reflects the same PENDING state.
    got = await async_client.get(f"/api/v1/airtime/{body['id']}", headers=alice_auth_header)
    assert got.status_code == 200
    assert got.json()["status"] == "PENDING"


# -----------------------------------------------------------------------------
# Auth / permission / validation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recharge_requires_auth(
    async_client: AsyncClient, airtime_merchant: MerchantProfile
) -> None:
    """No session token -> 401."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers={"Idempotency-Key": "x", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_recharge_requires_permission(
    async_client: AsyncClient,
    airtime_merchant: MerchantProfile,
    unpermitted_auth_header: dict[str, str],
) -> None:
    """A user whose role does not permit airtime -> 403."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(unpermitted_auth_header),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recharge_missing_idempotency_key_rejected(
    async_client: AsyncClient,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """The Idempotency-Key header is required (Pay-PRD-0200)."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers={**alice_auth_header, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_recharge_no_merchant_configured_rejected(
    async_client: AsyncClient,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """With no active airtime merchant in the tenant -> 422."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header),
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "airtime_merchant_not_configured"


@pytest.mark.asyncio
async def test_recharge_insufficient_funds_rejected(
    async_client: AsyncClient,
    airtime_merchant: MerchantProfile,
    user_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """An unfunded wallet cannot buy airtime -> 409 insufficient_funds."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body(amount="100")),
        headers=_headers(alice_auth_header),
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "insufficient_funds"


# -----------------------------------------------------------------------------
# Idempotency + tenant isolation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recharge_idempotent_replay_returns_same_recharge(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """Replaying the same Idempotency-Key returns the same recharge, once."""
    first = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header, idem="dup-key"),
    )
    assert first.status_code == 200, first.text
    second = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header, idem="dup-key"),
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    count = await db_session.scalar(
        select(func.count())
        .select_from(AirtimeRecharge)
        .where(AirtimeRecharge.tenant_id == test_tenant.id)
    )
    assert count == 1
    # Money moved exactly once.
    assert await _balance(db_session, funded_wallet.id) == Decimal("400")


@pytest.mark.asyncio
async def test_get_recharge_is_tenant_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """A recharge created in tenant A is not readable by a tenant B session."""
    from app.auth.sessions import create_session

    created = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header),
    )
    recharge_id = created.json()["id"]

    # A user in the other tenant.
    intruder = User(tenant_id=other_tenant.id)
    db_session.add(intruder)
    await db_session.flush()
    await db_session.commit()
    token = await create_session(intruder.id, other_tenant.id, "mobile")

    got = await async_client.get(
        f"/api/v1/airtime/{recharge_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert got.status_code == 404


@pytest.mark.asyncio
async def test_get_unknown_recharge_returns_404(
    async_client: AsyncClient, alice_auth_header: dict[str, str]
) -> None:
    """An unknown recharge id -> 404 airtime_recharge_not_found."""
    got = await async_client.get(f"/api/v1/airtime/{uuid4()}", headers=alice_auth_header)
    assert got.status_code == 404
    assert got.json()["error_code"] == "airtime_recharge_not_found"


@pytest.mark.asyncio
async def test_get_recharge_rejects_other_user_same_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """A different user in the SAME tenant cannot read alice's recharge (S7 A2)."""
    from app.auth.sessions import create_session

    created = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header),
    )
    recharge_id = created.json()["id"]

    other = User(tenant_id=test_tenant.id)
    db_session.add(other)
    await db_session.flush()
    await db_session.commit()
    token = await create_session(other.id, test_tenant.id, "mobile")

    got = await async_client.get(
        f"/api/v1/airtime/{recharge_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert got.status_code == 404


# -----------------------------------------------------------------------------
# Invariant #12 — UNCONDITIONAL fail-closed (no tenant flag involved)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recharge_fails_closed_without_any_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """No pricing/limit config (flag NOT set) → 422 service_not_configured, no money moves.

    Invariant #12: the airtime charge path fails closed unconditionally when a
    pricing config is missing — before any reservation is written.
    """
    assert test_tenant.require_config_to_transact is False  # flag plays no role

    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    # No money moved.
    assert await _balance(db_session, funded_wallet.id) == Decimal("500")


@pytest.mark.asyncio
async def test_recharge_fails_closed_when_pricing_present_but_limit_missing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Pricing present but NO limit config → still 422, no money moves.

    Invariant #12 requires BOTH configs; a limit gap alone fails the charge closed.
    """
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config
    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET

    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
        ),
    )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    assert await _balance(db_session, funded_wallet.id) == Decimal("500")


@pytest.mark.asyncio
async def test_recharge_succeeds_when_both_configs_present(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """Pricing + limit config for airtime present → recharge proceeds."""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "COMPLETED"
