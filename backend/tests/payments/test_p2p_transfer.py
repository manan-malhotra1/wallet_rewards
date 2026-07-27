"""Sending money to another customer.

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
from app.modules.payments.service import fund
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    StepUpPolicy,
    Tenant,
    User,
    UserIdentifier,
    WalletLimitConfig,
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
    for txn_type in ("p2p", "redemption", "fund"):
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
    """Verify sending money moves it from the sender to the recipient"""
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    bob, bob_wallet = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")

    # Give Alice opening balance via the internal fund service.
    await fund(
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
    """Verify a customer cannot send more money than their wallet balance"""
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    _bob, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")
    await fund(
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
    """Verify a customer cannot send money to themselves"""
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    await fund(
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
    """Verify sending money to an unknown recipient is refused"""
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    await fund(
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
    """Verify a customer cannot send money in a currency they hold no wallet for"""
    # Seed USD config so the gate passes for the requested currency and the
    # test reaches the wallet lookup it is actually exercising (account_not_found).
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id, currency="USD")
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
    """Verify a customer cannot send money to a recipient belonging to another tenant

    Recipient identifier exists only in other_tenant; request in test_tenant → 404.

    Critical no-existence-leak check (NFR-0220). With Phase F.4 the sender's
    tenant comes from the session token, so a tenant-A user genuinely cannot
    address a tenant-B recipient even if they share the phone.
    """
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    await fund(
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
    """Verify sending a zero or negative amount is refused"""
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
    """Verify a transfer must carry an idempotency key"""
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
    """Verify an unauthenticated customer cannot send money"""
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
    """Verify sending the same transfer twice moves money only once"""
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    _, bob_wallet = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")
    await fund(
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
    """Verify two simultaneous transfers cannot spend the same balance twice

    Two simultaneous transfers each for the full balance: only ONE succeeds.

    The SELECT FOR UPDATE on the sender wallet serialises the operations.
    The second one sees the post-debit balance and gets 409 insufficient_funds.
    """
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")
    await fund(
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


@pytest.mark.asyncio
async def test_p2p_concurrent_transfers_cannot_exceed_recipient_max_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify simultaneous incoming transfers cannot push a recipient past their maximum balance

    WAL-236 / M-01 (p2p receive axis): two concurrent transfers from DISTINCT
    senders into the SAME recipient — each individually under the recipient's
    max_balance but jointly over it — must NOT both land. The recipient may never
    exceed the ceiling.

    Distinct senders share no wallet lock, so serialising the SENDER debits (the
    existing guard) does nothing here. Only a FOR UPDATE lock on the RECIPIENT
    wallet, held across the max_balance read + the credit commit, can serialise the
    two receives. Without it both read the pre-credit balance and both pass.
    """
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    sender_a, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 1111")
    sender_b, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")
    _recipient, recipient_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 3333"
    )

    # Fund both senders BEFORE the cap exists so the seeding funds don't trip it.
    for idx, sender in enumerate((sender_a, sender_b)):
        await fund(
            db_session,
            tenant_id=test_tenant.id,
            user_id=sender.id,
            amount=Decimal("100"),
            currency="ZAR",
            idempotency_key=f"seed-recv-cap-{idx}",
        )

    # Recipient cap 150; each transfer is 100. Sequentially the first lands
    # (0+100) and the second is rejected (100+100 > 150).
    db_session.add(
        WalletLimitConfig(tenant_id=test_tenant.id, currency="ZAR", max_balance=Decimal("150"))
    )
    await db_session.commit()

    auth_a = await _auth_header_for(sender_a)
    auth_b = await _auth_header_for(sender_b)

    def transfer(auth: dict[str, str]) -> asyncio.Task[object]:
        return asyncio.create_task(
            async_client.post(
                "/api/v1/payments/p2p",
                headers={**auth, "Idempotency-Key": uuid4().hex},
                json={
                    "recipient": {
                        "identifier_type": "phone",
                        "identifier_value": "+27 82 555 3333",
                    },
                    "amount": "100",
                    "currency": "ZAR",
                },
            )
        )

    res_a, res_b = await asyncio.gather(transfer(auth_a), transfer(auth_b))

    statuses = sorted([res_a.status_code, res_b.status_code])
    assert statuses == [201, 409], f"expected one transfer + one cap-breach, got {statuses}"
    loser = res_a if res_a.status_code == 409 else res_b
    assert loser.json()["error_code"] == "recipient_max_balance_exceeded"

    recipient_bal, _ = await derive_balance(db_session, recipient_wallet.id)
    assert recipient_bal == Decimal("100"), f"recipient max_balance breached: {recipient_bal}"


