"""Maker-checker `update` operation tests (config edit → checker → atomic replace).

`update` lets an admin EDIT a live config (its scope locked) and route the
change through a checker. Apply is an atomic replace of the payload's scope:
all existing rows for the scope are deleted and the new row(s) inserted in ONE
transaction, so a live config can be changed without the create-path 409 and
without ever leaving the scope partially wiped.

Covers: propose validation (missing / non-existent target), a single-row limit
edit cycle, a multi-band pricing edit (2 → 3 bands), a tax edit cycle, the
revision-1 snapshot on an update proposal, and apply-time atomicity (a mid-apply
failure leaves the original config intact and the request un-applied).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ConfigChangeRevision,
    LimitConfig,
    PricingConfig,
    TaxConfig,
    Tenant,
)

pytestmark = pytest.mark.asyncio

MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _checker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["config-approver"], sub=CHECKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _url(tenant: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={tenant.id}"


async def _propose(
    client: AsyncClient, tenant: Tenant, body: dict, headers: dict[str, str]
) -> dict:
    resp = await client.post(_url(tenant), content=json.dumps(body), headers=headers)
    return resp


async def _approve(
    client: AsyncClient, tenant: Tenant, request_id: str, headers: dict[str, str]
) -> None:
    resp = await client.post(_url(tenant, f"/{request_id}/approve"), headers=headers)
    assert resp.status_code == 200, resp.text


# -----------------------------------------------------------------------------
# Payload builders
# -----------------------------------------------------------------------------


def _limit_body(
    tenant_id: UUID, *, operation: str, max_amount: str, target: str | None = None
) -> dict:
    body: dict = {
        "config_type": "limit",
        "operation": operation,
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": "p2p",
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "max_amount": max_amount,
        },
    }
    if target is not None:
        body["target_config_id"] = target
    return body


def _tax_body(
    tenant_id: UUID, *, operation: str, fee_tax_pct: str, target: str | None = None
) -> dict:
    body: dict = {
        "config_type": "tax",
        "operation": operation,
        "payload": {
            "tenant_id": str(tenant_id),
            "currency": "ZAR",
            "fee_tax_pct": fee_tax_pct,
        },
    }
    if target is not None:
        body["target_config_id"] = target
    return body


def _pricing_band(tenant_id: UUID, frm: str | None, to: str | None, fixed: str) -> dict:
    return {
        "tenant_id": str(tenant_id),
        "transaction_type": "cash_in",
        "account_type": "financial_wallet",
        "currency": "ZAR",
        "user_type": "agent",
        "amount_from": frm,
        "amount_to": to,
        "fixed_fee": fixed,
    }


# -----------------------------------------------------------------------------
# Propose validation
# -----------------------------------------------------------------------------


async def test_propose_update_without_target_is_422(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """An update proposal missing target_config_id → 422 (target required)."""
    resp = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="update", max_amount="2000"),
        _maker(make_admin_token),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "config_request_target_required"


async def test_propose_update_nonexistent_target_is_404(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """An update proposal whose target isn't in this tenant → 404."""
    resp = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id, operation="update", max_amount="2000", target=str(uuid4())
        ),
        _maker(make_admin_token),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "config_request_target_not_found"


async def test_propose_update_without_payload_is_422(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """An update proposal with no payload → 422 (payload required)."""
    body = {
        "config_type": "limit",
        "operation": "update",
        "target_config_id": str(uuid4()),
    }
    resp = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "config_request_payload_required"


# -----------------------------------------------------------------------------
# Single-row edit cycle (limit)
# -----------------------------------------------------------------------------


async def _create_live_limit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    make_admin_token: Callable[..., str],
    max_amount: str,
) -> LimitConfig:
    """Propose + approve a create so a live limit config exists; return it."""
    proposed = await _propose(
        async_client,
        tenant,
        _limit_body(tenant.id, operation="create", max_amount=max_amount),
        _maker(make_admin_token),
    )
    assert proposed.status_code == 201, proposed.text
    await _approve(async_client, tenant, proposed.json()["id"], _checker(make_admin_token))
    return (
        await db_session.execute(select(LimitConfig).where(LimitConfig.tenant_id == tenant.id))
    ).scalar_one()


