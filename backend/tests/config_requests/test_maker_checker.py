"""Maker-checker workflow — proposing, approving, and revising config changes.

Propose → (approve | request-changes → revise → resubmit)* → APPLIED / WITHDRAWN.
Covers: no config row until APPLIED; four-eyes (self-approval 409, role 403);
the full revise-and-resubmit loop applying the *revised* config; and isolation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import PricingConfig, Tenant

MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _checker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["config-approver"], sub=CHECKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _maker_who_can_approve(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """Same sub as the maker but also holds config-approver (self-approval test)."""
    token = make_admin_token(roles=["platform-admin", "config-approver"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _pricing_payload(tenant_id: UUID, fixed_fee: str = "5") -> dict:
    return {
        "config_type": "pricing",
        "operation": "create",
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": "cash_in",
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "fixed_fee": fixed_fee,
        },
    }


async def _pricing_count(session: AsyncSession, tenant: Tenant) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(PricingConfig)
            .where(PricingConfig.tenant_id == tenant.id)
        )
    ).scalar_one()


def _url(tenant: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={tenant.id}"


@pytest.mark.asyncio
async def test_propose_creates_pending_no_config_write(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a proposed config change stays pending and does not take effect until approved."""
    resp = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["maker_admin_id"] == MAKER_SUB
    assert await _pricing_count(db_session, test_tenant) == 0


