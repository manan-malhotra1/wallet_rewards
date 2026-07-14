"""Fixtures for the agent cash-in tests (Pricing v2 Epic 21).

Builds an agent (funded ZAR float + a role granting `cash_in` + session token)
and a customer (ZAR wallet + phone identifier), plus the pricing / commission /
tax configs that reproduce the design spec's worked example.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import create_commission_config
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
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
            transaction_type="top_up",
            currency=wallet.currency,
            status=TXN_STATUS_COMPLETED,
            entries=[
                LedgerEntryRequest(account_id=inflow.id, entry_type=ENTRY_DEBIT, amount=amount),
                LedgerEntryRequest(account_id=wallet.id, entry_type=ENTRY_CREDIT, amount=amount),
            ],
        ),
    )


@pytest_asyncio.fixture
async def agent_role(db_session: AsyncSession, test_tenant: Tenant) -> Role:
    """A tenant role granting the `cash_in` permission."""
    role = Role(tenant_id=test_tenant.id, name="agent_role", description="Grants cash_in.")
    db_session.add(role)
    await db_session.flush()
    db_session.add(RolePermission(role_id=role.id, transaction_type="cash_in"))
    await db_session.commit()
    await db_session.refresh(role)
    return role


@pytest_asyncio.fixture
async def agent(db_session: AsyncSession, test_tenant: Tenant, agent_role: Role) -> User:
    """An agent user holding the cash_in role."""
    user = User(tenant_id=test_tenant.id, user_type=USER_TYPE_AGENT)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=agent_role.id))
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def agent_float(db_session: AsyncSession, test_tenant: Tenant, agent: User) -> Account:
    """The agent's ZAR financial wallet, funded with R500."""
    wallet = Account(
        tenant_id=test_tenant.id,
        user_id=agent.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(wallet)
    await _fund(db_session, test_tenant, wallet, Decimal("500"))
    return wallet


@pytest_asyncio.fixture
async def agent_auth_header(agent: User) -> dict[str, str]:
    """Session token for the agent."""
    from app.auth.sessions import create_session

    token = await create_session(agent.id, agent.tenant_id, "mobile")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def customer(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """A customer with a phone identifier (the cash-in beneficiary)."""
    user = User(tenant_id=test_tenant.id, user_type=USER_TYPE_CONSUMER)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value="+27 82 555 7000",
            verified=True,
        )
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def customer_wallet(db_session: AsyncSession, test_tenant: Tenant, customer: User) -> Account:
    """The customer's ZAR financial wallet."""
    wallet = Account(
        tenant_id=test_tenant.id,
        user_id=customer.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(wallet)
    return wallet


@pytest_asyncio.fixture
async def worked_example_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Pricing / commission / tax configs reproducing the design worked example.

    A=100 → F=2 (fee inclusive), C=1, Tf=0.30 (fee-tax exclusive),
    Tc=0.15 (commission-tax inclusive).
    """
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("2"),
            fee_inclusive=True,
        ),
    )
    await create_commission_config(
        db_session,
        CommissionConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in",
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


def cash_in_body(amount: str = "100", phone: str = "+27 82 555 7000") -> dict:
    """A cash-in request body targeting the customer by phone."""
    return {
        "customer": {"identifier_type": "phone", "identifier_value": phone},
        "amount": amount,
        "currency": "ZAR",
    }


def cash_in_headers(auth: dict[str, str], idem: str | None = None) -> dict[str, str]:
    return {
        **auth,
        "Idempotency-Key": idem or f"cashin-{uuid4().hex[:12]}",
        "Content-Type": "application/json",
    }
