"""Cash-in wired to `resolve_service_code` (Task 6, mechanical replication of
the P2P reference wiring in `tests/payments/test_p2p_derived_service.py`).

An optional `service_code` on the cash-in request is resolved ONCE before any
permission/pricing/limits gate, and the resolved code drives everything
downstream while `base_transaction_type` always records the endpoint's own
base ('cash_in'). These tests prove: the omitted-`service_code` path is
unchanged, and a derived service records its own code + the base, charging
its own (different) fee.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.schemas import LimitConfigCreateRequest
from app.modules.limits.service import create_limit_config
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Role,
    RolePermission,
    Service,
    Tenant,
    Transaction,
    User,
    UserRole,
)
from tests.cashin.conftest import cash_in_body, cash_in_headers
from tests.conftest import make_points_account, reward_event_count, seed_first_time_points_rule


async def _seed_derived_cash_in_service(
    session: AsyncSession, tenant: Tenant, code: str = "cash_in_express"
) -> Service:
    """Persist a live derived service based on 'cash_in' (Task 4 fixture shape)."""
    base = Service(tenant_id=tenant.id, code="cash_in", display_name="Cash In", kind="base")
    session.add(base)
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name="Express Cash In",
        kind="derived",
        base_service_code="cash_in",
    )
    session.add(row)
    await session.commit()
    return row


async def _grant_permission(session: AsyncSession, user: User, transaction_type: str) -> None:
    """Grant `user` a role permitting `transaction_type`."""
    role = Role(tenant_id=user.tenant_id, name=f"grant-{transaction_type}-{uuid4().hex[:8]}")
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, transaction_type=transaction_type, permitted=True))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()


@pytest.mark.asyncio
async def test_omitting_service_code_records_plain_cash_in_unchanged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Verify no `service_code` in the request resolves to 'cash_in' byte for byte"""
    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body(amount="100")),
        headers=cash_in_headers(agent_auth_header),
    )
    assert resp.status_code == 201, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "cash_in"
    assert txn.base_transaction_type == "cash_in"


@pytest.mark.asyncio
async def test_derived_cash_in_records_its_own_code_and_base_and_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent: User,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Verify a derived cash-in service resolves, records the derived code +
    base 'cash_in', and charges a fee that DIFFERS from the base's (pricing /
    limits are never inherited — spec §6.2)."""
    await _seed_derived_cash_in_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("5"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, agent, "cash_in_express")

    body = cash_in_body(amount="100")
    body["service_code"] = "cash_in_express"
    resp = await async_client.post(
        "/api/v1/cashin", content=json.dumps(body), headers=cash_in_headers(agent_auth_header)
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert Decimal(data["fee"]) == Decimal("5")
    assert Decimal(data["fee"]) != Decimal("2")  # differs from the base's worked-example fee

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == data["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "cash_in_express"
    assert txn.base_transaction_type == "cash_in"


@pytest.mark.asyncio
async def test_reward_rule_on_base_code_does_not_fire_for_derived_cash_in(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent: User,
    customer: User,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Verify a reward rule targeting the BASE code does NOT fire for a
    derived cash-in (spec §8 — precise targeting, a derived service needs its
    own rule)."""
    await _seed_derived_cash_in_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("5"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, agent, "cash_in_express")
    await make_points_account(db_session, test_tenant.id, customer.id)
    # Rule targets the BASE 'cash_in' — must not fire for the derived txn.
    await seed_first_time_points_rule(
        db_session, test_tenant.id, transaction_type="cash_in", reward_value=Decimal("50")
    )

    body = cash_in_body(amount="100")
    body["service_code"] = "cash_in_express"
    resp = await async_client.post(
        "/api/v1/cashin", content=json.dumps(body), headers=cash_in_headers(agent_auth_header)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["earned_points"] == 0
    assert await reward_event_count(db_session, customer.id) == 0


@pytest.mark.asyncio
async def test_reward_rule_on_derived_code_fires_for_derived_cash_in(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent: User,
    customer: User,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Verify a reward rule targeting the DERIVED code DOES fire — the
    reward trigger carries the resolved service code, not the base literal."""
    await _seed_derived_cash_in_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("5"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, agent, "cash_in_express")
    await make_points_account(db_session, test_tenant.id, customer.id)
    # Rule targets the DERIVED code — must fire.
    await seed_first_time_points_rule(
        db_session, test_tenant.id, transaction_type="cash_in_express", reward_value=Decimal("50")
    )

    body = cash_in_body(amount="100")
    body["service_code"] = "cash_in_express"
    resp = await async_client.post(
        "/api/v1/cashin", content=json.dumps(body), headers=cash_in_headers(agent_auth_header)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["earned_points"] == 50
    assert await reward_event_count(db_session, customer.id) == 1
