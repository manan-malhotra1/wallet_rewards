"""Customer cash-out to an agent.

POST /api/v1/cashout: a subscriber (consumer) sends money to an agent — the
mirror of agent cash-in. The subscriber is debited (principal + fee), the agent
is credited the principal and earns a commission; fee + tax settle into the
system wallets. Covers the happy-path balances, auth/permission, validation,
the agent-type guard, self cash-out, tenant isolation, idempotency replay,
subscriber overdraft, step-up, and the invariant #12 fail-closed gate.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_TAX_COMMISSION,
    ACCOUNT_TYPE_TAX_SERVICE,
    Account,
    Tenant,
    User,
)
from tests.cashout.conftest import (
    SUBSCRIBER_PHONE,
    SUBSCRIBER_PIN,
    cash_out_body,
    cash_out_headers,
    seed_cashout_step_up_policy,
)
from tests.conftest import (
    make_points_account,
    reward_event_count,
    seed_first_time_points_rule,
)


async def _balance(session: AsyncSession, account_id) -> Decimal:
    balance, _ = await derive_balance(session, account_id)
    return balance


async def _system_account(session: AsyncSession, tenant: Tenant, account_type: str) -> Account:
    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == account_type,
                Account.currency == "ZAR",
                Account.user_id.is_(None),
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_cash_out_happy_path_matches_worked_example(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a customer cashing out to an agent moves money and commission to the right places"""
    await seed_cashout_step_up_policy(db_session, test_tenant)
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(amount="100")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert Decimal(data["fee"]) == Decimal("2")
    assert Decimal(data["commission"]) == Decimal("1")
    assert Decimal(data["tax"]) == Decimal("0.45")

    fee_acct = await _system_account(db_session, test_tenant, ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED)
    commission_acct = await _system_account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION)
    service_tax_acct = await _system_account(db_session, test_tenant, ACCOUNT_TYPE_TAX_SERVICE)
    commission_tax_acct = await _system_account(
        db_session, test_tenant, ACCOUNT_TYPE_TAX_COMMISSION
    )

    # Subscriber (payer): 500 - 100 - 2 (fee on top) - 0.30 (fee-tax on top) = 397.70
    assert await _balance(db_session, subscriber_wallet.id) == Decimal("397.70")
    # Agent (beneficiary): 100 (principal) + 0.85 (net commission) = 100.85
    assert await _balance(db_session, agent_wallet.id) == Decimal("100.85")
    assert await _balance(db_session, fee_acct.id) == Decimal("2")
    assert await _balance(db_session, commission_acct.id) == Decimal("-1")  # pool paid out
    assert await _balance(db_session, service_tax_acct.id) == Decimal("0.30")
    assert await _balance(db_session, commission_tax_acct.id) == Decimal("0.15")


@pytest.mark.asyncio
async def test_cash_out_requires_auth(
    async_client: AsyncClient, worked_example_configs: None
) -> None:
    """Verify an unauthenticated customer cannot cash out"""
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body()),
        headers={"Idempotency-Key": "x", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cash_out_permission_denied(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent_wallet: Account,
    worked_example_configs: None,
) -> None:
    """Verify a user without cash-out permission cannot cash out"""
    from app.auth.sessions import create_session
    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, User

    user = User(tenant_id=test_tenant.id)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()
    token = await create_session(user.id, test_tenant.id, "mobile")

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body()),
        headers=cash_out_headers({"Authorization": f"Bearer {token}"}),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cash_out_missing_idempotency_key_422(
    async_client: AsyncClient,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a cash-out must carry an idempotency key"""
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body()),
        headers={**subscriber_auth_header, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cash_out_unknown_agent_404(
    async_client: AsyncClient,
    subscriber_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify cashing out to an unknown agent is refused"""
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(phone="+27 82 000 0000")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cash_out_recipient_not_agent_422(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a customer can only cash out to an agent, not another customer"""
    from app.shared.models import USER_TYPE_CONSUMER, User, UserIdentifier

    other_consumer = User(tenant_id=test_tenant.id, user_type=USER_TYPE_CONSUMER)
    db_session.add(other_consumer)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=other_consumer.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value="+27 82 555 2222",
            verified=True,
        )
    )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(phone="+27 82 555 2222")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "recipient_not_agent"


@pytest.mark.asyncio
async def test_cash_out_to_self_422(
    async_client: AsyncClient,
    subscriber_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a customer cannot cash out to themselves"""
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(phone=SUBSCRIBER_PHONE)),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "self_transfer_not_allowed"


@pytest.mark.asyncio
async def test_cash_out_idempotent_replay(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify sending the same cash-out twice moves money only once"""
    # Fail-closed step-up: seed a high-threshold policy so R100 needs no PIN.
    await seed_cashout_step_up_policy(db_session, test_tenant)
    headers = cash_out_headers(subscriber_auth_header, idem="cashout-replay-1")
    first = await async_client.post(
        "/api/v1/cashout", content=json.dumps(cash_out_body(amount="100")), headers=headers
    )
    assert first.status_code == 201, first.text
    second = await async_client.post(
        "/api/v1/cashout", content=json.dumps(cash_out_body(amount="100")), headers=headers
    )
    assert second.status_code == 201, second.text
    assert second.json()["transaction_id"] == first.json()["transaction_id"]
    # Agent credited exactly once.
    assert await _balance(db_session, agent_wallet.id) == Decimal("100.85")
    # Subscriber debited exactly once.
    assert await _balance(db_session, subscriber_wallet.id) == Decimal("397.70")


@pytest.mark.asyncio
async def test_cash_out_overdraft_on_subscriber_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a customer cannot cash out more than their wallet holds"""
    # High-threshold policy so the amount takes the below-threshold (no-PIN)
    # path and reaches the overdraft check rather than a step-up 401.
    await seed_cashout_step_up_policy(db_session, test_tenant)
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(amount="100000")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cash_out_tenant_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    other_tenant: Tenant,
    subscriber_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a customer cannot cash out to an agent belonging to another tenant"""
    from app.shared.models import USER_TYPE_AGENT, User, UserIdentifier

    other_agent = User(tenant_id=other_tenant.id, user_type=USER_TYPE_AGENT)
    db_session.add(other_agent)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=other_agent.id,
            tenant_id=other_tenant.id,
            identifier_type="phone",
            identifier_value="+27 82 999 1111",
            verified=True,
        )
    )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(phone="+27 82 999 1111")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# Step-up (Phase H) — cashout over the policy threshold requires the PIN
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cash_out_step_up_required_without_pin(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a large cash-out asks the customer for their PIN"""
    from app.shared.models import StepUpPolicy

    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="cashout",
            currency="ZAR",
            threshold_amount=Decimal("50"),
        )
    )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(amount="100")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["error_code"] == "step_up_required"


