"""Adding an identifier — giving an existing customer a new phone, email, or account number.

Covers adding a post-registration identifier to an existing user: happy path
(account_number / phone / email), duplicate rejection (Pay-PRD-0070), unknown /
cross-tenant user (404), RBAC (401/403), validation (card_number excluded, empty
value), and the audit trail — asserting the raw identifier value is NEVER written
to the audit after_state (NFR-0170 / NFR-0240).
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
    headers: dict[str, str] | None,
    *,
    user_id: str,
    tenant: Tenant,
    identifier_type: str,
    identifier_value: str,
) -> tuple[int, dict]:
    """POST a new identifier onto an existing user; return (status, body)."""
    response = await client.post(
        f"/api/v1/identity/users/{user_id}/identifiers",
        params={"tenant_id": str(tenant.id)},
        headers=headers or {},
        json={
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
        },
    )
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_add_account_number_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can add an account number to an existing customer"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 3000")
    status, body = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-001-887-2210",
    )
    assert status == 201, body
    assert body["identifier_type"] == "account_number"
    assert body["identifier_value"] == "ZA-001-887-2210"
    # An admin-added identifier is NOT verification-proven (Story 27.3).
    assert body["verified"] is False

    # Capture the tenant id BEFORE the rollback expires the ORM object (accessing
    # an expired attribute would trigger a sync lazy-load outside the greenlet).
    tenant_id = test_tenant.id
    # The row is durably present, scoped to the user + tenant.
    await db_session.rollback()  # fresh snapshot so we see committed rows
    row = await db_session.execute(
        select(UserIdentifier).where(
            UserIdentifier.tenant_id == tenant_id,
            UserIdentifier.identifier_type == "account_number",
            UserIdentifier.identifier_value == "ZA-001-887-2210",
        )
    )
    identifier = row.scalar_one()
    assert str(identifier.user_id) == user["id"]
    assert identifier.verified is False


@pytest.mark.asyncio
async def test_add_phone_and_email_normalised(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an added phone number and email are tidied into a standard format"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 3001")

    phone_status, phone_body = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="phone",
        identifier_value="+27 82 555 3099",
    )
    assert phone_status == 201, phone_body
    # Phone is stripped to canonical form on write.
    assert phone_body["identifier_value"] == "+27825553099"
    assert phone_body["verified"] is False

    email_status, email_body = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="email",
        identifier_value="Jane@Example.com",
    )
    assert email_status == 201, email_body
    # Email is lowercased on write.
    assert email_body["identifier_value"] == "jane@example.com"


@pytest.mark.asyncio
async def test_add_duplicate_identifier_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an identifier already used by someone else in the tenant is rejected"""
    owner = await _create_user(
        async_client, admin_auth_header, test_tenant, phone="+27 82 555 3002"
    )
    other = await _create_user(
        async_client, admin_auth_header, test_tenant, phone="+27 82 555 3003"
    )

    # First add succeeds on `owner`.
    first_status, _ = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=owner["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-DUP-000-1",
    )
    assert first_status == 201

    # Re-adding the same (type, value) to a DIFFERENT user collides.
    dup_status, dup_body = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=other["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-DUP-000-1",
    )
    assert dup_status == 409, dup_body
    assert dup_body["error_code"] == "identifier_already_in_use"

    # Capture before the rollback expires the ORM object (avoids a sync lazy-load).
    tenant_id = test_tenant.id
    # The collision must not have created a second row.
    await db_session.rollback()
    count = await db_session.execute(
        select(func.count())
        .select_from(UserIdentifier)
        .where(
            UserIdentifier.tenant_id == tenant_id,
            UserIdentifier.identifier_type == "account_number",
            UserIdentifier.identifier_value == "ZA-DUP-000-1",
        )
    )
    assert count.scalar_one() == 1


@pytest.mark.asyncio
async def test_add_phone_without_plus_collides_with_existing_plus(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding a phone WITHOUT '+' is rejected when the same number exists WITH '+'"""
    # `owner` is created with the '+'-prefixed form (canonicalised at write time).
    await _create_user(async_client, admin_auth_header, test_tenant, phone="+27825550007")
    other = await _create_user(
        async_client, admin_auth_header, test_tenant, phone="+27 82 555 9000"
    )

    # Adding the SAME real number to `other` without the leading '+' must collide,
    # because normalisation collapses '+'/no-'+' to one canonical identifier.
    dup_status, dup_body = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=other["id"],
        tenant=test_tenant,
        identifier_type="phone",
        identifier_value="27825550007",
    )
    assert dup_status == 409, dup_body
    assert dup_body["error_code"] == "identifier_already_in_use"


@pytest.mark.asyncio
async def test_add_identifier_unknown_user(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding an identifier to a customer who does not exist is rejected"""
    status, body = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=str(uuid4()),
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-404-000-1",
    )
    assert status == 404, body
    assert body["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_add_identifier_cross_tenant_user_is_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot add an identifier to a customer in another tenant"""
    user = await _create_user(
        async_client, admin_auth_header, other_tenant, phone="+27 82 555 3004"
    )
    # Ask for that user under test_tenant's scope.
    status, body = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-XT-000-1",
    )
    assert status == 404, body
    assert body["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_add_identifier_forbids_non_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    make_admin_token,
) -> None:
    """Verify only a platform administrator can add an identifier"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 3005")
    non_admin = {"Authorization": f"Bearer {make_admin_token(roles=['viewer'])}"}
    status, _ = await _add_identifier(
        async_client,
        non_admin,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-403-000-1",
    )
    assert status == 403


@pytest.mark.asyncio
async def test_add_identifier_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding an identifier requires signing in"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 3006")
    status, _ = await _add_identifier(
        async_client,
        None,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="ZA-401-000-1",
    )
    assert status == 401


@pytest.mark.asyncio
async def test_add_identifier_rejects_card_number(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a raw card number cannot be added as an identifier"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 3007")
    status, _ = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="card_number",
        identifier_value="5234567890123456",
    )
    assert status == 422


@pytest.mark.asyncio
async def test_add_identifier_rejects_empty_value(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an empty identifier is rejected"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 3008")
    status, _ = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value="",
    )
    assert status == 422


@pytest.mark.asyncio
async def test_add_identifier_writes_audit_without_raw_value(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding an identifier is audited without recording the sensitive value"""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 3009")
    secret_value = "ZA-AUDIT-887-9"
    status, _ = await _add_identifier(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        identifier_type="account_number",
        identifier_value=secret_value,
    )
    assert status == 201

    await db_session.rollback()  # fresh snapshot so we see committed rows
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == user["id"],
            AuditLog.action == "user.identifier_added",
        )
    )
    audit_rows = result.scalars().all()
    assert len(audit_rows) == 1
    audit = audit_rows[0]
    assert audit.after_state["identifier_type"] == "account_number"
    assert audit.after_state["verified"] is False
    # The raw identifier value must never appear anywhere in the audit row.
    assert secret_value not in json.dumps(audit.after_state)
    assert secret_value not in (audit.after_state or {}).values()
