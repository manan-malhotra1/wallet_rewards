"""Value-based rewards.

Drives the engine through the INTERNAL wallet-outbox path — a direct
`evaluate_and_issue_firings` call shaped like `reward_outbox` rows
(`source_key="internal:wallet"`) — because `test_tenant` is a `both`-mode
tenant, where rewards come from the wallet outbox and external HTTP ingest is
correctly rejected (`wrong_mode`). The rule itself is still created via the
public admin API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.schemas import NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Tenant,
    User,
)


async def _ensure_system_points(session: AsyncSession, tenant: Tenant) -> None:
    """Create the tenant's system_points_issuance master account."""
    existing = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Account(
                tenant_id=tenant.id,
                account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
                currency="PTS",
            )
        )
        await session.commit()


async def _create_value_based_rule(
    client: AsyncClient,
    tenant: Tenant,
    *,
    transaction_type: str = "fund",
    min_amount: str = "100",
    reward_value: str = "50",
    stop_after_n_triggers: int | None = None,
) -> None:
    """Create a value_based rule via the public API."""
    body = {
        "tenant_id": str(tenant.id),
        "name": f"value-{uuid4().hex[:6]}",
        "rule_type": "value_based",
        "transaction_type": transaction_type,
        "min_amount": min_amount,
        "reward_type": "points",
        "reward_value": reward_value,
    }
    if stop_after_n_triggers is not None:
        body["stop_after_n_triggers"] = stop_after_n_triggers
    resp = await client.post("/api/v1/rules", json=body)
    assert resp.status_code == 201, resp.text


async def _ingest(
    session: AsyncSession, tenant: Tenant, user: User, *, amount: str, txn_type: str = "fund"
) -> int:
    """Drive one internal wallet event through the evaluator; return firings fired.

    Mirrors how `reward_outbox` shapes an event for `evaluate_and_issue_firings`:
    an `internal:wallet` source, a per-transaction event_id (idempotency key),
    and no merchant.
    """
    event = NormalisedEvent(
        event_id=uuid4().hex,
        source_key="internal:wallet",
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type=txn_type,
        amount=Decimal(amount),
        currency="ZAR",
        merchant_id=None,
        timestamp=datetime.now(UTC),
    )
    firings = await evaluate_and_issue_firings(session, event)
    return len(firings)


@pytest.mark.asyncio
async def test_value_based_fires_when_amount_meets_threshold(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer earns a reward when a transaction meets the minimum amount"""
    await _ensure_system_points(db_session, test_tenant)
    await _create_value_based_rule(async_client, test_tenant, min_amount="100")

    # Also need the user's points account so issuance can credit.
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type="points_account",
            currency="PTS",
        )
    )
    await db_session.commit()

    assert await _ingest(db_session, test_tenant, test_user, amount="500") == 1


@pytest.mark.asyncio
async def test_value_based_does_not_fire_below_threshold(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer earns no reward when a transaction is below the minimum amount"""
    await _ensure_system_points(db_session, test_tenant)
    await _create_value_based_rule(async_client, test_tenant, min_amount="100")

    assert await _ingest(db_session, test_tenant, test_user, amount="50") == 0


@pytest.mark.asyncio
async def test_value_based_stop_after_n_triggers(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a value-based rule stops rewarding a customer after its trigger limit"""
    await _ensure_system_points(db_session, test_tenant)
    await _create_value_based_rule(
        async_client, test_tenant, min_amount="100", stop_after_n_triggers=2
    )
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type="points_account",
            currency="PTS",
        )
    )
    await db_session.commit()

    outcomes = [await _ingest(db_session, test_tenant, test_user, amount="500") for _ in range(3)]
    assert outcomes == [1, 1, 0]


@pytest.mark.asyncio
async def test_value_based_requires_min_amount_on_create(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a value-based rule is rejected when its minimum amount is missing"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "bad-vb",
            "rule_type": "value_based",
            "transaction_type": "fund",
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422
