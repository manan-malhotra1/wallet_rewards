"""Deployment-mode gating: business_type drives reward behavior."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.events.schemas import RawExternalEvent
from app.modules.events.service import process_external_event
from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    INGESTION_STATUS_REJECTED,
    Account,
    EventIngestionLog,
    ExternalEventSource,
    User,
)
from app.shared.models.tenants import BUSINESS_TYPE_BOTH, Tenant
from app.shared.tenant_mode import business_type_of, rewards_from_wallet_enabled


@pytest.mark.asyncio
async def test_business_type_of_returns_stored_mode(db_session, tenant_factory):
    """Verify a stored deployment mode reads back and 'both' enables wallet-driven rewards."""
    tenant = await tenant_factory(business_type=BUSINESS_TYPE_BOTH)
    assert await business_type_of(db_session, tenant.id) == BUSINESS_TYPE_BOTH
    assert await rewards_from_wallet_enabled(db_session, tenant.id) is True


@pytest.mark.asyncio
async def test_wallet_mode_gate_is_non_raising_for_unknown_tenant(db_session):
    """Verify an unresolved tenant never 500s a money movement — the gate returns False."""
    # On the post_transaction hot path a missing tenant must degrade to
    # "no reward trigger" (False), NOT raise — unlike business_type_of.
    assert await rewards_from_wallet_enabled(db_session, uuid4()) is False


# -----------------------------------------------------------------------------
# External-event mode gate: external Kafka events issue rewards ONLY in `rewards`
# mode. `both`/`wallet` tenants must reject the event (in code, not by process).
# -----------------------------------------------------------------------------


async def _register_source(db_session, tenant: Tenant, source_key: str) -> ExternalEventSource:
    """Persist an active, secret-less external source for the tenant."""
    source = ExternalEventSource(
        tenant_id=tenant.id,
        name=f"src-{source_key}",
        source_key=source_key,
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    return source


async def _make_user(db_session, tenant: Tenant) -> User:
    """Persist a bare user in the tenant to own any issued reward."""
    user = User(tenant_id=tenant.id)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _ensure_points_issuance(db_session, tenant: Tenant) -> None:
    """Ensure the tenant's points-issuance account exists (rewards credit source)."""
    existing = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db_session.add(
            Account(
                tenant_id=tenant.id,
                account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
                currency="PTS",
            )
        )
        await db_session.commit()


def _raw_event(tenant: Tenant, user: User, source_key: str) -> RawExternalEvent:
    """Build a valid RawExternalEvent for the source/tenant/user."""
    return RawExternalEvent(
        event_id=uuid4().hex,
        source_key=source_key,
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="fund",
        amount="500",
        currency="ZAR",
        timestamp=datetime.now(UTC).isoformat(),
    )


@pytest.mark.asyncio
async def test_external_event_accepted_for_rewards_tenant(db_session, tenant_factory):
    """Verify a rewards-mode tenant accepts an external event (not mode-rejected)."""
    tenant = await tenant_factory(business_type="rewards")
    await _ensure_points_issuance(db_session, tenant)
    user = await _make_user(db_session, tenant)
    source = await _register_source(db_session, tenant, "rewards-src")

    result = await process_external_event(
        db_session, _raw_event(tenant, user, source.source_key)
    )

    assert result.outcome in ("processed", "duplicate")


@pytest.mark.asyncio
async def test_external_event_rejected_for_both_tenant(db_session, tenant_factory):
    """Verify a 'both'-mode tenant rejects an external event — rewards come from wallet activity."""
    tenant = await tenant_factory(business_type="both")
    user = await _make_user(db_session, tenant)
    source = await _register_source(db_session, tenant, "both-src")
    raw = _raw_event(tenant, user, source.source_key)

    result = await process_external_event(db_session, raw)

    assert result.outcome == "rejected"
    assert result.rejection_reason == "wrong_mode"
    # Rejection is audit-logged in event_ingestion_log with a REJECTED status.
    log = (
        await db_session.execute(
            select(EventIngestionLog).where(
                EventIngestionLog.external_event_id == raw.event_id
            )
        )
    ).scalar_one_or_none()
    assert log is not None
    assert log.status == INGESTION_STATUS_REJECTED
    assert log.failure_reason == "wrong_mode"


@pytest.mark.asyncio
async def test_external_event_rejected_for_wallet_tenant(db_session, tenant_factory):
    """Verify a 'wallet'-mode tenant rejects an external event — wallet mode has no rewards."""
    tenant = await tenant_factory(business_type="wallet")
    user = await _make_user(db_session, tenant)
    source = await _register_source(db_session, tenant, "wallet-src")

    result = await process_external_event(
        db_session, _raw_event(tenant, user, source.source_key)
    )

    assert result.outcome == "rejected"
    assert result.rejection_reason == "wrong_mode"
