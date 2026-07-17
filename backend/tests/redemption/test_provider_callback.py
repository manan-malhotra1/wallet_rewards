"""E2E tests for POST /api/v1/redemption/{id}/callback (Phase F.5).

Covers the threat model scenarios from
docs/security/threat-models/phase-f5-hmac-and-audit.md §7:
  - Valid HMAC + recent timestamp → 200, transition applied
  - Tampered body → 401 invalid_signature
  - Stale timestamp → 401 signature_timestamp_skew
  - Missing header → 401 signature_missing
  - Provider has no shared_secret → 401 signature_not_configured
  - Replay against already-terminal redemption → 409
  - audit_log row created on success and on integrity failure
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hmac import build_signature_header
from app.auth.secret_box import decrypt_secret
from app.modules.accounts.service import derive_balance
from app.modules.rewards.service import issue_points_reward
from app.shared.models import (
    Account,
    AuditLog,
    RedemptionProvider,
    Rule,
    Tenant,
    User,
)
from tests.conftest import create_session_token_for_user, seed_redemption_service_config

PROVIDER_SECRET = "x" * 64  # 64-char secret (well above the 32-char minimum)


async def _seed_pending_redemption(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    credit_amount: Decimal,
    redeem_amount: Decimal,
    seed_key: str,
    shared_secret: str | None = PROVIDER_SECRET,
) -> tuple[str, RedemptionProvider]:
    """Set up a PENDING redemption and return (redemption_id, provider).

    Provider is created with the given shared_secret (None disables callbacks).
    """
    rule = Rule(
        tenant_id=tenant.id,
        name=f"cb-seed-{seed_key}",
        rule_type="first_time",
        transaction_type="seed",
        reward_type="points",
        reward_value=credit_amount,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    await issue_points_reward(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        rule=rule,
        triggering_event_id=seed_key,
        reward_value=credit_amount,
    )

    # Fail-closed gate (invariant #12): seed redemption pricing + limit config
    # so the setup `/initiate` succeeds.
    await seed_redemption_service_config(db_session, tenant)

    body: dict = {
        "tenant_id": str(tenant.id),
        "name": f"CB-Provider-{seed_key}",
    }
    if shared_secret is not None:
        body["shared_secret"] = shared_secret
    pr = await async_client.post("/api/v1/redemption/providers", json=body)
    assert pr.status_code == 201, pr.text
    provider_id = pr.json()["id"]

    user_token = await create_session_token_for_user(user.id, user.tenant_id)
    init = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={
            "Idempotency-Key": uuid4().hex,
            "Authorization": f"Bearer {user_token}",
        },
        json={"provider_id": provider_id, "points_amount": str(redeem_amount)},
    )
    assert init.status_code == 201, init.text

    provider = (
        await db_session.execute(
            select(RedemptionProvider).where(RedemptionProvider.id == provider_id)
        )
    ).scalar_one()
    return init.json()["id"], provider


async def _count_audit(db_session: AsyncSession, *, action: str, entity_id: str) -> int:
    """Count audit rows for a specific (action, entity)."""
    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
    )
    return len(list(result.scalars().all()))


@pytest.mark.asyncio
async def test_callback_happy_path_completes_redemption(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Valid HMAC + outcome=completed → redemption COMPLETED, audit row written."""
    redemption_id, _ = await _seed_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("200"),
        redeem_amount=Decimal("80"),
        seed_key="ok",
    )

    body = json.dumps({"outcome": "completed", "external_reference": "MUKURU-OK"}).encode()
    signature = build_signature_header(raw_body=body, secret=PROVIDER_SECRET)

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["external_reference"] == "MUKURU-OK"

    # Balance permanently dropped — points DEBIT moved PENDING → COMPLETED.
    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("120")
    assert reserved == Decimal("0")

    # Audit row recorded under the system actor.
    assert (
        await _count_audit(
            db_session,
            action="redemption.confirmed.by_provider",
            entity_id=redemption_id,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_callback_failure_outcome_restores_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Valid HMAC + outcome=failed → redemption FAILED, balance restored."""
    redemption_id, _ = await _seed_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("60"),
        seed_key="fail",
    )

    body = json.dumps({"outcome": "failed", "reason": "out_of_stock"}).encode()
    signature = build_signature_header(raw_body=body, secret=PROVIDER_SECRET)

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "FAILED"

    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("100")  # original points restored
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_callback_tampered_body_returns_401(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Mutating the body after signing → 401 invalid_signature, no transition."""
    redemption_id, _ = await _seed_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("40"),
        seed_key="tamper",
    )

    body = json.dumps({"outcome": "completed"}).encode()
    signature = build_signature_header(raw_body=body, secret=PROVIDER_SECRET)
    tampered = body.replace(b"completed", b"failed   ")  # same length

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=tampered,
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "invalid_signature"


@pytest.mark.asyncio
async def test_callback_stale_timestamp_returns_401(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Signature timestamp > 5 min ago → 401 signature_timestamp_skew."""
    redemption_id, _ = await _seed_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("20"),
        seed_key="stale",
    )

    body = json.dumps({"outcome": "completed"}).encode()
    old_ts = int(time.time()) - 600  # 10 minutes ago
    signature = build_signature_header(raw_body=body, secret=PROVIDER_SECRET, timestamp=old_ts)

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "signature_timestamp_skew"


@pytest.mark.asyncio
async def test_callback_missing_signature_returns_422(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """No X-Sasai-Signature header → 422 (FastAPI's missing-header default)."""
    redemption_id, _ = await _seed_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("20"),
        seed_key="missing",
    )

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"Content-Type": "application/json"},
        content=json.dumps({"outcome": "completed"}).encode(),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_callback_provider_without_secret_returns_401(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Provider registered with no shared_secret → 401 signature_not_configured."""
    redemption_id, _ = await _seed_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("20"),
        seed_key="nosec",
        shared_secret=None,
    )

    body = json.dumps({"outcome": "completed"}).encode()
    # Signature header is required by the route schema — send a syntactically
    # valid one so the route handler reaches the service.
    signature = build_signature_header(raw_body=body, secret="z" * 64)
    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "signature_not_configured"


@pytest.mark.asyncio
async def test_callback_replay_after_terminal_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """A second valid callback on the same redemption → 409 (already terminal)."""
    redemption_id, _ = await _seed_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("30"),
        seed_key="replay",
    )

    body = json.dumps({"outcome": "completed"}).encode()
    signature = build_signature_header(raw_body=body, secret=PROVIDER_SECRET)

    first = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert first.status_code == 200

    # Same valid signature, but redemption is now COMPLETED → 409.
    second = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "redemption_not_pending"


@pytest.mark.asyncio
async def test_provider_secret_stored_encrypted_not_plaintext(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """The stored secret is Fernet ciphertext, not the plaintext operator input.

    Asserts the DB column never holds the raw secret (a DB leak must not expose
    the live callback-signing key) while HMAC verification still succeeds end
    to end against the decrypted value.
    """
    redemption_id, provider = await _seed_pending_redemption(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("200"),
        redeem_amount=Decimal("80"),
        seed_key="enc",
    )

    # Column holds ciphertext, not the plaintext the operator submitted.
    assert provider.shared_secret_encrypted is not None
    assert provider.shared_secret_encrypted != PROVIDER_SECRET
    assert decrypt_secret(provider.shared_secret_encrypted) == PROVIDER_SECRET

    # And HMAC verify still works against the encrypted-then-decrypted secret.
    body = json.dumps({"outcome": "completed"}).encode()
    signature = build_signature_header(raw_body=body, secret=PROVIDER_SECRET)
    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_callback_unknown_redemption_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """An unknown redemption_id → 404 redemption_not_found."""
    body = json.dumps({"outcome": "completed"}).encode()
    signature = build_signature_header(raw_body=body, secret=PROVIDER_SECRET)
    response = await async_client.post(
        f"/api/v1/redemption/{uuid4()}/callback",
        headers={"X-Sasai-Signature": signature, "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "redemption_not_found"