@pytest.mark.asyncio
async def test_cash_out_step_up_verified_with_pin(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a large cash-out completes when the customer enters the correct PIN"""
    from app.shared.models import StepUpPolicy

    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="cashout",
            currency="ZAR",
            threshold_amount=Decimal("50"),
        )
    )
    await db_session.commit()

    body = {**cash_out_body(amount="100"), "pin": SUBSCRIBER_PIN}
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(body),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text


# -----------------------------------------------------------------------------
# Invariant #12 — UNCONDITIONAL fail-closed (no tenant flag involved)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cash_out_fails_closed_when_no_config_at_all(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    agent_wallet: Account,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a cash-out is refused and no money moves when the service is unconfigured"""
    assert test_tenant.require_config_to_transact is False  # flag plays no role
    before, _ = await derive_balance(db_session, subscriber_wallet.id)

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(amount="100")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    after, _ = await derive_balance(db_session, subscriber_wallet.id)
    assert after == before


@pytest.mark.asyncio
async def test_cash_out_fails_closed_when_pricing_present_but_limit_missing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    agent_wallet: Account,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a cash-out is refused when limits are missing even if pricing exists"""
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config
    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET

    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("2"),
        ),
    )
    await db_session.commit()

    before, _ = await derive_balance(db_session, subscriber_wallet.id)

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(amount="100")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    after, _ = await derive_balance(db_session, subscriber_wallet.id)
    assert after == before


@pytest.mark.asyncio
async def test_cash_out_in_both_mode_earns_the_subscriber_points(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber: User,
    agent_recipient: User,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a cash-out rewards the withdrawing SUBSCRIBER, not the agent.

    In a full wallet+rewards ('both') tenant with an active first-transaction
    rule, a subscriber cashing out to an agent earns the configured points
    (the receiving agent earns commission, not rewards), and the cash-out
    response surfaces them inline as `earned_points`.
    """
    await seed_cashout_step_up_policy(db_session, test_tenant)
    # The reward recipient (subscriber) needs a points account for the CREDIT.
    await make_points_account(db_session, test_tenant.id, subscriber.id)
    # The reward tag is the CANONICAL ledger transaction_type "cashout" — the
    # same value the service posts and admins configure rules against.
    await seed_first_time_points_rule(
        db_session, test_tenant.id, transaction_type="cashout", reward_value=Decimal("50")
    )

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(amount="100")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["earned_points"] == 50

    # A reward_events row was issued to the SUBSCRIBER — never the receiving agent.
    assert await reward_event_count(db_session, subscriber.id) == 1
    assert await reward_event_count(db_session, agent_recipient.id) == 0


@pytest.mark.asyncio
async def test_cash_out_in_wallet_mode_earns_no_points(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber: User,
    agent_recipient: User,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a wallet-only deployment never rewards a cash-out (mode gate holds).

    Mirror of the both-mode test with the tenant flipped to 'wallet': even with
    an active first-transaction rule and the subscriber's points account present,
    a wallet-mode tenant writes NO reward_outbox row, issues NO reward, and
    returns `earned_points` 0 — proving the business_type gate holds end-to-end.
    """
    from sqlalchemy import func

    from app.shared.models.rewards import RewardOutbox

    await seed_cashout_step_up_policy(db_session, test_tenant)
    # Same seeding as both-mode: points account + an active first-cashout rule.
    await make_points_account(db_session, test_tenant.id, subscriber.id)
    await seed_first_time_points_rule(
        db_session, test_tenant.id, transaction_type="cashout", reward_value=Decimal("50")
    )
    # Flip the deployment mode to wallet-only — the reward gate reads business_type.
    test_tenant.business_type = "wallet"
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(amount="100")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["earned_points"] == 0

    # No reward issued to anyone, and no outbox row was ever enqueued.
    assert await reward_event_count(db_session, subscriber.id) == 0
    assert await reward_event_count(db_session, agent_recipient.id) == 0
    outbox_rows = (
        await db_session.execute(
            select(func.count())
            .select_from(RewardOutbox)
            .where(RewardOutbox.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert outbox_rows == 0
