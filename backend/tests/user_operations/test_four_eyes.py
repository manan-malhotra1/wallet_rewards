"""Four-eyes (required_approvals=1): a distinct checker approval APPLIES the op.

Covers the create + update effects, self-approval rejection, checker role gating,
double-apply protection, and the unknown-request 404.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, User, UserIdentifier, UserProfile
from tests.user_operations.conftest import (
    approve,
    create_user_payload,
    propose,
    user_count,
)


@pytest.mark.asyncio
async def test_create_user_applies_on_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """A distinct checker approving a create → APPLIED, user actually created."""
    before = await user_count(db_session, test_tenant)
    payload = create_user_payload()
    proposed = await propose(async_client, test_tenant, maker_header, "create_user", payload)

    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPLIED"
    assert body["approvals_count"] == 1
    assert body["applied_user_id"] is not None

    assert await user_count(db_session, test_tenant) == before + 1
    # The created user carries the proposed email identifier.
    email = payload["identifiers"][1]["identifier_value"]
    ident = (
        await db_session.execute(
            select(UserIdentifier).where(
                UserIdentifier.tenant_id == test_tenant.id,
                UserIdentifier.identifier_type == "email",
                UserIdentifier.identifier_value == email,
            )
        )
    ).scalar_one_or_none()
    assert ident is not None
    assert str(ident.user_id) == body["applied_user_id"]


@pytest.mark.asyncio
async def test_update_user_applies_on_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Approving an update edits the target's status, type, and profile name."""
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "update_user",
        {
            "target_user_id": str(test_user.id),
            "status": "suspended",
            "user_type": "agent",
            "first_name": "Grace",
        },
    )
    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPLIED"
    assert body["applied_user_id"] == str(test_user.id)

    await db_session.refresh(test_user)
    assert test_user.status == "suspended"
    assert test_user.user_type == "agent"
    profile = (
        await db_session.execute(select(UserProfile).where(UserProfile.user_id == test_user.id))
    ).scalar_one()
    assert profile.first_name == "Grace"


@pytest.mark.asyncio
async def test_self_approval_forbidden(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    maker_who_can_approve: dict[str, str],
) -> None:
    """The maker cannot approve their own request even holding user-approver."""
    before = await user_count(db_session, test_tenant)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    resp = await approve(async_client, test_tenant, proposed["id"], maker_who_can_approve)
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "self_approval_forbidden"
    assert await user_count(db_session, test_tenant) == before


@pytest.mark.asyncio
async def test_approve_requires_user_approver_role(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    make_admin_token,
) -> None:
    """A plain platform-admin (no user-approver) approving → 403."""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    token = make_admin_token(roles=["platform-admin"], sub="44444444-4444-4000-8000-000000000004")
    other = {"Authorization": f"Bearer {token}"}
    resp = await approve(async_client, test_tenant, proposed["id"], other)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_second_approve_after_applied_is_409_no_double_create(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
    checker2_header: dict[str, str],
) -> None:
    """Re-approving an APPLIED request → 409, and NO second user is created."""
    before = await user_count(db_session, test_tenant)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    first = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert first.status_code == 200
    assert first.json()["status"] == "APPLIED"

    second = await approve(async_client, test_tenant, proposed["id"], checker2_header)
    assert second.status_code == 409
    assert second.json()["error_code"] == "user_operation_invalid_state"
    assert await user_count(db_session, test_tenant) == before + 1


@pytest.mark.asyncio
async def test_approve_unknown_request_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    checker_header: dict[str, str],
) -> None:
    """Approving a non-existent request → 404."""
    from uuid import uuid4

    resp = await approve(async_client, test_tenant, str(uuid4()), checker_header)
    assert resp.status_code == 404