async def test_update_limit_config_replaces_in_place(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Edit a live limit config's cap via update → new value lands, still one row."""
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, "1000"
    )
    assert live.max_amount == Decimal("1000")

    proposed = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id, operation="update", max_amount="2000", target=str(live.id)
        ),
        _maker(make_admin_token),
    )
    assert proposed.status_code == 201, proposed.text
    await _approve(async_client, test_tenant, proposed.json()["id"], _checker(make_admin_token))

    # Exactly one row for the scope, carrying the new cap (no duplicate, no 409).
    rows = list(
        (
            await db_session.execute(
                select(LimitConfig).where(LimitConfig.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].max_amount == Decimal("2000")


async def test_update_proposal_records_revision_1_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """An update proposal snapshots revision 1 like any other proposal."""
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, "1000"
    )
    proposed = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id, operation="update", max_amount="2000", target=str(live.id)
        ),
        _maker(make_admin_token),
    )
    request_id = proposed.json()["id"]
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(ConfigChangeRevision)
            .where(ConfigChangeRevision.request_id == UUID(request_id))
        )
    ).scalar_one()
    assert count == 1

    detail = await async_client.get(
        _url(test_tenant, f"/{request_id}"), headers=_maker(make_admin_token)
    )
    revisions = detail.json()["revisions"]
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1


# -----------------------------------------------------------------------------
# Multi-band edit cycle (pricing): 2 bands → 3 bands
# -----------------------------------------------------------------------------


