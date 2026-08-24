"""Cash-out eligibility comes from the catalog, not a hardcoded tuple.

`_assert_recipient_is_agent` gated the receiving side on
`(USER_TYPE_AGENT, USER_TYPE_SUPER_AGENT)` — a literal pair frozen before user
types became runtime data. A tenant's own Retail type (the spec's own "tiered
agent" example) could be created, priced and capped, and still not receive a
cash-out. Same class as the `services.allowed_user_types` allowlist.

Eligibility is now "the recipient's type sits in the `retail` category", which
is what the category means: Retail is the agent-shaped tier, Consumers are the
subscribers who pay into it, Business is merchant collection. A custom Retail
type is therefore eligible on creation, with no second list to remember.

Covers both directions: a custom Retail recipient completes, and a Consumers
recipient is still refused with 422 `recipient_not_agent`.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    CATEGORY_CONSUMER,
    CATEGORY_RETAIL,
    Account,
    Tenant,
    User,
    UserIdentifier,
)
from tests.cashout.conftest import (
    cash_out_body,
    cash_out_headers,
    seed_cashout_step_up_policy,
)

pytestmark = pytest.mark.asyncio

TIERED_AGENT_PHONE = "+27 82 555 8100"


async def _make_recipient(
    session: AsyncSession,
    tenant: Tenant,
    *,
    type_code: str,
    category_code: str,
    phone: str,
) -> User:
    """Create a custom type, a user carrying it, a ZAR wallet and a phone.

    Args:
        session: Async DB session (commits).
        tenant: The owning tenant.
        type_code: The custom user type to create and assign.
        category_code: The category the type sits in — the eligibility axis
            under test.
        phone: The identifier the payer will name.

    Returns:
        The persisted recipient `User`.
    """
    await create_user_type(
        session,
        UserTypeCreateRequest(
            tenant_id=tenant.id,
            code=type_code,
            label=type_code.title(),
            category_code=category_code,
        ),
    )
    user = User(tenant_id=tenant.id, user_type=type_code)
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
    session.add(
        Account(
            tenant_id=tenant.id,
            user_id=user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await session.commit()
    await session.refresh(user)
    return user


async def test_a_custom_retail_type_can_receive_a_cash_out(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify the spec's own 'tiered agent' example can be cashed out to

    The recipient is a tenant-defined Retail type — not `agent`, not
    `super_agent`. Under the hardcoded tuple it was refused with
    `recipient_not_agent` no matter how it was configured.
    """
    recipient = await _make_recipient(
        db_session,
        test_tenant,
        type_code="tiered_agent",
        category_code=CATEGORY_RETAIL,
        phone=TIERED_AGENT_PHONE,
    )
    # Step-up is fail-closed: without a cashout policy any amount prompts for a
    # PIN and the request 401s before it reaches the ledger.
    await seed_cashout_step_up_policy(db_session, test_tenant)

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(phone=TIERED_AGENT_PHONE)),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["agent_user_id"] == str(recipient.id)

    # The money actually landed — a 201 with no credit would be a hollow pass.
    wallet = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.user_id == recipient.id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                Account.currency == "ZAR",
            )
        )
    ).scalar_one()
    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance > Decimal("0")


async def test_a_custom_consumers_type_is_still_refused(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify widening to the catalog did not open cash-out to every type

    A custom type in the Consumers category is another subscriber, not an
    agent, and must still be refused.
    """
    await _make_recipient(
        db_session,
        test_tenant,
        type_code="student",
        category_code=CATEGORY_CONSUMER,
        phone="+27 82 555 8200",
    )

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(phone="+27 82 555 8200")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "recipient_not_agent"
