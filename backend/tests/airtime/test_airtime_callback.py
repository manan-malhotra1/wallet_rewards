"""Airtime provider callbacks and operator resolve.

POST /api/v1/airtime/{id}/callback is HMAC-verified against the merchant's
decrypted callback secret and finalises a PENDING recharge (the async path for
a provider that returned 'pending'). POST /api/v1/airtime/{id}/resolve is the
admin operator override for a recharge the provider never called back on.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hmac import build_signature_header
from app.auth.secret_box import encrypt_secret
from app.modules.accounts.service import derive_balance
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.shared.models import (
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    MERCHANT_CATEGORY_AIRTIME,
    MERCHANT_MODE_SIMULATOR,
    TXN_STATUS_COMPLETED,
    USER_TYPE_MERCHANT,
    Account,
    MerchantProfile,
    Tenant,
    User,
)

_CALLBACK_SECRET = "airtime-callback-shared-secret-1234567890"
_SUCCESS_MSISDN = "+27825551234"
_PENDING_MSISDN = "+27820000002"  # simulator: ...0002 -> pending


@pytest_asyncio.fixture(autouse=True)
async def _airtime_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Autouse: seed a zero-fee airtime pricing + limit config for every test here.

    Invariant #12 makes the pricing+limit gate unconditional, so a recharge can
    only be created once both configs exist. Every test in this file first
    creates a recharge via the API, and none is a missing-config negative test,
    so seeding unconditionally is safe.
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
    # Step-up is FAIL-CLOSED: every test here first creates a recharge through
    # the initiate endpoint, which enforces step-up. Without an airtime_recharge
    # policy that would demand a PIN on any amount. Seed a policy whose threshold
    # sits far above the recharge amounts so the below-threshold path skips the
    # PIN and the callback flow under test is reached.
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
async def signed_merchant(db_session: AsyncSession, test_tenant: Tenant) -> MerchantProfile:
    """An active airtime merchant with a known Fernet-encrypted callback secret."""
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
        callback_secret_encrypted=encrypt_secret(_CALLBACK_SECRET),
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)
    return profile


@pytest_asyncio.fixture
async def funded_wallet(
    db_session: AsyncSession, test_tenant: Tenant, user_wallet: Account
) -> Account:
    """test_user's ZAR wallet, funded with R500."""
    # Reuse the tenant's pre-funded cash float (get-or-create) — a second
    # system_cash_inflow row would violate the unique index, and its positive
    # balance absorbs the bootstrap DEBIT below (the float has a no-overdraft floor).
    from app.modules.payments.service import get_or_create_system_cash_inflow

    inflow = await get_or_create_system_cash_inflow(db_session, test_tenant.id, "ZAR")
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key=f"fund-{user_wallet.id}",
            transaction_type="fund",
            currency="ZAR",
            status=TXN_STATUS_COMPLETED,
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id, entry_type=ENTRY_DEBIT, amount=Decimal("500")
                ),
                LedgerEntryRequest(
                    account_id=user_wallet.id, entry_type=ENTRY_CREDIT, amount=Decimal("500")
                ),
            ],
        ),
    )
    return user_wallet


def _body(msisdn: str = _SUCCESS_MSISDN, amount: str = "100") -> dict:
    return {"msisdn": msisdn, "network": "MTN", "amount": amount, "currency": "ZAR"}


def _recharge_headers(auth: dict[str, str], idem: str) -> dict[str, str]:
    return {**auth, "Idempotency-Key": idem, "Content-Type": "application/json"}


def _callback_headers(raw: bytes, secret: str = _CALLBACK_SECRET) -> dict[str, str]:
    return {
        "X-Sasai-Signature": build_signature_header(raw_body=raw, secret=secret),
        "Content-Type": "application/json",
    }


async def _balance(session: AsyncSession, account_id) -> Decimal:
    balance, _reserved = await derive_balance(session, account_id)
    return balance


async def _holding(session: AsyncSession, tenant: Tenant, merchant: MerchantProfile) -> Account:
    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.user_id == merchant.user_id,
                Account.account_type == ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
            )
        )
    ).scalar_one()


async def _create_pending(client: AsyncClient, auth: dict[str, str], idem: str = "cb-1") -> str:
    """Create a recharge that the simulator leaves PENDING, return its id."""
    resp = await client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body(_PENDING_MSISDN)),
        headers=_recharge_headers(auth, idem),
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["id"]


