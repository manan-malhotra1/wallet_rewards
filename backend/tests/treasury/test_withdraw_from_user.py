"""Tests for POST /api/v1/treasury/withdraw (admin pull-back).

Mirrors test_fund_user.py but verifies the reverse direction (user wallet
debited, operator_adjustment credited) and exercises the step-up flow
introduced in Phase 4.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger.service import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    Account,
    StepUpPolicy,
    Tenant,
    User,
)


async def _seed_user_wallet_with_balance(
    session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    starting_balance: Decimal,
) -> Account:
    """Give the user a ZAR wallet seeded with `starting_balance`."""
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    inflow = Account(
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency="ZAR",
    )
    session.add(inflow)
    await session.commit()
    await session.refresh(wallet)
    await session.refresh(inflow)

    # Bootstrap the balance via a manually-posted balanced transaction —
    # avoids the higher-level top_up code path so the test stays focused.
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"bootstrap-{uuid4().hex}",
            transaction_type="bootstrap",
            currency="ZAR",
            amount=starting_balance,
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id,
                    entry_type="DEBIT",
                    amount=starting_balance,
                ),
                LedgerEntryRequest(
                    account_id=wallet.id,
                    entry_type="CREDIT",
                    amount=starting_balance,
                ),
            ],
        ),
    )
    await session.commit()
    return wallet


async def _seed_step_up_policy(
    session: AsyncSession, tenant: Tenant, *, threshold: Decimal, currency: str = "ZAR"
) -> StepUpPolicy:
    """Add a withdraw step-up policy for the tenant."""
    policy = StepUpPolicy(
        tenant_id=tenant.id,
        transaction_type="withdraw",
        currency=currency,
        threshold_amount=threshold,
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


@pytest.mark.asyncio
async def test_withdraw_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Withdraw 200 from a 500-balance wallet → new balance 300."""
    wallet = await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "200",
            "currency": "ZAR",
            "reason": "Cash-out at agent counter.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["new_balance"]) == Decimal("300")

    # Direct ledger check: user wallet now sits at 300.
    new_balance, _ = await derive_balance(db_session, wallet.id)
    assert new_balance == Decimal("300")


@pytest.mark.asyncio
async def test_withdraw_credits_operator_adjustment(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Counter-leg lands on the operator_adjustment account (lazy-created)."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )

    await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "120",
            "currency": "ZAR",
            "reason": "Counter cash-out.",
        },
    )

    operator_account = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.currency == "ZAR",
            )
        )
    ).scalar_one()
    op_balance, _ = await derive_balance(db_session, operator_account.id)
    assert op_balance == Decimal("120")


@pytest.mark.asyncio
async def test_withdraw_rejects_insufficient_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Pulling more than the wallet holds → 409 insufficient_funds."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("50")
    )

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "100",
            "currency": "ZAR",
            "reason": "Over-draw attempt.",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "insufficient_funds"


@pytest.mark.asyncio
async def test_withdraw_missing_wallet_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """User without a wallet for the currency → 404."""
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "10",
            "currency": "ZAR",
            "reason": "No wallet.",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_withdraw_requires_auth(
    async_client: AsyncClient, test_tenant: Tenant, test_user: User
) -> None:
    """Anonymous withdraw → 401."""
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "10",
            "currency": "ZAR",
            "reason": "x",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_withdraw_step_up_required_without_pin(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Above threshold with no PIN → 401 step_up_required."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("1000")
    )
    await _seed_step_up_policy(db_session, test_tenant, threshold=Decimal("100"))

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "200",
            "currency": "ZAR",
            "reason": "Big cash-out.",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "step_up_required"


@pytest.mark.asyncio
async def test_withdraw_step_up_accepts_valid_pin(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Valid PIN unlocks the withdraw."""
    from app.auth.hashing import hash_pin

    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("1000")
    )
    await _seed_step_up_policy(db_session, test_tenant, threshold=Decimal("100"))
    # Step-up verifies against users.pin_hash — set it for this test.
    test_user.pin_hash = hash_pin("1234")
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "200",
            "currency": "ZAR",
            "reason": "Big cash-out.",
            "pin": "1234",
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_withdraw_step_up_rejects_wrong_pin(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Wrong PIN → 401 invalid_step_up_pin; balance untouched."""
    from app.auth.hashing import hash_pin

    wallet = await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("1000")
    )
    await _seed_step_up_policy(db_session, test_tenant, threshold=Decimal("100"))
    test_user.pin_hash = hash_pin("1234")
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "200",
            "currency": "ZAR",
            "reason": "Big cash-out.",
            "pin": "9999",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "invalid_step_up_pin"

    # Balance unchanged — no leg posted.
    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("1000")


@pytest.mark.asyncio
async def test_withdraw_below_threshold_skips_step_up(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Amount ≤ threshold → no PIN needed even though policy exists."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    await _seed_step_up_policy(db_session, test_tenant, threshold=Decimal("100"))

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "amount": "50",
            "currency": "ZAR",
            "reason": "Small cash-out.",
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_withdraw_cross_tenant_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """User in tenant A, withdraw scoped to tenant B → 404."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("100")
    )

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(other_tenant.id),
            "user_id": str(test_user.id),
            "amount": "10",
            "currency": "ZAR",
            "reason": "wrong tenant",
        },
    )
    assert resp.status_code == 404
