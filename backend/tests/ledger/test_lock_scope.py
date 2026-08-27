"""The ledger locks only rows a guard will actually check (spec B15).

The lock used to be taken for any non-zero delta on a guarded type, credits
included, while the floor applies only to a net DEBIT and the ceiling only to
`financial_wallet`. A credit into an uncapped guarded wallet therefore took a
`FOR UPDATE` row lock held through commit and was checked against nothing.

That mattered because of WHOSE row it is: parent commission credits the same
super-agent's commission wallet on every downline cash-in, so an entire
downline serialised on one row.

These tests pin both halves — the locks that must disappear, and every guard
that must NOT change.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import (
    InsufficientCommissionBalance,
    InsufficientFunds,
    MaxBalanceExceeded,
)
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Tenant,
    User,
)


@pytest.fixture
def lock_spy(monkeypatch) -> list:
    """Record every account the choke point takes a row lock on."""
    # The choke point imports this lazily from accounts.service inside the
    # function, so the SOURCE module is what has to be patched.
    from app.modules.accounts import service as accounts_service

    locked: list = []
    original = accounts_service.lock_account_for_update

    async def spy(session, account_id):
        locked.append(account_id)
        return await original(session, account_id)

    monkeypatch.setattr(accounts_service, "lock_account_for_update", spy)
    return locked


async def _account(
    session: AsyncSession, tenant: Tenant, account_type: str, user: User | None
) -> Account:
    """One account of a type, user-owned or system-owned."""
    account = Account(
        tenant_id=tenant.id,
        user_id=user.id if user is not None else None,
        account_type=account_type,
        currency="ZAR",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def _post(
    session: AsyncSession,
    tenant: Tenant,
    debit: Account,
    credit: Account,
    amount: Decimal,
    **kwargs,
):
    """Post one balanced two-leg transaction."""
    return await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"lock-{uuid4().hex[:10]}",
            transaction_type=kwargs.pop("transaction_type", "commission_accrual"),
            currency="ZAR",
            amount=amount,
            entries=[
                LedgerEntryRequest(debit.id, ENTRY_DEBIT, amount),
                LedgerEntryRequest(credit.id, ENTRY_CREDIT, amount),
            ],
            **kwargs,
        ),
    )


@pytest.mark.asyncio
async def test_a_credit_into_a_commission_wallet_takes_no_lock(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, lock_spy: list
) -> None:
    """The supervisor fan-in this whole story is about.

    Nothing can reject a credit into an uncapped wallet, so nothing should wait
    on one either.
    """
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )

    await _post(db_session, test_tenant, pool, wallet, Decimal("5"))

    # The pool is unguarded and the commission-wallet leg is a credit, so this
    # transaction should take no locks whatsoever.
    assert wallet.id not in lock_spy
    assert lock_spy == []


@pytest.mark.asyncio
async def test_a_debit_from_a_commission_wallet_still_locks(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, lock_spy: list
) -> None:
    """A disbursement CAN overdraw, so it must still serialise."""
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )
    await _post(db_session, test_tenant, pool, wallet, Decimal("50"))
    lock_spy.clear()

    await _post(
        db_session,
        test_tenant,
        wallet,
        pool,
        Decimal("20"),
        transaction_type="commission_disbursement",
    )
    assert wallet.id in lock_spy


@pytest.mark.asyncio
async def test_the_commission_floor_still_rejects_an_overdraw(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Narrowing WHICH rows lock must not change WHAT is enforced."""
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )
    await _post(db_session, test_tenant, pool, wallet, Decimal("10"))

    with pytest.raises(InsufficientCommissionBalance):
        await _post(
            db_session,
            test_tenant,
            wallet,
            pool,
            Decimal("999"),
            transaction_type="commission_disbursement",
        )


@pytest.mark.asyncio
async def test_a_credit_into_a_main_wallet_still_locks(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, lock_spy: list
) -> None:
    """The main wallet IS capped, so its credits keep the lock.

    This is what preserves the M-01 race: two concurrent credits must not both
    read a pre-credit balance and slip past max_balance together.
    """
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_FINANCIAL_WALLET, test_user
    )

    await _post(db_session, test_tenant, pool, wallet, Decimal("5"), transaction_type="fund")
    assert wallet.id in lock_spy


@pytest.mark.asyncio
async def test_a_cap_exempt_credit_takes_no_lock(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, lock_spy: list
) -> None:
    """`skip_receive_cap` disables the ceiling, so the lock has nothing to do.

    Locking for a check that is about to be skipped is exactly the pattern this
    change removes.
    """
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_FINANCIAL_WALLET, test_user
    )

    await _post(
        db_session,
        test_tenant,
        pool,
        wallet,
        Decimal("5"),
        transaction_type="fund",
        skip_receive_cap=True,
    )
    assert wallet.id not in lock_spy


@pytest.mark.asyncio
async def test_the_overdraft_floor_still_rejects_a_main_wallet_debit(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """The most important guard on the platform is untouched."""
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_FINANCIAL_WALLET, test_user
    )

    with pytest.raises(InsufficientFunds):
        await _post(
            db_session, test_tenant, wallet, pool, Decimal("1"), transaction_type="p2p"
        )


@pytest.mark.asyncio
async def test_locks_are_still_taken_in_canonical_order(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, lock_spy: list
) -> None:
    """Fewer locks must not disturb the ordering that prevents deadlock.

    Two wallets locked in inverse order by concurrent transactions is the only
    deadlock this choke point can produce, which is why the set is sorted.
    """
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    main = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_FINANCIAL_WALLET, test_user
    )
    commission = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )
    await _post(db_session, test_tenant, pool, commission, Decimal("40"))
    lock_spy.clear()

    # A disbursement: DEBIT commission (floor) + CREDIT main (ceiling) — both
    # still lock, so the ordering guarantee is observable.
    await _post(
        db_session,
        test_tenant,
        commission,
        main,
        Decimal("10"),
        transaction_type="commission_disbursement",
    )
    assert set(lock_spy) == {main.id, commission.id}
    assert lock_spy == sorted(lock_spy)


@pytest.mark.asyncio
async def test_max_balance_is_still_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """A capped credit that breaches the ceiling must still be rejected."""
    from app.modules.limits.schemas import WalletLimitConfigCreateRequest
    from app.modules.limits.service import create_wallet_limit_config

    await create_wallet_limit_config(
        db_session,
        WalletLimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            currency="ZAR",
            user_type=None,
            max_balance=Decimal("100"),
        ),
    )
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_FINANCIAL_WALLET, test_user
    )

    with pytest.raises(MaxBalanceExceeded):
        await _post(
            db_session, test_tenant, pool, wallet, Decimal("500"), transaction_type="fund"
        )

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("0")
