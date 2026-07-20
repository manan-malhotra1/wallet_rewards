"""Tests for read-side name enrichment on the audit-log endpoint.

The stored `audit_log` rows keep stable IDs (actor_id / entity_id). The read
API additionally resolves those IDs to human display names (`actor_name`,
`entity_name`) for the page returned, batching resolutions so there is no
N+1 (Enrichment is READ-SIDE only — stored rows are never mutated).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACTOR_ADMIN,
    ACTOR_SYSTEM,
    ACTOR_USER,
    AdminProfile,
    AuditLog,
    Tenant,
    User,
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _add_audit_row(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    actor_id: str,
    actor_type: str,
    entity_type: str,
    entity_id: str,
    action: str = "test.action",
) -> AuditLog:
    """Insert one immutable audit_log row for the tenant and return it."""
    row = AuditLog(
        tenant_id=tenant.id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=None,
        after_state=None,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _get_audit(
    async_client: AsyncClient, tenant: Tenant, **params: object
) -> list[dict[str, object]]:
    """GET the audit list for a tenant, asserting 200, returning the rows."""
    response = await async_client.get(
        "/api/v1/reconciliation/audit",
        params={"tenant_id": str(tenant.id), **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


# -----------------------------------------------------------------------------
# actor_name
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_actor_row_carries_admin_display_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """An admin-actor row resolves actor_name via the admin profile."""
    sub = "11111111-1111-4000-8000-0000000000aa"
    db_session.add(
        AdminProfile(
            keycloak_sub=sub,
            username="op.jane",
            display_name="Jane Operator",
            email="jane@example.com",
        )
    )
    await db_session.commit()

    row = await _add_audit_row(
        db_session,
        test_tenant,
        actor_id=sub,
        actor_type=ACTOR_ADMIN,
        entity_type="redemption",
        entity_id=str(uuid4()),
    )

    rows = await _get_audit(async_client, test_tenant, entity_id=row.entity_id)
    assert rows[0]["actor_name"] == "Jane Operator"


@pytest.mark.asyncio
async def test_user_actor_row_carries_user_display_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """A user-actor row resolves actor_name via the user resolver.

    `test_user` has a phone identifier but no profile, so the resolved name is
    the identifier value.
    """
    row = await _add_audit_row(
        db_session,
        test_tenant,
        actor_id=str(test_user.id),
        actor_type=ACTOR_USER,
        entity_type="redemption",
        entity_id=str(uuid4()),
    )

    rows = await _get_audit(async_client, test_tenant, entity_id=row.entity_id)
    assert rows[0]["actor_name"] == test_user.identifiers[0].identifier_value


@pytest.mark.asyncio
async def test_system_actor_row_gets_friendly_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """A system-actor row gets a friendly constant and never crashes."""
    row = await _add_audit_row(
        db_session,
        test_tenant,
        actor_id=ACTOR_SYSTEM,
        actor_type=ACTOR_SYSTEM,
        entity_type="redemption",
        entity_id=str(uuid4()),
    )

    rows = await _get_audit(async_client, test_tenant, entity_id=row.entity_id)
    assert rows[0]["actor_name"] == "System"


@pytest.mark.asyncio
async def test_apikey_system_actor_row_gets_api_key_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """An `apikey:`-prefixed system actor resolves to the 'API key' label."""
    row = await _add_audit_row(
        db_session,
        test_tenant,
        actor_id="apikey:ingest-svc",
        actor_type=ACTOR_SYSTEM,
        entity_type="redemption",
        entity_id=str(uuid4()),
    )

    rows = await _get_audit(async_client, test_tenant, entity_id=row.entity_id)
    assert rows[0]["actor_name"] == "API key"


@pytest.mark.asyncio
async def test_unknown_admin_actor_name_is_none(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """An admin actor with no recorded profile resolves to None (UI fallback)."""
    row = await _add_audit_row(
        db_session,
        test_tenant,
        actor_id="22222222-2222-4000-8000-0000000000bb",
        actor_type=ACTOR_ADMIN,
        entity_type="redemption",
        entity_id=str(uuid4()),
    )

    rows = await _get_audit(async_client, test_tenant, entity_id=row.entity_id)
    assert rows[0]["actor_name"] is None


# -----------------------------------------------------------------------------
# entity_name
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_entity_row_carries_affected_user_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """When entity_type == 'user', entity_name is the affected user's name."""
    row = await _add_audit_row(
        db_session,
        test_tenant,
        actor_id=ACTOR_SYSTEM,
        actor_type=ACTOR_SYSTEM,
        entity_type="user",
        entity_id=str(test_user.id),
    )

    rows = await _get_audit(async_client, test_tenant, entity_id=row.entity_id)
    assert rows[0]["entity_name"] == test_user.identifiers[0].identifier_value


@pytest.mark.asyncio
async def test_non_user_entity_with_non_uuid_id_does_not_crash(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """A non-user entity with a non-UUID id yields entity_name=None, no crash."""
    row = await _add_audit_row(
        db_session,
        test_tenant,
        actor_id=ACTOR_SYSTEM,
        actor_type=ACTOR_SYSTEM,
        entity_type="config",
        entity_id="not-a-uuid",
    )

    rows = await _get_audit(async_client, test_tenant, entity_id=row.entity_id)
    assert rows[0]["entity_name"] is None
    assert rows[0]["entity_id"] == "not-a-uuid"


@pytest.mark.asyncio
async def test_enrichment_is_tenant_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
) -> None:
    """A user-entity row does not resolve a name across a tenant boundary.

    `test_user` belongs to `test_tenant`; querying the audit log under
    `other_tenant` never surfaces that user's row, so enrichment can't leak
    the name. This asserts the existing tenant-scoping still holds.
    """
    await _add_audit_row(
        db_session,
        test_tenant,
        actor_id=ACTOR_SYSTEM,
        actor_type=ACTOR_SYSTEM,
        entity_type="user",
        entity_id=str(test_user.id),
    )

    rows = await _get_audit(async_client, other_tenant)
    assert rows == []