@pytest.mark.asyncio
async def test_p2p_bidirectional_concurrent_transfers_do_not_deadlock(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify two customers can send to each other at the same time without the transfers stalling

    Canonical id-sorted lock order (invariant #11): two simultaneous transfers
    A->B and B->A must BOTH complete — no deadlock, no 500, no hang.

    The balance guard locks every wallet leg in account-id order BEFORE any
    balance read, so A->B and B->A acquire the SAME two wallet rows in the SAME
    order and can only ever wait on each other, never cycle. If the lock order
    were request-derived (the sender-first lock this change removed from
    p2p_transfer), A->B would lock A then B while B->A locks B then A — the
    classic inverse-order deadlock Postgres aborts with SQLSTATE 40P01, which
    surfaces here as an unhandled 500 on one leg.

    Distinct amounts (100 vs 60) make the net balances prove BOTH transfers
    actually executed, not just one.
    """
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 1111"
    )
    bob, bob_wallet = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 2222")

    # Fund both wallets generously so neither debit can overdraft in ANY commit
    # order — the test isolates lock ordering, not the overdraft check.
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-deadlock-alice",
    )
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=bob.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-deadlock-bob",
    )

    alice_auth = await _auth_header_for(alice)
    bob_auth = await _auth_header_for(bob)

    def transfer(auth: dict[str, str], recipient_phone: str, amount: str) -> asyncio.Task[object]:
        return asyncio.create_task(
            async_client.post(
                "/api/v1/payments/p2p",
                headers={**auth, "Idempotency-Key": uuid4().hex},
                json={
                    "recipient": {"identifier_type": "phone", "identifier_value": recipient_phone},
                    "amount": amount,
                    "currency": "ZAR",
                },
            )
        )

    a_to_b = transfer(alice_auth, "+27 82 555 2222", "100")
    b_to_a = transfer(bob_auth, "+27 82 555 1111", "60")

    # wait_for converts a genuine app-level hang into a clear failure rather than
    # blocking the whole suite. Postgres deadlock detection would instead abort
    # one leg (-> 500) well inside this window.
    res_ab, res_ba = await asyncio.wait_for(asyncio.gather(a_to_b, b_to_a), timeout=30)

    for res in (res_ab, res_ba):
        assert res.status_code == 201, res.text
        assert "deadlock" not in res.text.lower()

    # Net: Alice 1000 - 100 (sent) + 60 (received) = 960; Bob the mirror = 1040.
    alice_bal, _ = await derive_balance(db_session, alice_wallet.id)
    bob_bal, _ = await derive_balance(db_session, bob_wallet.id)
    assert alice_bal == Decimal("960"), f"alice net wrong: {alice_bal}"
    assert bob_bal == Decimal("1040"), f"bob net wrong: {bob_bal}"


# -----------------------------------------------------------------------------
# Fail-closed service gating (Epic 23, Story 23.2)
# -----------------------------------------------------------------------------


async def _seed_p2p_pricing_and_limit(
    session: AsyncSession, tenant_id, currency: str = "ZAR"
) -> None:
    """Seed a default (all-user-types) p2p pricing + limit config.

    Invariant #12 makes the pricing+limit gate unconditional, so every test
    that actually transacts a p2p must seed both configs for the scope first.
    """
    from app.modules.limits.schemas import LimitConfigCreateRequest
    from app.modules.limits.service import create_limit_config
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config

    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=currency,
            # Zero fee so balance-asserting tests are unaffected (no fee leg is
            # added when the fee is 0); the gate only needs a config to EXIST.
            fixed_fee=Decimal("0"),
        ),
    )
    await create_limit_config(
        session,
        LimitConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=currency,
            daily_count_cap=10,
        ),
    )
    # Step-up is FAIL-CLOSED: a missing p2p policy would now require a PIN for
    # ANY amount, turning these money-flow tests into 401s. Seed a policy with a
    # threshold far above every amount they move so the below-threshold path is
    # taken and no PIN is needed — the transfer assertions stay intact.
    session.add(
        StepUpPolicy(
            tenant_id=tenant_id,
            transaction_type="p2p",
            currency=currency,
            threshold_amount=Decimal("100000000"),
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_p2p_fails_closed_when_flag_on_and_config_missing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Verify a transfer is refused when the service has no pricing or limit set up"""
    test_tenant.require_config_to_transact = True
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7001")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7002")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-gate-a",
    )
    await db_session.commit()

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 7002"},
            "amount": "250",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "service_not_configured"


