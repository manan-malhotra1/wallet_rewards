"""Tests for POST /api/v1/payments/p2p.

Covers the Phase B threat-model scenarios from
docs/security/threat-models/phase-b-p2p.md §5, updated for Phase F.4
which removed `tenant_id` + `sender_user_id` from the body and gates the
endpoint on `get_current_user` (user session token).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.payments.service import top_up
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
    UserIdentifier,
)
from tests.conftest import create_session_token_for_user


@pytest.fixture
def idempotency_header() -> dict[str, str]:
    """Fresh Idempotency-Key per test request."""
    return {"Idempotency-Key": uuid4().hex}


async def _ensure_default_role(session: AsyncSession, tenant: Tenant):
    """Get or create the tenant's standard_user role with common permissions.

    Phase F.3 added a role check at step 1 of payment orchestration. Without
    a permitted role, P2P returns 403. This helper makes user creation
    self-contained — every helper-created user gets a default role.
    """
    from sqlalchemy import select

    from app.shared.models import Role, RolePermission

    result = await session.execute(
        select(Role).where(Role.tenant_id == tenant.id, Role.name == "standard_user")
    )
    role = result.scalar_one_or_none()
    if role is not None:
        return role
    role = Role(tenant_id=tenant.id, name="standard_user")
    session.add(role)
    await session.flush()
    for txn_type in ("p2p", "redemption", "top_up"):
        session.add(RolePermission(role_id=role.id, transaction_type=txn_type, permitted=True))
    await session.commit()
    return role


async def _make_user_with_wallet(
    session: AsyncSession,
    tenant: Tenant,
    *,
    phone: str,
    currency: str = "ZAR",
    assign_default_role: bool = True,
) -> tuple[User, Account]:
    """Helper — create a user with one phone identifier + one ZAR wallet.

    By default also assigns the tenant's standard_user role so P2P passes
    the Phase F.3 role check. Pass `assign_default_role=False` to test the
    "no role → 403" path.
    """
    from app.shared.models import UserRole

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
    if assign_default_role:
        role = await _ensure_default_role(session, tenant)
        session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()
    await session.refresh(user)
    await session.refresh(wallet)
    return user, wallet


async def _auth_header_for(user: User) -> dict[str, str]:
    """Build a Bearer header for a freshly-created user (Phase F.4)."""
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


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
    bob, bob_wallet = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")

    # Give Alice opening balance via the internal top_up service.
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-alice-1",
    )

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
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

    # Verify balances directly from the ledger — admin balance endpoint is
    # tested separately. derive_balance hits the test DB through db_session.
    alice_bal, _ = await derive_balance(db_session, alice_wallet.id)
    bob_bal, _ = await derive_balance(db_session, bob_wallet.id)
    assert alice_bal == Decimal("750")
    assert bob_bal == Decimal("250")


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
    _bob, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-alice-2",
    )

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
            "amount": "200",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "insufficient_funds"

    bal, _ = await derive_balance(db_session, alice_wallet.id)
    assert bal == Decimal("100")


@pytest.mark.asyncio
async def test_p2p_rejects_self_transfer(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Sender == recipient → 422 self_transfer_not_allowed."""
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="seed-alice-self",
    )

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
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
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="seed-alice-unknown",
    )

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
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
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222", currency="ZAR")

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
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

    Critical no-existence-leak check (NFR-0220). With Phase F.4 the sender's
    tenant comes from the session token, so a tenant-A user genuinely cannot
    address a tenant-B recipient even if they share the phone.
    """
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-alice-cross",
    )
    # Bob exists only in other_tenant with the SAME phone number.
    await _make_user_with_wallet(db_session, other_tenant, phone="+27 82 555 2222")

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_p2p_rejects_zero_amount(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Pydantic gt=0 constraint rejects zero/negative amounts → 422."""
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 0001")
    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 0000"},
            "amount": "0",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_p2p_requires_idempotency_key(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Missing Idempotency-Key header → 422 (FastAPI's missing-header default)."""
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 0001")
    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=alice_auth,
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 0000"},
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_p2p_rejects_unauthenticated_caller(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """No Authorization header → 401 (Phase F.4)."""
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers=idempotency_header,
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 401


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
    _, bob_wallet = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")
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
        "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 2222"},
        "amount": "100",
        "currency": "ZAR",
    }
    alice_auth = await _auth_header_for(alice)

    first = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": key},
        json=payload,
    )
    second = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": key},
        json=payload,
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["transaction_id"] == second.json()["transaction_id"]

    # Balances reflect ONE transfer, not two.
    alice_bal, _ = await derive_balance(db_session, alice_wallet.id)
    bob_bal, _ = await derive_balance(db_session, bob_wallet.id)
    assert alice_bal == Decimal("400")
    assert bob_bal == Decimal("100")


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
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-race",
    )
    alice_auth = await _auth_header_for(alice)

    def request(idemp_key: str) -> asyncio.Task[object]:
        return asyncio.create_task(
            async_client.post(
                "/api/v1/payments/p2p",
                headers={**alice_auth, "Idempotency-Key": idemp_key},
                json={
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
