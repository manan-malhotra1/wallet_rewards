"""Tests for POST /api/v1/payments/p2p.

Covers the Phase B threat-model scenarios from
docs/security/threat-models/phase-b-p2p.md §5.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.service import top_up
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
    UserIdentifier,
)


@pytest.fixture
def idempotency_header() -> dict[str, str]:
    """Fresh Idempotency-Key per test request."""
    return {"Idempotency-Key": uuid4().hex}


async def _make_user_with_wallet(
    session: AsyncSession,
    tenant: Tenant,
    *,
    phone: str,
    currency: str = "ZAR",
) -> tuple[User, Account]:
    """Helper — create a user with one phone identifier + one ZAR wallet."""
    user = User(tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=tenant.id,
            identifier_type="phone",
            identifier_value=phone,
            verified=True,
        )
    )
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
    )
    session.add(wallet)
    await session.commit()
    await session.refresh(user)
    await session.refresh(wallet)
    return user, wallet


# -----------------------------------------------------------------------------
# Happy path & balance assertions
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2p_happy_path_moves_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Alice 1000 -> Bob 0; after P2P 250: Alice 750, Bob 250."""
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    bob, bob_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 2222"
    )

    # Give Alice opening balance via the internal top_up service.
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-alice-1",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
            "amount": "250",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["sender_user_id"] == str(alice.id)
    assert body["recipient_user_id"] == str(bob.id)
    assert Decimal(body["amount"]) == Decimal("250")

    # Verify the balances changed accordingly.
    alice_bal = await async_client.get(
        f"/api/v1/accounts/{alice_wallet.id}/balance",
        params={"tenant_id": str(test_tenant.id)},
    )
    bob_bal = await async_client.get(
        f"/api/v1/accounts/{bob_wallet.id}/balance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert Decimal(alice_bal.json()["balance"]) == Decimal("750")
    assert Decimal(bob_bal.json()["balance"]) == Decimal("250")


# -----------------------------------------------------------------------------
# Rejection paths
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2p_rejects_overdraft(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Sender with insufficient balance gets 409 — no ledger write."""
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    bob, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 2222"
    )
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-alice-2",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
            "amount": "200",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "insufficient_funds"

    # Balance must be unchanged.
    bal = await async_client.get(
        f"/api/v1/accounts/{alice_wallet.id}/balance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert Decimal(bal.json()["balance"]) == Decimal("100")


@pytest.mark.asyncio
async def test_p2p_rejects_self_transfer(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Sender == recipient → 422 self_transfer_not_allowed."""
    alice, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="seed-alice-self",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 1111"},
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "self_transfer_not_allowed"


@pytest.mark.asyncio
async def test_p2p_rejects_unknown_recipient(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Unknown recipient phone → 404 user_not_found."""
    alice, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="seed-alice-unknown",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 9999"},
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_p2p_rejects_sender_without_wallet_in_currency(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Sender has a wallet, but not in the requested currency → 404."""
    alice, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111", currency="ZAR"
    )
    bob, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 2222", currency="ZAR"
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
            "amount": "10",
            "currency": "USD",  # neither party has a USD wallet
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "account_not_found"


@pytest.mark.asyncio
async def test_p2p_cross_tenant_recipient_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Recipient identifier exists only in other_tenant; request in test_tenant → 404.

    Critical no-existence-leak check (NFR-0220).
    """
    alice, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-alice-cross",
    )
    # Bob exists only in other_tenant with the SAME phone number.
    await _make_user_with_wallet(
        db_session, other_tenant, phone="+27 82 555 2222"
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_p2p_rejects_zero_amount(
    async_client: AsyncClient,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Pydantic gt=0 constraint rejects zero/negative amounts → 422."""
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(uuid4()),
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 0000"},
            "amount": "0",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_p2p_requires_idempotency_key(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Missing Idempotency-Key header → 422 (FastAPI's missing-header default)."""
    response = await async_client.post(
        "/api/v1/payments/p2p",
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(uuid4()),
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 0000"},
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422


# -----------------------------------------------------------------------------
# Idempotency & concurrency
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2p_idempotent_replay(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Same Idempotency-Key returns the original transaction; no double-debit."""
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    bob, bob_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 2222"
    )
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="seed-alice-idem",
    )

    key = uuid4().hex
    payload = {
        "tenant_id": str(test_tenant.id),
        "sender_user_id": str(alice.id),
        "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
        "amount": "100",
        "currency": "ZAR",
    }

    first = await async_client.post(
        "/api/v1/payments/p2p", headers={"Idempotency-Key": key}, json=payload
    )
    second = await async_client.post(
        "/api/v1/payments/p2p", headers={"Idempotency-Key": key}, json=payload
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["transaction_id"] == second.json()["transaction_id"]

    # Balances reflect ONE transfer, not two.
    alice_bal = await async_client.get(
        f"/api/v1/accounts/{alice_wallet.id}/balance",
        params={"tenant_id": str(test_tenant.id)},
    )
    bob_bal = await async_client.get(
        f"/api/v1/accounts/{bob_wallet.id}/balance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert Decimal(alice_bal.json()["balance"]) == Decimal("400")
    assert Decimal(bob_bal.json()["balance"]) == Decimal("100")


@pytest.mark.asyncio
async def test_p2p_concurrent_double_spend_blocked(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Two simultaneous transfers each for the full balance: only ONE succeeds.

    The SELECT FOR UPDATE on the sender wallet serialises the operations.
    The second one sees the post-debit balance and gets 409 insufficient_funds.
    """
    alice, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 2222"
    )
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-race",
    )

    def request(idemp_key: str) -> "asyncio.Task[object]":
        return asyncio.create_task(
            async_client.post(
                "/api/v1/payments/p2p",
                headers={"Idempotency-Key": idemp_key},
                json={
                    "tenant_id": str(test_tenant.id),
                    "sender_user_id": str(alice.id),
                    "recipient": {
                        "identifier_type": "phone",
                        "identifier_value": "+27 82 555 2222",
                    },
                    "amount": "100",  # full balance
                    "currency": "ZAR",
                },
            )
        )

    task_a = request(uuid4().hex)
    task_b = request(uuid4().hex)
    res_a, res_b = await asyncio.gather(task_a, task_b)

    statuses = sorted([res_a.status_code, res_b.status_code])
    assert statuses == [201, 409], f"expected one success + one overdraft, got {statuses}"
    fail = res_a if res_a.status_code == 409 else res_b
    assert fail.json()["error_code"] == "insufficient_funds"
