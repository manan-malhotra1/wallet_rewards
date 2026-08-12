"""Proposing a user change holds it until approved.

Also covers propose-time validation (invalid payload, unknown operation, missing
email/phone), role gating, and the update_user target-existence check.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, User, UserProfile
from tests.user_operations.conftest import (
    create_user_payload,
    ops_url,
    propose,
    user_count,
)


@pytest.mark.asyncio
async def test_propose_create_user_is_pending_and_creates_nothing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify proposing to create a user creates no user until approved"""
    before = await user_count(db_session, test_tenant)
    body = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    assert body["status"] == "PENDING"
    assert body["operation"] == "create_user"
    assert body["applied_user_id"] is None
    assert body["approvals_count"] == 0
    assert body["required_approvals"] == 1
    # The submitted review is present (maker).
    assert [r["action"] for r in body["reviews"]] == ["submitted"]
    assert await user_count(db_session, test_tenant) == before


@pytest.mark.asyncio
async def test_propose_update_user_is_pending_and_changes_nothing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
) -> None:
    """Verify proposing to edit a user leaves the user unchanged until approved"""
    body = await propose(
        async_client,
        test_tenant,
        maker_header,
        "update_user",
        {"target_user_id": str(test_user.id), "status": "suspended", "first_name": "Grace"},
    )
    assert body["status"] == "PENDING"
    assert body["applied_user_id"] is None

    await db_session.refresh(test_user)
    assert test_user.status == "active"  # unchanged
    profile = (
        await db_session.execute(select(UserProfile).where(UserProfile.user_id == test_user.id))
    ).scalar_one_or_none()
    assert profile is None  # no profile written on propose


@pytest.mark.asyncio
async def test_propose_update_unknown_target_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify proposing an edit to a user who does not exist is reported as not found"""
    from uuid import uuid4

    resp = await async_client.post(
        ops_url(test_tenant),
        content=json.dumps(
            {
                "operation": "update_user",
                "payload": {"target_user_id": str(uuid4()), "status": "suspended"},
            }
        ),
        headers=maker_header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_propose_create_without_email_or_phone_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a new user must have at least an email or phone number"""
    resp = await async_client.post(
        ops_url(test_tenant),
        content=json.dumps(
            {
                "operation": "create_user",
                "payload": {
                    "identifiers": [
                        {"identifier_type": "account_number", "identifier_value": "ZA-1"}
                    ]
                },
            }
        ),
        headers=maker_header,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_propose_unknown_operation_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify an unrecognised user change type is rejected"""
    resp = await async_client.post(
        ops_url(test_tenant),
        content=json.dumps({"operation": "delete_user", "payload": {}}),
        headers=maker_header,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_propose_requires_platform_admin_role(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token,
) -> None:
    """Verify only a platform admin can propose a user change"""
    token = make_admin_token(roles=["user-approver"], sub="99999999-9999-4000-8000-000000000009")
    resp = await async_client.post(
        ops_url(test_tenant),
        content=json.dumps({"operation": "create_user", "payload": create_user_payload()}),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403
