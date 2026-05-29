"""Tests for manual resolve + audit log query (Phase E.1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.rewards.service import issue_points_reward
from app.shared.models import (
    REDEMPTION_STATUS_COMPLETED,
    REDEMPTION_STATUS_FAILED,
    Account,
    AuditLog,
    Redemption,
    Rule,
    Tenant,
    User,
)


async def _push_redemption_into_manual_review(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    amount: Decimal,
    *,
    seed_key: str,
) -> Redemption:
    """Initiate + age + sweep twice (max_retries=1) -> MANUAL_REVIEW."""
    rule = Rule(
        tenant_id=tenant.id,
        name=f"seed-mr-{seed_key}",
        rule_type="first_time",
        transaction_type="seed",
        reward_type="points",
        reward_value=amount + Decimal("10"),
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    await issue_points_reward(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        rule=rule,
        triggering_event_id=f"seed-mr-{seed_key}",
        reward_value=amount + Decimal("10"),
    )

    provider_resp = await async_client.post(
        "/api/v1/redemption/providers",
        json={
            "tenant_id": str(tenant.id),
            "name": f"P-mr-{seed_key}",
            "max_retries": 1,
        },
    )
    provider_id = provider_resp.json()["id"]

    init = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "tenant_id": str(tenant.id),
            "user_id": str(user.id),
            "provider_id": provider_id,
            "points_amount": str(amount),
        },
    )
    redemption_id = init.json()["id"]

    # Backdate + sweep so the sweep escalates it.
    redemption = (await db_session.execute(
        select(Redemption).where(Redemption.id == redemption_id)
    )).scalar_one()
    redemption.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await db_session.commit()

    await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(tenant.id), "threshold_minutes": 5},
    )
    await db_session.refresh(redemption)
    assert redemption.status == "MANUAL_REVIEW"
    return redemption


@pytest.mark.asyncio
async def test_manual_resolve_completed_finalises_redemption(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Manual resolve COMPLETED: ledger PENDING -> COMPLETED, balance drops."""
    redemption = await _push_redemption_into_manual_review(
        async_client,
        db_session,
        test_tenant,
        test_user,
        Decimal("50"),
        seed_key="comp",
    )

    response = await async_client.post(
        f"/api/v1/reconciliation/{redemption.id}/resolve",
        json={
            "tenant_id": str(test_tenant.id),
            "outcome": "COMPLETED",
            "reason": "operator confirmed with Mukuru by phone",
            "external_reference": "MUKURU-MANUAL-001",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == REDEMPTION_STATUS_COMPLETED
    assert body["external_reference"] == "MUKURU-MANUAL-001"

    # Available balance permanently drops by the redeemed amount.
    balance, reserved = await derive_balance(db_session, user_points.id)
    # Initial: granted (amount+10) = 60. Redeemed 50. Final balance: 10.
    assert balance == Decimal("10")
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_manual_resolve_reversed_restores_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Manual resolve REVERSED: ledger PENDING -> REVERSED, balance restored."""
    redemption = await _push_redemption_into_manual_review(
        async_client,
        db_session,
        test_tenant,
        test_user,
        Decimal("40"),
        seed_key="rev",
    )

    response = await async_client.post(
        f"/api/v1/reconciliation/{redemption.id}/resolve",
        json={
            "tenant_id": str(test_tenant.id),
            "outcome": "REVERSED",
            "reason": "provider unreachable for 24h",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == REDEMPTION_STATUS_FAILED

    # Initial: granted 50. Redemption reversed → balance back to 50.
    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("50")
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_manual_resolve_rejects_non_manual_review(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Resolve only works against MANUAL_REVIEW — PENDING redemption rejects."""
    # Make a PENDING redemption WITHOUT pushing into MANUAL_REVIEW.
    rule = Rule(
        tenant_id=test_tenant.id,
        name="seed-pending",
        rule_type="first_time",
        transaction_type="seed",
        reward_type="points",
        reward_value=Decimal("60"),
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    await issue_points_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        rule=rule,
        triggering_event_id="pending-only",
        reward_value=Decimal("60"),
    )

    provider_resp = await async_client.post(
        "/api/v1/redemption/providers",
        json={"tenant_id": str(test_tenant.id), "name": "P-pending"},
    )
    init = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "provider_id": provider_resp.json()["id"],
            "points_amount": "10",
        },
    )
    redemption_id = init.json()["id"]

    response = await async_client.post(
        f"/api/v1/reconciliation/{redemption_id}/resolve",
        json={
            "tenant_id": str(test_tenant.id),
            "outcome": "COMPLETED",
            "reason": "trying to skip the queue",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "redemption_not_in_manual_review"


@pytest.mark.asyncio
async def test_manual_resolve_cross_tenant_rejects(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Cross-tenant resolve -> 404 (no existence leak)."""
    redemption = await _push_redemption_into_manual_review(
        async_client,
        db_session,
        test_tenant,
        test_user,
        Decimal("20"),
        seed_key="xt",
    )

    response = await async_client.post(
        f"/api/v1/reconciliation/{redemption.id}/resolve",
        json={
            "tenant_id": str(other_tenant.id),
            "outcome": "COMPLETED",
            "reason": "wrong tenant",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "redemption_not_found"


@pytest.mark.asyncio
async def test_manual_resolve_writes_audit_entry(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Resolve writes an audit_log row with before/after state + actor=admin."""
    redemption = await _push_redemption_into_manual_review(
        async_client,
        db_session,
        test_tenant,
        test_user,
        Decimal("15"),
        seed_key="aud",
    )

    await async_client.post(
        f"/api/v1/reconciliation/{redemption.id}/resolve",
        json={
            "tenant_id": str(test_tenant.id),
            "outcome": "REVERSED",
            "reason": "audit reason",
        },
    )

    entries = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "redemption",
            AuditLog.entity_id == str(redemption.id),
            AuditLog.action == "recon.resolved.reversed",
        )
    )).scalars().all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor_type == "admin"
    assert entry.note == "audit reason"
    assert entry.before_state["status"] == "MANUAL_REVIEW"
    assert entry.after_state["status"] == REDEMPTION_STATUS_FAILED


@pytest.mark.asyncio
async def test_audit_query_tenant_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Audit endpoint only returns rows for the requested tenant."""
    redemption = await _push_redemption_into_manual_review(
        async_client,
        db_session,
        test_tenant,
        test_user,
        Decimal("20"),
        seed_key="audq",
    )
    await async_client.post(
        f"/api/v1/reconciliation/{redemption.id}/resolve",
        json={
            "tenant_id": str(test_tenant.id),
            "outcome": "COMPLETED",
            "reason": "ok",
        },
    )

    # Query under the other tenant — should see no entries about this redemption.
    response = await async_client.get(
        "/api/v1/reconciliation/audit",
        params={
            "tenant_id": str(other_tenant.id),
            "entity_type": "redemption",
            "entity_id": str(redemption.id),
        },
    )
    assert response.status_code == 200
    assert response.json() == []
