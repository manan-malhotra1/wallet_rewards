"""Fixtures for the subscriber cash-out tests.

Builds a subscriber (consumer with a funded ZAR wallet, a role granting
`cashout`, a known PIN, and a phone identifier for the self-cash-out case) and
an agent recipient (agent user + ZAR wallet + phone identifier), plus the
pricing / limit / commission / tax configs that reproduce a worked example.

Cash-out is cash-in reversed: the subscriber is the payer and bears the fee;
the agent is the beneficiary and earns the commission.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_pin
from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import create_commission_config
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.limits.schemas import LimitConfigCreateRequest
from app.modules.limits.service import create_limit_config
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config
from app.modules.taxes.schemas import TaxConfigCreateRequest
from app.modules.taxes.service import create_tax_config
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    TXN_STATUS_COMPLETED,
    USER_TYPE_AGENT,
    USER_TYPE_CONSUMER,
    Account,
    Role,
    RolePermission,
    Tenant,
    User,
    UserIdentifier,
    UserRole,
)

SUBSCRIBER_PHONE = "+27 82 555 1000"
AGENT_PHONE = "+27 82 555 7000"
SUBSCRIBER_PIN = "1234"


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
async def subscriber_role(db_session: AsyncSession, test_tenant: Tenant) -> Role:
    """A tenant role granting the `cashout` permission."""
    role = Role(tenant_id=test_tenant.id, name="subscriber_role", description="Grants cashout.")
    db_session.add(role)
    await db_session.flush()
    db_session.add(RolePermission(role_id=role.id, transaction_type="cashout"))
    await db_session.commit()
    await db_session.refresh(role)
    return role


@pytest_asyncio.fixture
async def subscriber(db_session: AsyncSession, test_tenant: Tenant, subscriber_role: Role) -> User:
    """A consumer holding the cashout role, a PIN, and a phone identifier."""
    user = User(
        tenant_id=test_tenant.id,
        user_type=USER_TYPE_CONSUMER,
        pin_hash=hash_pin(SUBSCRIBER_PIN),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=subscriber_role.id))
    db_session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value=SUBSCRIBER_PHONE,
            verified=True,
        )
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def subscriber_wallet(
    db_session: AsyncSession, test_tenant: Tenant, subscriber: User
) -> Account:
    """The subscriber's ZAR financial wallet, funded with R500."""
    wallet = Account(
        tenant_id=test_tenant.id,
        user_id=subscriber.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(wallet)
    await _fund(db_session, test_tenant, wallet, Decimal("500"))
    return wallet


@pytest_asyncio.fixture
async def subscriber_auth_header(subscriber: User) -> dict[str, str]:
    """Session token for the subscriber."""
    from app.auth.sessions import create_session

    token = await create_session(subscriber.id, subscriber.tenant_id, "mobile")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def agent_recipient(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """An agent with a phone identifier (the cash-out beneficiary)."""
    user = User(tenant_id=test_tenant.id, user_type=USER_TYPE_AGENT)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value=AGENT_PHONE,
            verified=True,
        )
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def agent_wallet(
    db_session: AsyncSession, test_tenant: Tenant, agent_recipient: User
) -> Account:
    """The receiving agent's ZAR financial wallet."""
    wallet = Account(
        tenant_id=test_tenant.id,
        user_id=agent_recipient.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(wallet)
    return wallet


@pytest_asyncio.fixture
async def worked_example_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Pricing / limit / commission / tax configs reproducing a worked example.

    A=100 → F=2 (fee EXCLUSIVE, borne by the subscriber on top), C=1 to the
    agent, Tf=0.30 (fee-tax exclusive), Tc=0.15 (commission-tax inclusive).
    Subscriber pays 100 + 2 + 0.30 = 102.30; the agent receives 100 + 0.85
    (net commission) = 100.85.
    """
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("2"),
            fee_inclusive=False,  # subscriber bears the fee on top of the principal
        ),
    )
    # Invariant #12: cashout requires BOTH a pricing AND a limit config for the
    # acting subscriber's scope. Seed a permissive limit so the worked-example
    # tests reach the ledger (amount 100 within a daily count cap of 10).
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await create_commission_config(
        db_session,
        CommissionConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout",
            currency="ZAR",
            fixed_commission=Decimal("1"),
        ),
    )
    await create_tax_config(
        db_session,
        TaxConfigCreateRequest(
            tenant_id=test_tenant.id,
            currency="ZAR",
            fee_tax_pct=Decimal("0.15"),
            commission_tax_pct=Decimal("0.15"),
            fee_tax_inclusive=False,
            commission_tax_inclusive=True,
        ),
    )


async def seed_cashout_step_up_policy(
    session: AsyncSession, tenant: Tenant, *, threshold: str = "100000000"
) -> None:
    """Seed a cashout step-up policy with a threshold ABOVE the test amount.

    Step-up is FAIL-CLOSED: without a cashout policy the subscriber would be
    prompted for a PIN on any amount, turning the money-flow tests into 401s.
    A high threshold takes the below-threshold path so no PIN is required and
    the balance / overdraft / idempotency assertions stay intact. Kept out of
    `worked_example_configs` deliberately — the dedicated step-up tests seed
    their own R50-threshold policy and would collide on the unique index.
    """
    from app.shared.models import StepUpPolicy

    session.add(
        StepUpPolicy(
            tenant_id=tenant.id,
            transaction_type="cashout",
            currency="ZAR",
            threshold_amount=Decimal(threshold),
        )
    )
    await session.commit()


def cash_out_body(amount: str = "100", phone: str = AGENT_PHONE) -> dict:
    """A cash-out request body targeting the agent by phone."""
    return {
        "identifier_type": "phone",
        "identifier_value": phone,
        "amount": amount,
        "currency": "ZAR",
    }


def cash_out_headers(auth: dict[str, str], idem: str | None = None) -> dict[str, str]:
    return {
        **auth,
        "Idempotency-Key": idem or f"cashout-{uuid4().hex[:12]}",
        "Content-Type": "application/json",
    }
