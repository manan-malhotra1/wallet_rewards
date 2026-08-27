"""Shared builder for a tenant with real accrued commission.

Builds a flag-on tenant with a real accrued commission balance — posted through
`post_transaction`, never by inserting a ledger row by hand, so the balances the
tests assert on are the ones the ledger actually derives.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Instrument,
    Tenant,
    User,
    UserIdentifier,
)

ACCRUED = Decimal("100")


@dataclass
class BatchFixture:
    """Everything a batch test needs, pre-wired."""

    tenant: Tenant
    agent: User
    agent_msisdn: str
    consumer_msisdn: str
    agent_commission_wallet: Account
    agent_main_wallet: Account
    bank_mirror: Account
    session: AsyncSession

    async def drain_commission_wallet(self) -> None:
        """Empty the agent's commission wallet.

        Simulates the balance drifting between approval and apply, which is the
        case pass-2 re-validation exists to catch (spec §8.4).
        """
        pool = await _account(
            self.session, self.tenant, ACCOUNT_TYPE_COMMISSION, user=None
        )
        await post_transaction(
            self.session,
            PostTransactionRequest(
                tenant_id=self.tenant.id,
                idempotency_key=f"drain-{uuid4().hex[:8]}",
                transaction_type="commission_withdrawal",
                currency="ZAR",
                amount=ACCRUED,
                entries=[
                    LedgerEntryRequest(
                        self.agent_commission_wallet.id, ENTRY_DEBIT, ACCRUED
                    ),
                    LedgerEntryRequest(pool.id, ENTRY_CREDIT, ACCRUED),
                ],
            ),
        )


async def _account(
    session: AsyncSession,
    tenant: Tenant,
    account_type: str,
    *,
    user: User | None,
    currency: str = "ZAR",
    name: str | None = None,
) -> Account:
    """Get-or-create one account, so fixtures compose without collisions."""
    from sqlalchemy import select

    stmt = select(Account).where(
        Account.tenant_id == tenant.id,
        Account.account_type == account_type,
        Account.currency == currency,
    )
    stmt = stmt.where(
        Account.user_id == user.id if user is not None else Account.user_id.is_(None)
    )
    existing = (await session.execute(stmt)).scalars().first()
    if existing is not None:
        return existing

    account = Account(
        tenant_id=tenant.id,
        user_id=user.id if user is not None else None,
        account_type=account_type,
        currency=currency,
        name=name,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def _user_with_phone(
    session: AsyncSession, tenant: Tenant, user_type: str, phone: str
) -> User:
    """A user of a type carrying one verified phone identifier."""
    user = User(tenant_id=tenant.id, user_type=user_type)
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
    await session.commit()
    await session.refresh(user)
    return user


async def build_batch_fixture(db_session: AsyncSession, test_tenant: Tenant) -> BatchFixture:
    """A flag-on tenant, an agent holding R100 of accrued commission, a mirror."""
    test_tenant.commission_wallet_enabled = True
    for code in ("ZAR", "INR"):
        db_session.add(
            Instrument(
                tenant_id=test_tenant.id,
                code=code,
                symbol=code,
                display_name=code,
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            )
        )
    await db_session.commit()

    suffix = uuid4().int % 10000
    agent_msisdn = f"+2782100{suffix:04d}"
    consumer_msisdn = f"+2782200{suffix:04d}"

    agent = await _user_with_phone(db_session, test_tenant, "agent", agent_msisdn)
    await _user_with_phone(db_session, test_tenant, "consumer", consumer_msisdn)

    commission_wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, user=agent
    )
    main_wallet = await _account(
        db_session, test_tenant, ACCOUNT_TYPE_FINANCIAL_WALLET, user=agent
    )
    await _account(
        db_session,
        test_tenant,
        ACCOUNT_TYPE_COMMISSION_WALLET,
        user=agent,
        currency="INR",
    )
    pool = await _account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, user=None)
    bank_mirror = await _account(
        db_session,
        test_tenant,
        ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        user=None,
        name="Primary",
    )

    # Accrue through the real ledger so the balance is genuinely derived.
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key=f"accrue-{uuid4().hex[:8]}",
            transaction_type="commission_accrual",
            currency="ZAR",
            amount=ACCRUED,
            entries=[
                LedgerEntryRequest(pool.id, ENTRY_DEBIT, ACCRUED),
                LedgerEntryRequest(commission_wallet.id, ENTRY_CREDIT, ACCRUED),
            ],
        ),
    )

    return BatchFixture(
        tenant=test_tenant,
        agent=agent,
        agent_msisdn=agent_msisdn,
        consumer_msisdn=consumer_msisdn,
        agent_commission_wallet=commission_wallet,
        agent_main_wallet=main_wallet,
        bank_mirror=bank_mirror,
        session=db_session,
    )


def build_maker_admin() -> AdminPrincipal:
    """The batch maker."""
    return AdminPrincipal(
        id="00000000-0000-4000-8000-00000000bm01", username="batchmaker", roles=frozenset()
    )