async def test_update_pricing_replaces_whole_band_set(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A live 2-band schedule edited to 3 bands → scope has exactly the 3 new bands."""
    create_body = {
        "config_type": "pricing",
        "operation": "create",
        "payload": {
            "bands": [
                _pricing_band(test_tenant.id, "0", "100", "1"),
                _pricing_band(test_tenant.id, "101", None, "2"),
            ]
        },
    }
    created = await _propose(async_client, test_tenant, create_body, _maker(make_admin_token))
    assert created.status_code == 201, created.text
    await _approve(async_client, test_tenant, created.json()["id"], _checker(make_admin_token))

    live_rows = list(
        (
            await db_session.execute(
                select(PricingConfig).where(PricingConfig.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(live_rows) == 2
    target = str(live_rows[0].id)

    # Edit to a 3-band schedule (add a slab) for the SAME scope.
    update_body = {
        "config_type": "pricing",
        "operation": "update",
        "target_config_id": target,
        "payload": {
            "bands": [
                _pricing_band(test_tenant.id, "0", "100", "1"),
                _pricing_band(test_tenant.id, "101", "500", "2"),
                _pricing_band(test_tenant.id, "501", None, "4"),
            ]
        },
    }
    updated = await _propose(async_client, test_tenant, update_body, _maker(make_admin_token))
    assert updated.status_code == 201, updated.text
    await _approve(async_client, test_tenant, updated.json()["id"], _checker(make_admin_token))

    rows = list(
        (
            await db_session.execute(
                select(PricingConfig)
                .where(PricingConfig.tenant_id == test_tenant.id)
                .order_by(PricingConfig.amount_from.nulls_last())
            )
        ).scalars()
    )
    # Old 2 bands gone; exactly the 3 new bands remain.
    assert len(rows) == 3
    assert [r.fixed_fee for r in rows] == [Decimal("1"), Decimal("2"), Decimal("4")]
    assert rows[2].amount_to is None  # the new open-ended top band


# -----------------------------------------------------------------------------
# Tax edit cycle (single-row, no user_type / transaction_type in scope)
# -----------------------------------------------------------------------------


async def test_update_tax_config_replaces_in_place(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A tax (single-row) edit cycle works: new rate lands, still one row."""
    created = await _propose(
        async_client,
        test_tenant,
        _tax_body(test_tenant.id, operation="create", fee_tax_pct="0.1"),
        _maker(make_admin_token),
    )
    assert created.status_code == 201, created.text
    await _approve(async_client, test_tenant, created.json()["id"], _checker(make_admin_token))
    live = (
        await db_session.execute(select(TaxConfig).where(TaxConfig.tenant_id == test_tenant.id))
    ).scalar_one()

    updated = await _propose(
        async_client,
        test_tenant,
        _tax_body(
            test_tenant.id, operation="update", fee_tax_pct="0.2", target=str(live.id)
        ),
        _maker(make_admin_token),
    )
    assert updated.status_code == 201, updated.text
    await _approve(async_client, test_tenant, updated.json()["id"], _checker(make_admin_token))

    rows = list(
        (
            await db_session.execute(select(TaxConfig).where(TaxConfig.tenant_id == test_tenant.id))
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].fee_tax_pct == Decimal("0.2")


# -----------------------------------------------------------------------------
# Atomicity: a mid-apply failure leaves the original config intact
# -----------------------------------------------------------------------------


async def test_update_apply_failure_leaves_original_intact(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the replace raises AFTER its delete+insert but before commit, the whole
    replace rolls back: the original config survives and the request is un-applied.

    The replace does its delete+insert then the audit write then a SINGLE commit;
    injecting a failure at the audit step (post-flush, pre-commit) exercises the
    all-or-none guarantee that a partial replace can never persist.
    """
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, "1000"
    )
    proposed = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id, operation="update", max_amount="2000", target=str(live.id)
        ),
        _maker(make_admin_token),
    )
    request_id = proposed.json()["id"]

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected mid-apply failure")

    # Fail inside the replace helper, after the delete+insert flush, before commit.
    monkeypatch.setattr("app.modules.limits.service.record_audit_for_admin", _boom)

    with pytest.raises(RuntimeError):
        await async_client.post(
            _url(test_tenant, f"/{request_id}/approve"), headers=_checker(make_admin_token)
        )

    # The scope was never wiped: still exactly one row with the ORIGINAL cap.
    rows = list(
        (
            await db_session.execute(
                select(LimitConfig).where(LimitConfig.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].max_amount == Decimal("1000")

    # And the request never reached APPLIED (its staged transition rolled back too).
    detail = await async_client.get(
        _url(test_tenant, f"/{request_id}"), headers=_maker(make_admin_token)
    )
    assert detail.json()["status"] == "PENDING"


# -----------------------------------------------------------------------------
# Governance trust boundary: the edit's scope must match the target's scope
# -----------------------------------------------------------------------------


async def test_update_scope_mismatch_rejected_matching_succeeds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """An update naming target X (scope A) with a payload for scope B → 422.

    Otherwise the request would silently replace scope B and leave X untouched.
    A same-scope edit against the same target still succeeds.
    """
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, "1000"
    )

    # Same target id, but a payload whose transaction_type (scope) differs.
    mismatched = {
        "config_type": "limit",
        "operation": "update",
        "target_config_id": str(live.id),
        "payload": {
            "tenant_id": str(test_tenant.id),
            "transaction_type": "fund",  # scope B — target is scope A ("p2p")
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "max_amount": "2000",
        },
    }
    resp = await _propose(async_client, test_tenant, mismatched, _maker(make_admin_token))
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "config_request_scope_mismatch"

    # The matching-scope edit against the same target is accepted.
    ok = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id, operation="update", max_amount="2000", target=str(live.id)
        ),
        _maker(make_admin_token),
    )
    assert ok.status_code == 201, ok.text


# -----------------------------------------------------------------------------
# An update proposal is revisable exactly like a create
# -----------------------------------------------------------------------------


async def test_update_proposal_can_be_revised_and_resubmitted(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """request-changes on an update → revise → resubmit → approve applies the revised edit.

    The request stays operation=update, the snapshot revision bumps, and the
    revised cap is what lands on the live config.
    """
    live = await _create_live_limit(
        async_client, db_session, test_tenant, make_admin_token, "1000"
    )
    proposed = await _propose(
        async_client,
        test_tenant,
        _limit_body(
            test_tenant.id, operation="update", max_amount="2000", target=str(live.id)
        ),
        _maker(make_admin_token),
    )
    request_id = proposed.json()["id"]
    assert proposed.json()["operation"] == "update"

    # Checker asks for changes → CHANGES_REQUESTED.
    rc = await async_client.post(
        _url(test_tenant, f"/{request_id}/request-changes"),
        content=json.dumps({"comment": "Make it 3000 instead."}),
        headers=_checker(make_admin_token),
    )
    assert rc.status_code == 200, rc.text

    # Maker revises the update's payload in place (2000 → 3000), bumping revision.
    revised = await async_client.patch(
        _url(test_tenant, f"/{request_id}"),
        content=json.dumps(
            {
                "payload": {
                    "tenant_id": str(test_tenant.id),
                    "transaction_type": "p2p",
                    "account_type": "financial_wallet",
                    "currency": "ZAR",
                    "max_amount": "3000",
                }
            }
        ),
        headers=_maker(make_admin_token),
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["operation"] == "update"  # still an update
    assert revised.json()["revision"] == 2

    resub = await async_client.post(
        _url(test_tenant, f"/{request_id}/resubmit"), headers=_maker(make_admin_token)
    )
    assert resub.status_code == 200, resub.text
    await _approve(async_client, test_tenant, request_id, _checker(make_admin_token))

    # The REVISED cap (3000) landed on the single live row for the scope.
    rows = list(
        (
            await db_session.execute(
                select(LimitConfig).where(LimitConfig.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].max_amount == Decimal("3000")
