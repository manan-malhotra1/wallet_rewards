"""Four-eyes (required_approvals=1): a distinct checker approval EXECUTES the op.

Covers the money-moving effect + `applied_transaction_id` for each operation,
self-approval rejection, checker role gating, and the deterministic-idempotency
guard (a second approve can't double-post).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import ACCOUNT_TYPE_OPERATOR_ADJUSTMENT, Account, Tenant, User
from tests.money_operations.conftest import (
    approve,
    propose,
    seed_bank_mirror,
    seed_float,
    seed_system_wallet,
    seed_user_wallet,
    txn_count,
    user_phone,
)


@pytest.mark.asyncio
async def test_fund_user_applies_on_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """A distinct checker approving a fund → APPLIED, wallet credited, txn linked."""
    wallet = await seed_user_wallet(db_session, test_tenant, test_user)
    # fund_user DEBITs the cash float on apply; pre-fund it (no-overdraft floor).
    await seed_float(db_session, test_tenant, Decimal("1000"))
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "fund_user",
        {
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "250",
            "currency": "ZAR",
            "reason": "gift",
        },
    )
    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPLIED"
    assert body["approvals_count"] == 1
    assert body["applied_transaction_id"] is not None

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("250")


@pytest.mark.asyncio
async def test_withdraw_user_applies_on_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    funded_wallet: Account,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Approving a withdraw debits the wallet and credits the chosen mirror."""
    mirror = await seed_bank_mirror(db_session, test_tenant)
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "withdraw_user",
        {
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "200",
            "currency": "ZAR",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "cash-out",
        },
    )
    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "APPLIED"

    wallet_balance, _ = await derive_balance(db_session, funded_wallet.id)
    mirror_balance, _ = await derive_balance(db_session, mirror.id)
    assert wallet_balance == Decimal("300")
    assert mirror_balance == Decimal("200")


@pytest.mark.asyncio
async def test_adjust_system_wallet_applies_on_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Approving a positive adjust funds the target system wallet."""
    target = await seed_system_wallet(db_session, test_tenant)
    mirror = await seed_bank_mirror(db_session, test_tenant)
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "adjust_system_wallet",
        {
            "account_id": str(target.id),
            "amount": "300",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "float top-up",
        },
    )
    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "APPLIED"

    target_balance, _ = await derive_balance(db_session, target.id)
    assert target_balance == Decimal("300")


@pytest.mark.asyncio
async def test_create_bank_mirror_applies_on_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Approving a create_bank_mirror creates the operator_adjustment account.

    No `applied_transaction_id` — creating an account posts no ledger txn.
    """
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "create_bank_mirror",
        {"currency": "ZAR", "name": "Standard Bank"},
    )
    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPLIED"
    assert body["applied_transaction_id"] is None

    mirror = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.name == "Standard Bank",
            )
        )
    ).scalar_one_or_none()
    assert mirror is not None


@pytest.mark.asyncio
async def test_self_approval_forbidden(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    maker_who_can_approve: dict[str, str],
) -> None:
    """The maker cannot approve their own request even holding treasury-approver."""
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "create_bank_mirror",
        {"currency": "ZAR", "name": "Self"},
    )
    resp = await approve(async_client, test_tenant, proposed["id"], maker_who_can_approve)
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "self_approval_forbidden"
    assert await txn_count(db_session, test_tenant) == 0


@pytest.mark.asyncio
async def test_approve_requires_treasury_approver_role(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    make_admin_token,
) -> None:
    """A plain platform-admin (no treasury-approver) approving → 403."""
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "create_bank_mirror",
        {"currency": "ZAR", "name": "X"},
    )
    # Different admin, but only platform-admin — lacks treasury-approver.
    token = make_admin_token(roles=["platform-admin"], sub="44444444-4444-4000-8000-000000000004")
    other = {"Authorization": f"Bearer {token}"}
    resp = await approve(async_client, test_tenant, proposed["id"], other)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_second_approve_after_applied_is_409_no_double_post(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
    checker2_header: dict[str, str],
) -> None:
    """Re-approving an APPLIED request → 409, and NO second transaction posts.

    Guards invariant #2: the deterministic idempotency key plus the terminal
    state check together prevent a double execution.
    """
    wallet = await seed_user_wallet(db_session, test_tenant, test_user)
    # fund_user DEBITs the cash float on apply; pre-fund it (no-overdraft floor).
    await seed_float(db_session, test_tenant, Decimal("1000"))
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "fund_user",
        {
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "100",
            "currency": "ZAR",
            "reason": "gift",
        },
    )
    first = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert first.status_code == 200
    assert first.json()["status"] == "APPLIED"

    # A second distinct checker tries to approve the now-APPLIED request.
    second = await approve(async_client, test_tenant, proposed["id"], checker2_header)
    assert second.status_code == 409
    assert second.json()["error_code"] == "money_operation_invalid_state"

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("100")  # funded exactly once
    # One float top-up (seed) + exactly one fund — the re-approve posted nothing.
    assert await txn_count(db_session, test_tenant) == 2


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
