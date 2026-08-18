"""P2P wired to `resolve_service_code` — the reference derived-service flow.

Task 5 wires P2P as the reference money endpoint (spec §7): an optional
`service_code` on the request is resolved ONCE before any permission/
pricing/limits gate, and the resolved code drives everything downstream while
`base_transaction_type` always records the endpoint's own base ('p2p'). These
tests prove: the omitted-`service_code` path is byte-for-byte unchanged, a
derived service charges its OWN fee independently of the base, and the
fail-closed pricing/limits gate (invariant #12) applies per-code — a derived
service with no config of its own is rejected even though the base 'p2p' is
fully configured, and WITHOUT writing any transaction row.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.schemas import LimitConfigCreateRequest
from app.modules.limits.service import create_limit_config
from app.modules.payments.service import fund
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Role,
    RolePermission,
    Service,
    Tenant,
    Transaction,
    User,
    UserRole,
)
from tests.payments.test_p2p_transfer import (
    _auth_header_for,
    _make_user_with_wallet,
    _seed_p2p_pricing_and_limit,
)


async def _seed_derived_p2p_service(
    session: AsyncSession, tenant: Tenant, code: str = "p2p_diaspora"
) -> Service:
    """Persist a live derived service based on 'p2p' (Task 4 fixture shape).

    Also seeds the live base 'p2p' row so `resolve_service_code`'s
    resolution-time intersection has a real base to intersect against,
    matching how an operator-created derived service would look in practice.
    """
    base = Service(tenant_id=tenant.id, code="p2p", display_name="Send Money", kind="base")
    session.add(base)
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name="Diaspora P2P",
        kind="derived",
        base_service_code="p2p",
    )
    session.add(row)
    await session.commit()
    return row


async def _grant_permission(session: AsyncSession, user: User, transaction_type: str) -> None:
    """Grant `user` a role permitting `transaction_type` (mirrors _ensure_default_role)."""
    role = Role(tenant_id=user.tenant_id, name=f"grant-{transaction_type}-{uuid4().hex[:8]}")
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, transaction_type=transaction_type, permitted=True))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()


async def _seed_pricing_and_limit(
    session: AsyncSession,
    tenant_id,
    transaction_type: str,
    *,
    fixed_fee: Decimal = Decimal("0"),
    daily_count_cap: int | None = 10,
) -> None:
    """Seed a default (all-user-types) pricing + limit config for one code."""
    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type=transaction_type,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=fixed_fee,
        ),
    )
    await create_limit_config(
        session,
        LimitConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type=transaction_type,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=daily_count_cap,
        ),
    )


async def _transaction_count(session: AsyncSession, tenant_id, transaction_type: str) -> int:
    """Count rows for one transaction_type — used to prove no ledger write happened."""
    result = await session.execute(
        select(Transaction).where(
            Transaction.tenant_id == tenant_id,
            Transaction.transaction_type == transaction_type,
        )
    )
    return len(result.scalars().all())


@pytest.mark.asyncio
async def test_omitting_service_code_records_plain_p2p_unchanged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify no `service_code` in the request resolves to 'p2p' byte for byte"""
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5001")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5002")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="seed-derived-a",
    )

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 5002"},
            "amount": "50",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == response.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "p2p"
    assert txn.base_transaction_type == "p2p"


@pytest.mark.asyncio
async def test_derived_service_records_its_own_code_and_charges_its_own_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify a derived service with its own pricing resolves, records the
    derived code + base 'p2p', and charges a fee that DIFFERS from the base's
    (pricing/limits are never inherited — spec §6.2)."""
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)  # base fee = 0
    await _seed_derived_p2p_service(db_session, test_tenant)
    await _seed_pricing_and_limit(
        db_session, test_tenant.id, "p2p_diaspora", fixed_fee=Decimal("15")
    )
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5101")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5102")
    await _grant_permission(db_session, alice, "p2p_diaspora")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="seed-derived-b",
    )

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 5102"},
            "amount": "50",
            "currency": "ZAR",
            "service_code": "p2p_diaspora",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["fee"]) == Decimal("15")
    assert Decimal(body["fee"]) != Decimal("0")  # differs from the base's zero fee

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == body["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "p2p_diaspora"
    assert txn.base_transaction_type == "p2p"


@pytest.mark.asyncio
async def test_derived_service_with_no_pricing_config_fails_closed_with_no_transaction_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify a derived service with NO pricing config 422s and writes nothing

    Invariant #12 is per-code: the base 'p2p' being fully configured must not
    leak a fee/limit to a derived service that has none of its own.
    """
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    await _seed_derived_p2p_service(db_session, test_tenant)
    # Limit config only — pricing deliberately absent.
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p_diaspora",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    alice, _alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 5201"
    )
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5202")
    await _grant_permission(db_session, alice, "p2p_diaspora")

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 5202"},
            "amount": "50",
            "currency": "ZAR",
            "service_code": "p2p_diaspora",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "service_not_configured"

    # No p2p-family transaction was written — nothing was ever moved. (The
    # tenant fixture's own float pre-funding writes an unrelated
    # 'treasury.adjust' row, so we scope the emptiness check to this flow.)
    result = await db_session.execute(
        select(Transaction).where(
            Transaction.tenant_id == test_tenant.id,
            Transaction.transaction_type.in_(["p2p", "p2p_diaspora"]),
        )
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_derived_service_with_no_limit_config_fails_closed(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify a derived service with pricing but NO limit config still 422s"""
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    await _seed_derived_p2p_service(db_session, test_tenant)
    # Pricing config only — limit deliberately absent.
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p_diaspora",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("15"),
        ),
    )
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5301")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5302")
    await _grant_permission(db_session, alice, "p2p_diaspora")

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 5302"},
            "amount": "50",
            "currency": "ZAR",
            "service_code": "p2p_diaspora",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "service_not_configured"

    assert await _transaction_count(db_session, test_tenant.id, "p2p_diaspora") == 0


@pytest.mark.asyncio
async def test_exhausting_derived_daily_cap_does_not_block_plain_p2p(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify the derived service's daily count cap is independent of the base's

    Limits are never inherited (spec §6.2): a derived service hitting ITS OWN
    daily cap must not affect the base 'p2p' cap, and vice versa.
    """
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    await _seed_derived_p2p_service(db_session, test_tenant)
    await _seed_pricing_and_limit(
        db_session, test_tenant.id, "p2p_diaspora", daily_count_cap=1
    )
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5401")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 5402")
    await _grant_permission(db_session, alice, "p2p_diaspora")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="seed-derived-cap",
    )
    alice_auth = await _auth_header_for(alice)

    # First derived transfer consumes the cap of 1.
    first = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 5402"},
            "amount": "10",
            "currency": "ZAR",
            "service_code": "p2p_diaspora",
        },
    )
    assert first.status_code == 201, first.text

    # Second derived transfer breaches the derived cap.
    second = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 5402"},
            "amount": "10",
            "currency": "ZAR",
            "service_code": "p2p_diaspora",
        },
    )
    assert second.status_code == 429, second.text
    assert second.json()["error_code"] == "daily_count_exceeded"

    # A plain (base) p2p transfer is UNAFFECTED — independent cap.
    plain = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 5402"},
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert plain.status_code == 201, plain.text
