"""User changes: how many approvals are required.

Also asserts the duplicate-approver guard — the same checker cannot supply two
of the required approvals.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, UserOperationRequest
from tests.user_operations.conftest import (
    approve,
    create_user_payload,
    propose,
    user_count,
)


async def _set_required_approvals(session: AsyncSession, op_id: str, n: int) -> None:
    """Bump a proposed request to `n` required approvals (six-eyes has no policy table)."""
    request = (
        await session.execute(
            select(UserOperationRequest).where(UserOperationRequest.id == UUID(op_id))
        )
    ).scalar_one()
    request.required_approvals = n
    await session.commit()


@pytest.mark.asyncio
async def test_six_eyes_needs_two_distinct_checkers(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
    checker2_header: dict[str, str],
) -> None:
    """Verify a user change needing two approvals only applies after two different admins approve"""
    before = await user_count(db_session, test_tenant)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    await _set_required_approvals(db_session, proposed["id"], 2)

    first = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "PENDING"
    assert body["approvals_count"] == 1
    assert await user_count(db_session, test_tenant) == before  # not applied yet

    second = await approve(async_client, test_tenant, proposed["id"], checker2_header)
    assert second.status_code == 200
    assert second.json()["status"] == "APPLIED"
    assert second.json()["approvals_count"] == 2
    assert await user_count(db_session, test_tenant) == before + 1


@pytest.mark.asyncio
async def test_duplicate_approver_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify one admin cannot supply both required approvals for a user change"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    await _set_required_approvals(db_session, proposed["id"], 2)

    first = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert first.status_code == 200
    assert first.json()["status"] == "PENDING"

    dup = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert dup.status_code == 409
    assert dup.json()["error_code"] == "user_operation_duplicate_approver"
