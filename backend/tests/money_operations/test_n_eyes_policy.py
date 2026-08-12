"""Treasury moves: how many approvals the policy requires.

With an ApprovalPolicy requiring 2 approvals: the first approval leaves the
request PENDING (1 of 2); a second DISTINCT approval executes; the SAME approver
twice is a duplicate 409; and the maker approving is a self-approval 409.
Resolution order: op-specific policy > tenant-wide default > code default of 1.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import ApprovalPolicy, Tenant
from tests.money_operations.conftest import (
    approve,
    propose,
    txn_count,
)


async def _seed_policy(
    session: AsyncSession, tenant: Tenant, *, operation: str | None, required: int
) -> None:
    """Insert an ApprovalPolicy row for the tenant."""
    session.add(
        ApprovalPolicy(tenant_id=tenant.id, operation=operation, required_approvals=required)
    )
    await session.commit()


def _mirror_payload(name: str) -> dict:
    return {"currency": "ZAR", "name": name}


@pytest.mark.asyncio
async def test_six_eyes_needs_two_distinct_approvals(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
    checker2_header: dict[str, str],
) -> None:
    """Verify a move requiring two approvals only happens after two different admins approve"""
    await _seed_policy(db_session, test_tenant, operation=None, required=2)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror_payload("Six")
    )
    assert proposed["required_approvals"] == 2

    first = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "PENDING"
    assert first.json()["approvals_count"] == 1

    second = await approve(async_client, test_tenant, proposed["id"], checker2_header)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "APPLIED"
    assert second.json()["approvals_count"] == 2


@pytest.mark.asyncio
async def test_six_eyes_same_approver_twice_is_duplicate_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify one admin cannot supply both required approvals for a move"""
    await _seed_policy(db_session, test_tenant, operation=None, required=2)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror_payload("Dup")
    )
    first = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert first.json()["status"] == "PENDING"

    again = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert again.status_code == 409
    assert again.json()["error_code"] == "money_operation_duplicate_approver"


@pytest.mark.asyncio
async def test_six_eyes_maker_approve_is_self_approval_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    maker_who_can_approve: dict[str, str],
) -> None:
    """Verify the proposing admin cannot count as one of the two required approvers"""
    await _seed_policy(db_session, test_tenant, operation=None, required=2)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror_payload("SelfSix")
    )
    resp = await approve(async_client, test_tenant, proposed["id"], maker_who_can_approve)
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "self_approval_forbidden"


@pytest.mark.asyncio
async def test_policy_op_specific_beats_tenant_default(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify an approval rule set for a specific move overrides the tenant-wide default"""
    await _seed_policy(db_session, test_tenant, operation=None, required=1)
    await _seed_policy(db_session, test_tenant, operation="create_bank_mirror", required=2)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror_payload("Specific")
    )
    assert proposed["required_approvals"] == 2


@pytest.mark.asyncio
async def test_policy_tenant_default_applies_when_no_op_specific(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify the tenant-wide approval rule applies to moves without their own rule"""
    await _seed_policy(db_session, test_tenant, operation=None, required=2)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror_payload("Default")
    )
    assert proposed["required_approvals"] == 2


@pytest.mark.asyncio
async def test_policy_defaults_to_one_when_absent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a move needs one approval when no approval rule is configured"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror_payload("None")
    )
    assert proposed["required_approvals"] == 1


@pytest.mark.asyncio
async def test_first_of_two_approvals_moves_no_money(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify a single approval does not move money when two are required"""
    await _seed_policy(db_session, test_tenant, operation=None, required=2)
    from tests.money_operations.conftest import account_count

    before = await account_count(db_session, test_tenant)
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror", _mirror_payload("Early")
    )
    await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert await account_count(db_session, test_tenant) == before
    assert await txn_count(db_session, test_tenant) == 0