@pytest.mark.asyncio
async def test_approve_by_different_admin_applies_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a config change goes live once a second admin approves it."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]

    approved = await async_client.post(
        _url(test_tenant, f"/{request_id}/approve"),
        headers=_checker(make_admin_token),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPLIED"
    assert approved.json()["checker_admin_id"] == CHECKER_SUB
    assert await _pricing_count(db_session, test_tenant) == 1


@pytest.mark.asyncio
async def test_self_approval_forbidden(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify the admin who proposed a change cannot approve their own change."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]

    resp = await async_client.post(
        _url(test_tenant, f"/{request_id}/approve"),
        headers=_maker_who_can_approve(make_admin_token),
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "self_approval_forbidden"


@pytest.mark.asyncio
async def test_approve_requires_config_approver_role(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify only an admin with approver rights can approve a config change."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]
    # A different admin, but only platform-admin — lacks config-approver.
    other = {
        "Authorization": f"Bearer {make_admin_token(roles=['platform-admin'], sub=CHECKER_SUB)}",
    }
    resp = await async_client.post(_url(test_tenant, f"/{request_id}/approve"), headers=other)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_full_revise_resubmit_loop_applies_revised_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a change sent back for edits applies the revised version once re-approved."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id, fixed_fee="5")),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]

    # Checker asks for changes (mandatory comment) → CHANGES_REQUESTED.
    rc = await async_client.post(
        _url(test_tenant, f"/{request_id}/request-changes"),
        content=json.dumps({"comment": "Fee too high, drop to 3."}),
        headers=_checker(make_admin_token),
    )
    assert rc.status_code == 200, rc.text
    assert rc.json()["status"] == "CHANGES_REQUESTED"

    # Maker revises the payload in place (fee 5 → 3), bumping revision.
    revised = await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps(
            {
                "payload": {
                    "tenant_id": str(test_tenant.id),
                    "transaction_type": "cash_in",
                    "account_type": "financial_wallet",
                    "currency": "ZAR",
                    "fixed_fee": "3",
                }
            }
        ),
        headers=_maker(make_admin_token),
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["revision"] == 2
    # Pricing payloads are stored as a multi-band schedule (Epic 25).
    assert revised.json()["payload"]["bands"][0]["fixed_fee"] == "3"

    # Maker resubmits → back to PENDING.
    resub = await async_client.post(
        _url(test_tenant, f"/{request_id}/resubmit"), headers=_maker(make_admin_token)
    )
    assert resub.status_code == 200, resub.text
    assert resub.json()["status"] == "PENDING"

    # Checker approves → APPLIED with the REVISED fee (3), same request id.
    approved = await async_client.post(
        _url(test_tenant, f"/{request_id}/approve"), headers=_checker(make_admin_token)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPLIED"

    config = (
        await db_session.execute(
            select(PricingConfig).where(PricingConfig.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert config.fixed_fee == Decimal("3.000000")  # the revised value landed

    # The review thread persisted the whole loop.
    detail = await async_client.get(
        _url(test_tenant, f"/{request_id}"), headers=_maker(make_admin_token)
    )
    actions = [r["action"] for r in detail.json()["reviews"]]
    assert actions == [
        "submitted",
        "changes_requested",
        "revised",
        "resubmitted",
        "approved",
    ]


@pytest.mark.asyncio
async def test_revise_by_non_maker_forbidden(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify only the admin who proposed a change may edit it after changes are requested."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]
    await async_client.post(
        _url(test_tenant, f"/{request_id}/request-changes"),
        content=json.dumps({"comment": "change it"}),
        headers=_checker(make_admin_token),
    )
    # A different platform-admin tries to revise → 403.
    other_maker = {
        "Authorization": f"Bearer {make_admin_token(roles=['platform-admin'], sub=CHECKER_SUB)}",
        "Content-Type": "application/json",
    }
    resp = await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps({"payload": _pricing_payload(test_tenant.id)["payload"]}),
        headers=other_maker,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_request_changes_requires_comment(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify requesting changes requires a comment explaining why."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]
    resp = await async_client.post(
        _url(test_tenant, f"/{request_id}/request-changes"),
        content=json.dumps({}),
        headers=_checker(make_admin_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_withdraw_is_terminal(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a withdrawn change stays withdrawn and can no longer be approved."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]
    withdrawn = await async_client.post(
        _url(test_tenant, f"/{request_id}/withdraw"), headers=_maker(make_admin_token)
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"

    resp = await async_client.post(
        _url(test_tenant, f"/{request_id}/approve"), headers=_checker(make_admin_token)
    )
    assert resp.status_code == 409
    assert await _pricing_count(db_session, test_tenant) == 0


@pytest.mark.asyncio
async def test_wallet_limit_config_via_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify wallet-balance limits can also be changed through the approval workflow."""
    from app.shared.models import WalletLimitConfig

    proposal = {
        "config_type": "wallet_limit",
        "operation": "create",
        "payload": {
            "tenant_id": str(test_tenant.id),
            "currency": "ZAR",
            "max_balance": "50000",
        },
    }
    proposed = await async_client.post(
        _url(test_tenant), content=json.dumps(proposal), headers=_maker(make_admin_token)
    )
    assert proposed.status_code == 201, proposed.text
    request_id = proposed.json()["id"]
    approved = await async_client.post(
        _url(test_tenant, f"/{request_id}/approve"), headers=_checker(make_admin_token)
    )
    assert approved.status_code == 200, approved.text

    config = (
        await db_session.execute(
            select(WalletLimitConfig).where(WalletLimitConfig.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert config.max_balance == Decimal("50000.000000")


@pytest.mark.asyncio
async def test_propose_invalid_payload_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a config change with invalid values is rejected cleanly."""
    bad = {
        "config_type": "pricing",
        "operation": "create",
        # variable_fee_pct must be < 1 — 5 is invalid.
        "payload": {
            "tenant_id": str(test_tenant.id),
            "transaction_type": "cash_in",
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "variable_fee_pct": "5",
        },
    }
    resp = await async_client.post(
        _url(test_tenant), content=json.dumps(bad), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_tenant_isolation_on_request(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify one tenant cannot see another tenant's config change request."""
    proposed = await async_client.post(
        _url(test_tenant),
        content=json.dumps(_pricing_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    request_id = proposed.json()["id"]
    resp = await async_client.get(
        _url(other_tenant, f"/{request_id}"), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 404