# -----------------------------------------------------------------------------
# Callback
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_completes_pending_recharge(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    signed_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a provider success callback completes a pending airtime recharge"""
    recharge_id = await _create_pending(async_client, alice_auth_header)
    raw = json.dumps({"outcome": "completed", "provider_reference": "MTN-XYZ"}).encode()

    resp = await async_client.post(
        f"/api/v1/airtime/{recharge_id}/callback",
        content=raw,
        headers=_callback_headers(raw),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "COMPLETED"
    assert resp.json()["provider_reference"] == "MTN-XYZ"

    holding = await _holding(db_session, test_tenant, signed_merchant)
    assert await _balance(db_session, funded_wallet.id) == Decimal("400")
    assert await _balance(db_session, holding.id) == Decimal("100")


@pytest.mark.asyncio
async def test_callback_failed_reverses_and_refunds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    signed_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a provider failure callback refunds the customer"""
    recharge_id = await _create_pending(async_client, alice_auth_header)
    raw = json.dumps({"outcome": "failed", "reason": "mno_rejected"}).encode()

    resp = await async_client.post(
        f"/api/v1/airtime/{recharge_id}/callback",
        content=raw,
        headers=_callback_headers(raw),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "REVERSED"

    holding = await _holding(db_session, test_tenant, signed_merchant)
    assert await _balance(db_session, funded_wallet.id) == Decimal("500")
    assert await _balance(db_session, holding.id) == Decimal("0")


@pytest.mark.asyncio
async def test_callback_bad_signature_rejected(
    async_client: AsyncClient,
    signed_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify an airtime callback with an invalid signature is rejected"""
    recharge_id = await _create_pending(async_client, alice_auth_header)
    raw = json.dumps({"outcome": "completed"}).encode()
    resp = await async_client.post(
        f"/api/v1/airtime/{recharge_id}/callback",
        content=raw,
        headers=_callback_headers(raw, secret="the-wrong-secret"),
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_callback_missing_signature_rejected(
    async_client: AsyncClient,
    signed_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify an airtime callback without a signature is rejected"""
    recharge_id = await _create_pending(async_client, alice_auth_header)
    raw = json.dumps({"outcome": "completed"}).encode()
    resp = await async_client.post(
        f"/api/v1/airtime/{recharge_id}/callback",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_callback_on_terminal_recharge_rejected(
    async_client: AsyncClient,
    signed_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a callback on an already-settled recharge is rejected"""
    # A success msisdn resolves synchronously to COMPLETED.
    created = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body(_SUCCESS_MSISDN)),
        headers=_recharge_headers(alice_auth_header, "cb-terminal"),
    )
    assert created.status_code == 200
    recharge_id = created.json()["id"]

    raw = json.dumps({"outcome": "failed", "reason": "late"}).encode()
    resp = await async_client.post(
        f"/api/v1/airtime/{recharge_id}/callback",
        content=raw,
        headers=_callback_headers(raw),
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "airtime_recharge_already_settled"


@pytest.mark.asyncio
async def test_callback_unknown_recharge_returns_404(
    async_client: AsyncClient, signed_merchant: MerchantProfile
) -> None:
    """Verify a callback for an unknown recharge is rejected"""
    raw = json.dumps({"outcome": "completed"}).encode()
    resp = await async_client.post(
        f"/api/v1/airtime/{uuid4()}/callback",
        content=raw,
        headers=_callback_headers(raw),
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# Operator resolve (reconciliation safety net)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_resolve_completes_pending_recharge(
    async_client: AsyncClient,
    test_tenant: Tenant,
    signed_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an operator can force a stuck pending recharge to complete"""
    recharge_id = await _create_pending(async_client, alice_auth_header)
    resp = await async_client.post(
        f"/api/v1/airtime/{recharge_id}/resolve",
        json={"tenant_id": str(test_tenant.id), "outcome": "COMPLETED"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_resolve_requires_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    signed_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a customer cannot force-resolve a recharge"""
    recharge_id = await _create_pending(async_client, alice_auth_header)
    resp = await async_client.post(
        f"/api/v1/airtime/{recharge_id}/resolve",
        json={"tenant_id": str(test_tenant.id), "outcome": "COMPLETED"},
        headers=alice_auth_header,
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_resolve_on_terminal_recharge_rejected(
    async_client: AsyncClient,
    test_tenant: Tenant,
    signed_merchant: MerchantProfile,
    funded_wallet: Account,
    alice_auth_header: dict[str, str],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an operator cannot resolve an already-settled recharge"""
    created = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body(_SUCCESS_MSISDN)),
        headers=_recharge_headers(alice_auth_header, "resolve-terminal"),
    )
    assert created.status_code == 200  # success msisdn settles synchronously
    recharge_id = created.json()["id"]

    resp = await async_client.post(
        f"/api/v1/airtime/{recharge_id}/resolve",
        json={"tenant_id": str(test_tenant.id), "outcome": "COMPLETED"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "airtime_recharge_already_settled"
