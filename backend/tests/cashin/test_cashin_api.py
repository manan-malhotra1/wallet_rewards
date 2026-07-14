"""Integration tests for the agent cash-in API (Pricing v2 Epic 21).

POST /api/v1/cashin: an agent funds a customer's wallet from the agent's float
and earns a commission; fee + tax settle into the system wallets. Covers the
happy path (E2E balances match the design worked example), auth/permission,
validation, tenant isolation, idempotency replay, and agent-float overdraft.
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
    ACCOUNT_TYPE_TAXES,
    Account,
    Tenant,
)
from tests.cashin.conftest import cash_in_body, cash_in_headers


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
async def test_cash_in_happy_path_matches_worked_example(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Full E2E: all five balances match the design spec's worked example."""
    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body(amount="100")),
        headers=cash_in_headers(agent_auth_header),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert Decimal(data["fee"]) == Decimal("2")
    assert Decimal(data["commission"]) == Decimal("1")
    assert Decimal(data["tax"]) == Decimal("0.45")

    fee_acct = await _system_account(db_session, test_tenant, ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED)
    commission_acct = await _system_account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION)
    taxes_acct = await _system_account(db_session, test_tenant, ACCOUNT_TYPE_TAXES)

    # customer receives A - F - Tf = 100 - 2 - 0.30
    assert await _balance(db_session, customer_wallet.id) == Decimal("97.70")
    # agent: 500 - 100 (principal, fee inclusive) + 0.85 (commission net) = 400.85
    assert await _balance(db_session, agent_float.id) == Decimal("400.85")
    assert await _balance(db_session, fee_acct.id) == Decimal("2")
    assert await _balance(db_session, commission_acct.id) == Decimal("-1")  # pool paid out
    assert await _balance(db_session, taxes_acct.id) == Decimal("0.45")  # 0.30 + 0.15


@pytest.mark.asyncio
async def test_cash_in_requires_auth(
    async_client: AsyncClient, worked_example_configs: None
) -> None:
    """No session token -> 401."""
    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body()),
        headers={"Idempotency-Key": "x", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cash_in_permission_denied(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    customer_wallet: Account,
    worked_example_configs: None,
) -> None:
    """A user without the cash_in permission -> 403."""
    from app.auth.sessions import create_session
    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, User

    # A plain user (no role) with a funded ZAR wallet.
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
        "/api/v1/cashin",
        content=json.dumps(cash_in_body()),
        headers=cash_in_headers({"Authorization": f"Bearer {token}"}),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cash_in_missing_idempotency_key_422(
    async_client: AsyncClient,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Missing Idempotency-Key header -> 422."""
    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body()),
        headers={**agent_auth_header, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cash_in_unknown_customer_404(
    async_client: AsyncClient,
    agent_float: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """An unregistered customer identifier -> 404."""
    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body(phone="+27 82 000 0000")),
        headers=cash_in_headers(agent_auth_header),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cash_in_idempotent_replay(
    async_client: AsyncClient,
    db_session: AsyncSession,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Same Idempotency-Key returns the original txn; money moves only once."""
    headers = cash_in_headers(agent_auth_header, idem="cashin-replay-1")
    first = await async_client.post(
        "/api/v1/cashin", content=json.dumps(cash_in_body(amount="100")), headers=headers
    )
    assert first.status_code == 201, first.text
    second = await async_client.post(
        "/api/v1/cashin", content=json.dumps(cash_in_body(amount="100")), headers=headers
    )
    assert second.status_code == 201, second.text
    assert second.json()["transaction_id"] == first.json()["transaction_id"]
    # Customer credited exactly once.
    assert await _balance(db_session, customer_wallet.id) == Decimal("97.70")


@pytest.mark.asyncio
async def test_cash_in_overdraft_on_agent_float_409(
    async_client: AsyncClient,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """An amount beyond the agent's R500 float -> 409 insufficient funds."""
    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body(amount="100000")),
        headers=cash_in_headers(agent_auth_header),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cash_in_tenant_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    other_tenant: Tenant,
    agent_float: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """A customer identifier that lives in another tenant -> 404 (isolation)."""
    from app.shared.models import User, UserIdentifier

    other_user = User(tenant_id=other_tenant.id)
    db_session.add(other_user)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=other_user.id,
            tenant_id=other_tenant.id,
            identifier_type="phone",
            identifier_value="+27 82 999 1111",
            verified=True,
        )
    )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body(phone="+27 82 999 1111")),
        headers=cash_in_headers(agent_auth_header),
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# Fail-closed service gating (Epic 23, Story 23.2)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cash_in_fails_closed_when_flag_on_and_limit_config_missing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Flag on + pricing present but NO cash_in limit config → 422, no money moves.

    Closes the M-01 gap: cash_in must honour the same "pricing AND limits"
    contract as p2p / airtime when the tenant is fail-closed.
    """
    test_tenant.require_config_to_transact = True
    await db_session.commit()

    before = await derive_balance(db_session, agent_float.id)

    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body(amount="100")),
        headers=cash_in_headers(agent_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    assert await derive_balance(db_session, agent_float.id) == before


@pytest.mark.asyncio
async def test_cash_in_succeeds_when_flag_on_and_both_configs_present(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Flag on + pricing AND a cash_in limit config present → cash-in proceeds."""
    from app.modules.limits.schemas import LimitConfigCreateRequest
    from app.modules.limits.service import create_limit_config
    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET

    test_tenant.require_config_to_transact = True
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body(amount="100")),
        headers=cash_in_headers(agent_auth_header),
    )
    assert resp.status_code == 201, resp.text
