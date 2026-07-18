"""Integration tests for the subscriber cash-out API.

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
)
from tests.cashout.conftest import (
    SUBSCRIBER_PHONE,
    SUBSCRIBER_PIN,
    cash_out_body,
    cash_out_headers,
    seed_cashout_step_up_policy,
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
    """Full E2E: subscriber debited principal+fee, agent credited, legs balance."""
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
    """No session token -> 401."""
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
    """A user without the cashout permission -> 403."""
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
    """Missing Idempotency-Key header -> 422."""
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
    """An unregistered agent identifier -> 404."""
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
    """A recipient that resolves to a consumer (not an agent) -> 422."""
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
    """A subscriber cashing out to their own identifier -> 422 self_transfer."""
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
    """Same Idempotency-Key returns the original txn; money moves only once."""
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
    """An amount beyond the subscriber's R500 wallet -> 409 insufficient funds."""
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
    """An agent identifier that lives in another tenant -> 404 (isolation)."""
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
    """Cash-out over the step-up threshold without a PIN -> 401 step_up_required."""
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
    """Cash-out over the threshold WITH the correct PIN -> 201."""
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
    """No pricing/limit config → 422, no money moves (invariant #12)."""
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
    """Pricing present but NO cashout limit config → 422, no money moves."""
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
