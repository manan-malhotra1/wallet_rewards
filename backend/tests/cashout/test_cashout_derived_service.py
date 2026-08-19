"""Cash-out wired to `resolve_service_code` (Task 6, mechanical replication of
the P2P reference wiring in `tests/payments/test_p2p_derived_service.py`).

An optional `service_code` on the cash-out request is resolved ONCE before any
permission/pricing/limits gate, and the resolved code drives everything
downstream while `base_transaction_type` always records the endpoint's own
base ('cashout'). These tests prove: the omitted-`service_code` path is
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
from tests.cashout.conftest import cash_out_body, cash_out_headers, seed_cashout_step_up_policy
from tests.conftest import make_points_account, reward_event_count, seed_first_time_points_rule


async def _seed_derived_cashout_service(
    session: AsyncSession, tenant: Tenant, code: str = "cashout_express"
) -> Service:
    """Persist a live derived service based on 'cashout' (Task 4 fixture shape)."""
    base = Service(tenant_id=tenant.id, code="cashout", display_name="Cash Out", kind="base")
    session.add(base)
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name="Express Cash Out",
        kind="derived",
        base_service_code="cashout",
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
async def test_omitting_service_code_records_plain_cashout_unchanged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify no `service_code` in the request resolves to 'cashout' byte for byte"""
    await seed_cashout_step_up_policy(db_session, test_tenant)
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(cash_out_body(amount="100")),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "cashout"
    assert txn.base_transaction_type == "cashout"


@pytest.mark.asyncio
async def test_derived_cashout_records_its_own_code_and_base_and_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber: User,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a derived cashout service resolves, records the derived code +
    base 'cashout', and charges a fee that DIFFERS from the base's (pricing /
    limits are never inherited — spec §6.2)."""
    await seed_cashout_step_up_policy(db_session, test_tenant)
    await _seed_derived_cashout_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("7"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, subscriber, "cashout_express")

    body = cash_out_body(amount="100")
    body["service_code"] = "cashout_express"
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(body),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert Decimal(data["fee"]) == Decimal("7")
    assert Decimal(data["fee"]) != Decimal("2")  # differs from the base's worked-example fee

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == data["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "cashout_express"
    assert txn.base_transaction_type == "cashout"


@pytest.mark.asyncio
async def test_reward_rule_on_base_code_does_not_fire_for_derived_cashout(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber: User,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a reward rule targeting the BASE code does NOT fire for a
    derived cashout (spec §8 — precise targeting)."""
    await seed_cashout_step_up_policy(db_session, test_tenant)
    await _seed_derived_cashout_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("7"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, subscriber, "cashout_express")
    await make_points_account(db_session, test_tenant.id, subscriber.id)
    await seed_first_time_points_rule(
        db_session, test_tenant.id, transaction_type="cashout", reward_value=Decimal("50")
    )

    body = cash_out_body(amount="100")
    body["service_code"] = "cashout_express"
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(body),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["earned_points"] == 0
    assert await reward_event_count(db_session, subscriber.id) == 0


@pytest.mark.asyncio
async def test_reward_rule_on_derived_code_fires_for_derived_cashout(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    subscriber: User,
    subscriber_wallet: Account,
    agent_wallet: Account,
    worked_example_configs: None,
    subscriber_auth_header: dict[str, str],
) -> None:
    """Verify a reward rule targeting the DERIVED code DOES fire — the reward
    trigger carries the resolved service code, not the base literal."""
    await seed_cashout_step_up_policy(db_session, test_tenant)
    await _seed_derived_cashout_service(db_session, test_tenant)
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("7"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cashout_express",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await _grant_permission(db_session, subscriber, "cashout_express")
    await make_points_account(db_session, test_tenant.id, subscriber.id)
    await seed_first_time_points_rule(
        db_session, test_tenant.id, transaction_type="cashout_express", reward_value=Decimal("50")
    )

    body = cash_out_body(amount="100")
    body["service_code"] = "cashout_express"
    resp = await async_client.post(
        "/api/v1/cashout",
        content=json.dumps(body),
        headers=cash_out_headers(subscriber_auth_header),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["earned_points"] == 50
    assert await reward_event_count(db_session, subscriber.id) == 1
