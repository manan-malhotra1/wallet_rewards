"""Tests for the reconciliation sweep + listing endpoints (Phase E.1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rewards.service import issue_points_reward
from app.shared.models import (
    REDEMPTION_STATUS_COMPLETED,
    REDEMPTION_STATUS_MANUAL_REVIEW,
    REDEMPTION_STATUS_PENDING,
    Account,
    AuditLog,
    Redemption,
    RedemptionProvider,
    Rule,
    Tenant,
    User,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _grant_points(
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    amount: Decimal,
    *,
    key: str,
) -> None:
    """Issue `amount` points to `user` via a throwaway first_time rule."""
    rule = Rule(
        tenant_id=tenant.id,
        name=f"seed-{key}",
        rule_type="first_time",
        transaction_type="seed",
        reward_type="points",
        reward_value=amount,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    await issue_points_reward(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        rule=rule,
        triggering_event_id=key,
        reward_value=amount,
    )


async def _make_pending_redemption(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    amount: Decimal,
    age_minutes: int,
    max_retries: int = 3,
    seed_key: str,
) -> Redemption:
    """Initiate a redemption via API, then backdate it for sweep eligibility.

    Reaches into the DB to set provider.max_retries + redemption.created_at —
    test-only since these aren't exposed via the API.
    """
    await _grant_points(
        db_session, tenant, user, amount + Decimal("10"), key=seed_key
    )

    provider_resp = await async_client.post(
        "/api/v1/redemption/providers",
        json={
            "tenant_id": str(tenant.id),
            "name": f"P-{seed_key}",
            "max_retries": max_retries,
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

    # Backdate created_at so the sweep sees it as stale.
    redemption = (await db_session.execute(
        select(Redemption).where(Redemption.id == redemption_id)
    )).scalar_one()
    redemption.created_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    await db_session.commit()
    await db_session.refresh(redemption)
    return redemption


# -----------------------------------------------------------------------------
# Sweep tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_bumps_retry_for_stale_pending(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """A PENDING redemption older than threshold gets retry_count incremented."""
    redemption = await _make_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        amount=Decimal("20"),
        age_minutes=10,
        max_retries=5,
        seed_key="bump1",
    )
    assert redemption.retry_count == 0

    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scanned_count"] == 1
    assert body["bumped_count"] == 1
    assert body["escalated_count"] == 0
    assert body["audit_entry_count"] == 1

    await db_session.refresh(redemption)
    assert redemption.retry_count == 1
    assert redemption.status == REDEMPTION_STATUS_PENDING


@pytest.mark.asyncio
async def test_sweep_ignores_recent_pending(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """A PENDING redemption inside the threshold window is NOT swept."""
    redemption = await _make_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        amount=Decimal("20"),
        age_minutes=1,  # under the 5-min threshold
        seed_key="recent",
    )

    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    body = response.json()
    assert body["scanned_count"] == 0
    assert body["bumped_count"] == 0

    await db_session.refresh(redemption)
    assert redemption.retry_count == 0


@pytest.mark.asyncio
async def test_sweep_ignores_completed(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Only PENDING redemptions are candidates — COMPLETED ones are skipped."""
    redemption = await _make_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        amount=Decimal("20"),
        age_minutes=10,
        seed_key="comp",
    )

    # Confirm it now so it's COMPLETED before the sweep.
    await async_client.post(
        f"/api/v1/redemption/{redemption.id}/confirm",
        json={"tenant_id": str(test_tenant.id)},
    )

    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    body = response.json()
    assert body["scanned_count"] == 0

    await db_session.refresh(redemption)
    assert redemption.status == REDEMPTION_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_sweep_escalates_after_max_retries(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """When retry_count reaches provider.max_retries, status -> MANUAL_REVIEW."""
    redemption = await _make_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        amount=Decimal("15"),
        age_minutes=10,
        max_retries=2,
        seed_key="esc",
    )

    # First sweep: retry_count 0 -> 1, still PENDING.
    await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    await db_session.refresh(redemption)
    assert redemption.retry_count == 1
    assert redemption.status == REDEMPTION_STATUS_PENDING

    # Second sweep: retry_count 1 -> 2, hits max_retries=2, escalates.
    second = await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )
    body = second.json()
    assert body["bumped_count"] == 0
    assert body["escalated_count"] == 1

    await db_session.refresh(redemption)
    assert redemption.retry_count == 2
    assert redemption.status == REDEMPTION_STATUS_MANUAL_REVIEW


@pytest.mark.asyncio
async def test_sweep_writes_audit_log_per_item(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Every sweep action produces exactly one audit_log row."""
    redemption = await _make_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        amount=Decimal("25"),
        age_minutes=10,
        max_retries=5,
        seed_key="audit",
    )

    await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(test_tenant.id), "threshold_minutes": 5},
    )

    entries = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "redemption",
            AuditLog.entity_id == str(redemption.id),
        )
    )).scalars().all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor_type == "system"
    assert entry.action == "recon.swept"
    assert entry.before_state["retry_count"] == 0
    assert entry.after_state["retry_count"] == 1


@pytest.mark.asyncio
async def test_pending_list_tenant_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """The pending list under another tenant returns []."""
    await _make_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        amount=Decimal("20"),
        age_minutes=10,
        seed_key="ts",
    )

    response = await async_client.get(
        "/api/v1/reconciliation/pending",
        params={"tenant_id": str(other_tenant.id), "threshold_minutes": 5},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_sweep_rejects_unknown_tenant(async_client: AsyncClient) -> None:
    """Sweep against an unknown tenant_id returns 404."""
    response = await async_client.post(
        "/api/v1/reconciliation/sweep",
        json={"tenant_id": str(uuid4()), "threshold_minutes": 5},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "tenant_not_found"
