"""Airtime recharge wired to `resolve_service_code` (Task 6, mechanical
replication of the P2P reference wiring in
`tests/payments/test_p2p_derived_service.py`).

An optional `service_code` on the recharge request is resolved ONCE before any
permission/pricing/limits gate, and the resolved code drives everything
downstream while `base_transaction_type` always records the endpoint's own
base ('airtime_recharge'). These tests prove: the omitted-`service_code` path
is unchanged, and a derived service records its own code + the base, charging
its own (different) fee.

`tests/airtime/` has no `conftest.py` — every existing test file (e.g.
`test_airtime_recharge_api.py`) defines its merchant/wallet/config fixtures
locally. This file mirrors that same shape (identical fixture bodies) rather
than inventing new ones, since pytest fixtures aren't shared across files
without a conftest.
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

from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.limits.schemas import LimitConfigCreateRequest
from app.modules.limits.service import create_limit_config
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    MERCHANT_CATEGORY_AIRTIME,
    MERCHANT_MODE_SIMULATOR,
    TXN_STATUS_COMPLETED,
    USER_TYPE_MERCHANT,
    Account,
    MerchantProfile,
    Role,
    RolePermission,
    Service,
    StepUpPolicy,
    Tenant,
    Transaction,
    User,
    UserRole,
)
from tests.conftest import make_points_account, reward_event_count, seed_first_time_points_rule

_SUCCESS_MSISDN = "+27825551234"


@pytest_asyncio.fixture
async def airtime_merchant(db_session: AsyncSession, test_tenant: Tenant) -> MerchantProfile:
    """An active airtime merchant (user_type=merchant) + profile for test_tenant.

    Mirrors `test_airtime_recharge_api.airtime_merchant` (local fixture, no
    shared conftest exists for this module).
    """
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
    """Seed a zero-fee airtime pricing + limit config for ZAR, plus a
    high-threshold step-up policy so the money-flow tests don't 401."""
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
    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge",
            currency="ZAR",
            threshold_amount=Decimal("100000000"),
        )
    )
    await db_session.commit()


async def _seed_derived_airtime_service(
    session: AsyncSession, tenant: Tenant, code: str = "airtime_recharge_bulk"
) -> Service:
    """Persist a live derived service based on 'airtime_recharge' (Task 4 fixture shape)."""
    base = Service(
        tenant_id=tenant.id, code="airtime_recharge", display_name="Airtime Recharge", kind="base"
    )
    session.add(base)
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name="Bulk Airtime Recharge",
        kind="derived",
        base_service_code="airtime_recharge",
    )
    session.add(row)
    await session.commit()
    return row


async def _grant_permission(session: AsyncSession, user: User, transaction_type: str) -> None:
    """Grant `user` a role permitting `transaction_type`."""
    role = Role(tenant_id=user.tenant_id, name=f"grant-{transaction_type}-{uuid4().hex[:8]}")
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, transaction_type=transaction_type, permitted=True))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()


def _body(msisdn: str = _SUCCESS_MSISDN, amount: str = "100") -> dict:
    return {"msisdn": msisdn, "network": "MTN", "amount": amount, "currency": "ZAR"}


def _headers(auth: dict[str, str], idem: str) -> dict[str, str]:
    return {**auth, "Idempotency-Key": idem, "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_omitting_service_code_records_plain_airtime_recharge_unchanged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify no `service_code` in the request resolves to 'airtime_recharge' byte for byte"""
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(_body()),
        headers=_headers(alice_auth_header, "airtime-derived-omit-1"),
    )
    assert resp.status_code == 200, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "airtime_recharge"
    assert txn.base_transaction_type == "airtime_recharge"


@pytest.mark.asyncio
async def test_derived_airtime_recharge_records_its_own_code_and_base_and_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    airtime_merchant: MerchantProfile,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a derived airtime service resolves, records the derived code +
    base 'airtime_recharge', and charges a fee that DIFFERS from the base's
    zero fee (pricing / limits are never inherited — spec §6.2)."""
    await _seed_derived_airtime_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge_bulk",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("3"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge_bulk",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, test_user, "airtime_recharge_bulk")

    body = _body()
    body["service_code"] = "airtime_recharge_bulk"
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(body),
        headers=_headers(alice_auth_header, "airtime-derived-fee-1"),
    )
    assert resp.status_code == 200, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "airtime_recharge_bulk"
    assert txn.base_transaction_type == "airtime_recharge"
    assert Decimal(str(txn.fee_amount)) == Decimal("3")
    assert Decimal(str(txn.fee_amount)) != Decimal("0")  # differs from the base's zero fee


@pytest.mark.asyncio
async def test_reward_rule_on_base_code_does_not_fire_for_derived_recharge(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    airtime_merchant,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a reward rule targeting the BASE code does NOT fire for a
    derived airtime recharge (spec §8 — precise targeting)."""
    await _seed_derived_airtime_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge_bulk",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("3"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge_bulk",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, test_user, "airtime_recharge_bulk")
    await make_points_account(db_session, test_tenant.id, test_user.id)
    await seed_first_time_points_rule(
        db_session, test_tenant.id, transaction_type="airtime_recharge", reward_value=Decimal("50")
    )

    body = _body()
    body["service_code"] = "airtime_recharge_bulk"
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(body),
        headers=_headers(alice_auth_header, "airtime-derived-reward-base-1"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["earned_points"] == 0
    assert await reward_event_count(db_session, test_user.id) == 0


@pytest.mark.asyncio
async def test_reward_rule_on_derived_code_fires_for_derived_recharge(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    airtime_merchant,
    funded_wallet: Account,
    airtime_configs: None,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a reward rule targeting the DERIVED code DOES fire — the reward
    outbox row carries the resolved service code, not the base literal."""
    await _seed_derived_airtime_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge_bulk",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("3"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="airtime_recharge_bulk",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, test_user, "airtime_recharge_bulk")
    await make_points_account(db_session, test_tenant.id, test_user.id)
    await seed_first_time_points_rule(
        db_session,
        test_tenant.id,
        transaction_type="airtime_recharge_bulk",
        reward_value=Decimal("50"),
    )

    body = _body()
    body["service_code"] = "airtime_recharge_bulk"
    resp = await async_client.post(
        "/api/v1/airtime/recharge",
        content=json.dumps(body),
        headers=_headers(alice_auth_header, "airtime-derived-reward-derived-1"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["earned_points"] == 50
    assert await reward_event_count(db_session, test_user.id) == 1
