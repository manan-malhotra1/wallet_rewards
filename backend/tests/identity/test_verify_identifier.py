"""Verifying an identifier — an admin marking a customer's account number as confirmed.

Covers the manual admin verification of an `account_number` identifier: happy
path (unverified → verified, one audit row, no raw value in it), type guard
(phone/email rejected with 422 identifier_not_manually_verifiable, unchanged),
already-verified idempotency (200, still verified, NO second audit row), unknown /
wrong-user / cross-tenant identifier (404), and RBAC (401/403).
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Tenant, UserIdentifier


async def _create_user(
    client: AsyncClient,
    headers: dict[str, str],
    tenant: Tenant,
    *,
    phone: str,
) -> dict:
    """Create a user via the API and return the response body."""
    response = await client.post(
        "/api/v1/identity/users",
        headers=headers,
        json={
            "tenant_id": str(tenant.id),
            "identifiers": [{"identifier_type": "phone", "identifier_value": phone}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_identifier(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    user_id: str,
    tenant: Tenant,
    identifier_type: str,
    identifier_value: str,
) -> dict:
    """POST a new identifier onto an existing user; return the response body."""
    response = await client.post(
        f"/api/v1/identity/users/{user_id}/identifiers",
        params={"tenant_id": str(tenant.id)},
        headers=headers,
        json={"identifier_type": identifier_type, "identifier_value": identifier_value},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _verify_identifier(
    client: AsyncClient,
    headers: dict[str, str] | None,
    *,
    user_id: str,
    identifier_id: str,
    tenant: Tenant,
) -> tuple[int, dict]:
    """POST the verify action; return (status, body)."""
    response = await client.post(
        f"/api/v1/identity/users/{user_id}/identifiers/{identifier_id}/verify",
        params={"tenant_id": str(tenant.id)},
        headers=headers or {},
    )
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_verify_account_number_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can mark a customer's account number as verified"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 4000")
    identifier = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-VER-887-0",
    )
    assert identifier["verified"] is False

    status, body = await _verify_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        identifier_id=identifier["id"],
        tenant=test_tenant,
    )
    assert status == 200, body
    assert body["id"] == identifier["id"]
    assert body["verified"] is True

    tenant_id = test_tenant.id
    await db_session.rollback()  # fresh snapshot so we see committed rows
    row = await db_session.execute(
        select(UserIdentifier).where(UserIdentifier.id == identifier["id"])
    )
    assert row.scalar_one().verified is True

    # Exactly one `admin.identifier_verified` audit row, and it never carries the
    # raw account-number value (NFR-0170) — only the type + before/after verified.
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_id == user["id"],
                    AuditLog.action == "admin.identifier_verified",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    audit = audit_rows[0]
    assert audit.tenant_id == tenant_id
    assert audit.after_state["identifier_type"] == "account_number"
    assert audit.before_state["verified"] is False
    assert audit.after_state["verified"] is True
    assert "ZA-VER-887-0" not in json.dumps(audit.after_state)
    assert "ZA-VER-887-0" not in json.dumps(audit.before_state)


@pytest.mark.asyncio
async def test_verify_rejects_phone_identifier(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a phone number cannot be manually marked as verified through this action"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 4001")
    # The phone identifier created with the user (verified=False) is the target.
    phone_id = user["identifiers"][0]["id"]
    assert user["identifiers"][0]["identifier_type"] == "phone"

    status, body = await _verify_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        identifier_id=phone_id,
        tenant=test_tenant,
    )
    assert status == 422, body
    assert body["error_code"] == "identifier_not_manually_verifiable"

    await db_session.rollback()
    row = await db_session.execute(select(UserIdentifier).where(UserIdentifier.id == phone_id))
    assert row.scalar_one().verified is False


@pytest.mark.asyncio
async def test_verify_already_verified_is_idempotent(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify re-verifying an already-verified identifier makes no further change"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 4002")
    identifier = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-IDEM-887-2",
    )

    first_status, _ = await _verify_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        identifier_id=identifier["id"],
        tenant=test_tenant,
    )
    assert first_status == 200
    second_status, second_body = await _verify_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        identifier_id=identifier["id"],
        tenant=test_tenant,
    )
    assert second_status == 200, second_body
    assert second_body["verified"] is True

    await db_session.rollback()
    # Idempotent no-op: only ONE audit row despite two verify calls.
    count = await db_session.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.entity_id == user["id"],
            AuditLog.action == "admin.identifier_verified",
        )
    )
    assert count.scalar_one() == 1


@pytest.mark.asyncio
async def test_verify_unknown_identifier_is_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify verifying an identifier that does not exist is rejected"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 4003")
    status, body = await _verify_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        identifier_id=str(uuid4()),
        tenant=test_tenant,
    )
    assert status == 404, body
    assert body["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_verify_identifier_of_wrong_user_is_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an identifier cannot be verified against the wrong customer"""
    owner = await _create_user(
        async_client, admin_auth_header, test_tenant, phone="+27 82 555 4004"
    )
    other = await _create_user(
        async_client, admin_auth_header, test_tenant, phone="+27 82 555 4005"
    )
    identifier = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=owner["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-WRONG-887-4",
    )
    # Ask to verify owner's identifier while naming `other` as the user.
    status, body = await _verify_identifier(
        async_client,
        admin_auth_header,
        user_id=other["id"],
        identifier_id=identifier["id"],
        tenant=test_tenant,
    )
    assert status == 404, body
    assert body["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_verify_cross_tenant_identifier_is_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot verify an identifier in another tenant"""
    user = await _create_user(
        async_client, admin_auth_header, other_tenant, phone="+27 82 555 4006"
    )
    identifier = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=other_tenant,
        identifier_type="account_number",
        identifier_value="ZA-XT-887-6",
    )
    # Try to verify it under test_tenant's scope.
    status, body = await _verify_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        identifier_id=identifier["id"],
        tenant=test_tenant,
    )
    assert status == 404, body
    assert body["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_verify_identifier_forbids_non_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    make_admin_token,
) -> None:
    """Verify only a platform administrator can verify an identifier"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 4007")
    identifier = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-403-887-7",
    )
    non_admin = {"Authorization": f"Bearer {make_admin_token(roles=['viewer'])}"}
    status, _ = await _verify_identifier(
        async_client,
        non_admin,
        user_id=user["id"],
        identifier_id=identifier["id"],
        tenant=test_tenant,
    )
    assert status == 403


@pytest.mark.asyncio
async def test_verify_identifier_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify verifying an identifier requires signing in"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 4008")
    identifier = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-401-887-8",
    )
    status, _ = await _verify_identifier(
        async_client,
        None,
        user_id=user["id"],
        identifier_id=identifier["id"],
        tenant=test_tenant,
    )
    assert status == 401