@pytest.mark.asyncio
async def test_p2p_succeeds_when_flag_on_and_configs_present(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Verify a transfer completes when pricing and limits are configured"""
    test_tenant.require_config_to_transact = True
    await _seed_p2p_pricing_and_limit(db_session, test_tenant.id)
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7011")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7012")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-gate-b",
    )
    await db_session.commit()

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 7012"},
            "amount": "250",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_p2p_fails_closed_when_amount_outside_configured_band(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Verify a transfer is refused when no fee is configured for its amount

    Flag on + a pricing band exists but the amount falls outside it → 422.

    The gate's existence check is amount-agnostic (a band row exists), so it
    passes; the per-amount fee resolution then finds no band and, because the
    tenant is fail-closed, the missing-pricing error is NOT swallowed.
    """
    from app.modules.limits.schemas import LimitConfigCreateRequest
    from app.modules.limits.service import create_limit_config
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config

    test_tenant.require_config_to_transact = True
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            amount_from=Decimal("0"),
            amount_to=Decimal("100"),
            fixed_fee=Decimal("2"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    # Step-up runs before per-amount fee resolution; seed a policy with a
    # threshold above the R250 amount so step-up no-ops and the test reaches
    # the pricing_config_missing branch it is asserting (not a 401 step-up).
    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            currency="ZAR",
            threshold_amount=Decimal("100000000"),
        )
    )
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7021")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7022")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-gate-c",
    )
    await db_session.commit()

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 7022"},
            "amount": "250",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "pricing_config_missing"


# -----------------------------------------------------------------------------
# Invariant #12 — UNCONDITIONAL fail-closed (no tenant flag involved)
# -----------------------------------------------------------------------------


async def _p2p_txn_count(session: AsyncSession, tenant_id) -> int:
    """Count posted p2p transactions for the tenant (seed 'fund' txns excluded)."""
    from sqlalchemy import func, select

    from app.shared.models import Transaction

    return await session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.tenant_id == tenant_id, Transaction.transaction_type == "p2p")
    )


@pytest.mark.asyncio
async def test_invariant12_p2p_fails_closed_without_any_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Verify a transfer is refused and no money moves when the service is unconfigured

    No pricing config AND flag NOT set → 422, and NO p2p transaction is written.

    Invariant #12: the gate is unconditional; a missing pricing config fails the
    charge closed BEFORE any ledger work, with no silent zero-fee.
    """
    assert test_tenant.require_config_to_transact is False  # flag plays no role
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 9101"
    )
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 9102")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-inv12-a",
    )
    await db_session.commit()

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 9102"},
            "amount": "250",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "service_not_configured"
    # No p2p transaction row created, sender balance untouched.
    assert await _p2p_txn_count(db_session, test_tenant.id) == 0
    bal, _ = await derive_balance(db_session, alice_wallet.id)
    assert bal == Decimal("1000")


@pytest.mark.asyncio
async def test_invariant12_p2p_fails_closed_when_pricing_present_but_limit_missing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    idempotency_header: dict[str, str],
) -> None:
    """Verify a transfer is refused when limits are missing even if pricing exists

    Pricing present but NO limit config → still 422, no p2p transaction written.

    Invariant #12 requires BOTH configs; a limit gap alone fails the charge closed.
    """
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config

    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
        ),
    )
    alice, alice_wallet = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 9201"
    )
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 9202")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-inv12-b",
    )
    await db_session.commit()

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, **idempotency_header},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 9202"},
            "amount": "250",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "service_not_configured"
    assert await _p2p_txn_count(db_session, test_tenant.id) == 0
    bal, _ = await derive_balance(db_session, alice_wallet.id)
    assert bal == Decimal("1000")
