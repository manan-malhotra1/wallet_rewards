"""Tests for the dev-simulator event routes.

`/sim-ingest` is the HTTP path the mobile-simulator uses to fire events
synchronously. It mirrors `/external` but skips admin auth — HMAC over
the body is the only proof of origin. The route 404s outside dev mode.

`/sim-kafka-produce` is the Kafka path. Produces one message to
`wallet.events.external` for the existing consumer to pick up. Also
dev-gated.

Covers:
  - /sim-ingest 404 when SIMULATOR_DEV_MODE is off
  - /sim-ingest happy path: valid HMAC → 200 + processed
  - /sim-ingest 422-ish on bad signature (process_external_event rejects)
  - /sim-kafka-produce 404 when SIMULATOR_DEV_MODE is off
  - /sim-kafka-produce 422 when user_id is missing
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hmac import build_signature_header
from app.config import settings
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    ExternalEventSource,
    Tenant,
    User,
)


async def _seed_source_with_secret(
    db_session: AsyncSession, tenant: Tenant, *, secret: str = "shh-test-secret"
) -> str:
    """Insert an ExternalEventSource with `shared_secret` set. Returns source_key.

    The HMAC enforcement on `process_external_event` only triggers when
    `shared_secret IS NOT NULL`; the sim-ingest route refuses unsigned
    requests by design.
    """
    source_key = f"sim-src-{uuid4().hex[:8]}"
    db_session.add(
        ExternalEventSource(
            tenant_id=tenant.id,
            name="sim-source",
            source_key=source_key,
            shared_secret=secret,
        )
    )
    await db_session.commit()
    return source_key


async def _seed_first_time_rule(
    async_client: AsyncClient, tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """Create a first_time fund rule so the event has something to fire on."""
    resp = await async_client.post(
        "/api/v1/rules",
        headers=admin_auth_header,
        json={
            "tenant_id": str(tenant.id),
            "name": "sim-fund-bonus",
            "rule_type": "first_time",
            "transaction_type": "fund",
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert resp.status_code == 201, resp.text


def _event_body(tenant: Tenant, user: User, source_key: str) -> bytes:
    """Build a canonical RawExternalEvent body for the simulator HTTP path."""
    return json.dumps(
        {
            "event_id": str(uuid4()),
            "tenant_id": str(tenant.id),
            "user_id": str(user.id),
            "source_key": source_key,
            "transaction_type": "fund",
            "amount": "500",
            "currency": "ZAR",
            "timestamp": datetime.now(UTC).isoformat(),
            "raw": {},
        }
    ).encode("utf-8")


# -----------------------------------------------------------------------------
# /sim-ingest
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sim_ingest_404_when_flag_off(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SIMULATOR_DEV_MODE off → route reports 404 regardless of body."""
    monkeypatch.setattr(settings, "SIMULATOR_DEV_MODE", False)
    response = await async_client.post(
        "/api/v1/events/sim-ingest",
        content=b"{}",
        headers={"X-Sasai-Signature": "t=1,v1=deadbeef"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_sim_ingest_happy_path_with_valid_hmac(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid HMAC signature over the body → 200 + outcome='processed'."""
    monkeypatch.setattr(settings, "SIMULATOR_DEV_MODE", True)
    secret = "test-secret-abc"
    source_key = await _seed_source_with_secret(db_session, test_tenant, secret=secret)
    await _seed_first_time_rule(async_client, test_tenant, admin_auth_header)

    # The rules engine needs a points account on the recipient + a
    # system issuance account on the tenant to land the reward credit.
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_POINTS,
            currency="PTS",
        )
    )
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=None,
            account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            currency="PTS",
        )
    )
    await db_session.commit()

    body = _event_body(test_tenant, test_user, source_key)
    signature = build_signature_header(raw_body=body, secret=secret)

    response = await async_client.post(
        "/api/v1/events/sim-ingest",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Sasai-Signature": signature,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "processed"


@pytest.mark.asyncio
async def test_sim_ingest_rejects_bad_signature(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garbage signature → process_external_event rejects with outcome=rejected."""
    monkeypatch.setattr(settings, "SIMULATOR_DEV_MODE", True)
    source_key = await _seed_source_with_secret(db_session, test_tenant)
    body = _event_body(test_tenant, test_user, source_key)

    response = await async_client.post(
        "/api/v1/events/sim-ingest",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Sasai-Signature": "t=1,v1=0123456789abcdef",
        },
    )
    # process_external_event returns IngestResponse{outcome: rejected} on
    # bad HMAC — not a HTTP error. Confirm the outcome in the body.
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "rejected"


# -----------------------------------------------------------------------------
# /sim-kafka-produce
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sim_kafka_produce_404_when_flag_off(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SIMULATOR_DEV_MODE off → 404."""
    monkeypatch.setattr(settings, "SIMULATOR_DEV_MODE", False)
    response = await async_client.post(
        "/api/v1/events/sim-kafka-produce",
        json={"user_id": str(uuid4()), "transaction_type": "fund"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_sim_kafka_produce_422_when_user_id_missing(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """user_id is the partition key — missing it must reject (422)."""
    monkeypatch.setattr(settings, "SIMULATOR_DEV_MODE", True)
    response = await async_client.post(
        "/api/v1/events/sim-kafka-produce",
        json={"transaction_type": "fund", "amount": "500"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "missing_user_id"


# NOTE: The full kafka-produce happy path is not unit-tested here — it
# would require a running Kafka broker or extensive mocking of confluent
# kafka's C bindings. The route delegates straight to confluent_kafka's
# Producer, which is exercised by the existing publish_event.py manual
# script. Adding a Kafka happy-path test belongs in an integration suite
# that's gated by a `KAFKA_AVAILABLE=true` env flag.
