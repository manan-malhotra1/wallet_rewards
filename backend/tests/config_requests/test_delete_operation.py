"""Maker-checker `delete` operation tests — delete removes the whole SCOPE.

The admin UI models a config as "one row per config (scope)". For multi-band
types (pricing, commission) a schedule is several `*_config` rows sharing one
scope (transaction_type[, account_type], currency, user_type). A per-config
Delete must remove EVERY band of that scope, not just the single band named by
`target_config_id`.

For single-row types (limit, wallet_limit, tax) the scope holds exactly one row,
so delete is behaviour-preserving. A DIFFERENT scope is never touched, the whole
delete lands in ONE commit (atomic), and one `*_config.deleted` audit row
captures the removed scope.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    AuditLog,
    CommissionConfig,
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


async def _propose(client: AsyncClient, tenant: Tenant, body: dict, headers: dict[str, str]):
    return await client.post(_url(tenant), content=json.dumps(body), headers=headers)


async def _approve(
    client: AsyncClient, tenant: Tenant, request_id: str, headers: dict[str, str]
) -> None:
    resp = await client.post(_url(tenant, f"/{request_id}/approve"), headers=headers)
    assert resp.status_code == 200, resp.text


async def _create_and_approve(
    client: AsyncClient, tenant: Tenant, body: dict, make_admin_token: Callable[..., str]
) -> None:
    proposed = await _propose(client, tenant, body, _maker(make_admin_token))
    assert proposed.status_code == 201, proposed.text
    await _approve(client, tenant, proposed.json()["id"], _checker(make_admin_token))


async def _propose_delete_and_approve(
    client: AsyncClient,
    tenant: Tenant,
    config_type: str,
    target_id: str,
    make_admin_token: Callable[..., str],
) -> None:
    body = {
        "config_type": config_type,
        "operation": "delete",
        "target_config_id": target_id,
    }
    proposed = await _propose(client, tenant, body, _maker(make_admin_token))
    assert proposed.status_code == 201, proposed.text
    await _approve(client, tenant, proposed.json()["id"], _checker(make_admin_token))


# -----------------------------------------------------------------------------
# Payload builders
# -----------------------------------------------------------------------------


def _pricing_band(
    tenant_id: UUID,
    frm: str | None,
    to: str | None,
    fixed: str,
    *,
    currency: str = "ZAR",
    user_type: str = "agent",
) -> dict:
    return {
        "tenant_id": str(tenant_id),
        "transaction_type": "cash_in",
        "account_type": "financial_wallet",
        "currency": currency,
        "user_type": user_type,
        "amount_from": frm,
        "amount_to": to,
        "fixed_fee": fixed,
    }


def _commission_band(tenant_id: UUID, frm: str | None, to: str | None, fixed: str) -> dict:
    return {
        "tenant_id": str(tenant_id),
        "transaction_type": "cash_in",
        "currency": "ZAR",
        "user_type": "agent",
        "amount_from": frm,
        "amount_to": to,
        "fixed_commission": fixed,
    }


def _limit_body(tenant_id: UUID, *, transaction_type: str, max_amount: str) -> dict:
    return {
        "config_type": "limit",
        "operation": "create",
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": transaction_type,
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "max_amount": max_amount,
        },
    }


async def _pricing_rows(session: AsyncSession, tenant: Tenant) -> list[PricingConfig]:
    return list(
        (
            await session.execute(
                select(PricingConfig)
                .where(PricingConfig.tenant_id == tenant.id)
                .order_by(PricingConfig.amount_from.nulls_last())
            )
        ).scalars()
    )


# -----------------------------------------------------------------------------
# Multi-band pricing: delete one band id removes the ENTIRE scope
# -----------------------------------------------------------------------------


async def test_delete_pricing_removes_whole_scope_leaves_other_scope(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Delete targeting one band of a 3-band scope removes all 3; another scope survives."""
    # Scope A: a 3-band ZAR/agent schedule.
    await _create_and_approve(
        async_client,
        test_tenant,
        {
            "config_type": "pricing",
            "operation": "create",
            "payload": {
                "bands": [
                    _pricing_band(test_tenant.id, "0", "100", "1"),
                    _pricing_band(test_tenant.id, "101", "500", "2"),
                    _pricing_band(test_tenant.id, "501", None, "3"),
                ]
            },
        },
        make_admin_token,
    )
    # Scope B: a different scope (USD) that must remain untouched.
    await _create_and_approve(
        async_client,
        test_tenant,
        {
            "config_type": "pricing",
            "operation": "create",
            "payload": {"bands": [_pricing_band(test_tenant.id, None, None, "9", currency="USD")]},
        },
        make_admin_token,
    )

    all_rows = await _pricing_rows(db_session, test_tenant)
    assert len(all_rows) == 4
    scope_a = [r for r in all_rows if r.currency == "ZAR"]
    assert len(scope_a) == 3
    target = str(scope_a[0].id)  # target the FIRST band of scope A

    await _propose_delete_and_approve(
        async_client, test_tenant, "pricing", target, make_admin_token
    )

    remaining = await _pricing_rows(db_session, test_tenant)
    # All 3 ZAR bands gone; the single USD band remains.
    assert len(remaining) == 1
    assert remaining[0].currency == "USD"


async def test_delete_commission_removes_whole_schedule(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A commission multi-band delete removes every band of the schedule."""
    await _create_and_approve(
        async_client,
        test_tenant,
        {
            "config_type": "commission",
            "operation": "create",
            "payload": {
                "bands": [
                    _commission_band(test_tenant.id, "0", "100", "1"),
                    _commission_band(test_tenant.id, "101", None, "2"),
                ]
            },
        },
        make_admin_token,
    )
    rows = list(
        (
            await db_session.execute(
                select(CommissionConfig).where(CommissionConfig.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(rows) == 2
    target = str(rows[0].id)

    await _propose_delete_and_approve(
        async_client, test_tenant, "commission", target, make_admin_token
    )

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(CommissionConfig)
            .where(CommissionConfig.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert count == 0


# -----------------------------------------------------------------------------
# Single-row types: delete removes exactly the one config, other scopes intact
# -----------------------------------------------------------------------------


async def test_delete_limit_removes_only_target_scope(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A single-row limit delete removes exactly that config; a different one stays."""
    await _create_and_approve(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, transaction_type="p2p", max_amount="1000"),
        make_admin_token,
    )
    await _create_and_approve(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, transaction_type="fund", max_amount="5000"),
        make_admin_token,
    )
    rows = list(
        (
            await db_session.execute(
                select(LimitConfig).where(LimitConfig.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(rows) == 2
    p2p = next(r for r in rows if r.transaction_type == "p2p")

    await _propose_delete_and_approve(
        async_client, test_tenant, "limit", str(p2p.id), make_admin_token
    )

    remaining = list(
        (
            await db_session.execute(
                select(LimitConfig).where(LimitConfig.tenant_id == test_tenant.id)
            )
        ).scalars()
    )
    assert len(remaining) == 1
    assert remaining[0].transaction_type == "fund"


async def test_delete_tax_removes_single_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A tax (single-row) delete removes exactly the one config."""
    await _create_and_approve(
        async_client,
        test_tenant,
        {
            "config_type": "tax",
            "operation": "create",
            "payload": {
                "tenant_id": str(test_tenant.id),
                "currency": "ZAR",
                "fee_tax_pct": "0.1",
            },
        },
        make_admin_token,
    )
    live = (
        await db_session.execute(select(TaxConfig).where(TaxConfig.tenant_id == test_tenant.id))
    ).scalar_one()

    await _propose_delete_and_approve(
        async_client, test_tenant, "tax", str(live.id), make_admin_token
    )

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(TaxConfig)
            .where(TaxConfig.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert count == 0


# -----------------------------------------------------------------------------
# Audit shape: one `.deleted` row with a before_state summarising removed bands
# -----------------------------------------------------------------------------


async def test_delete_writes_one_deleted_audit_summarising_scope(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A pricing scope delete appends exactly one `pricing_config.deleted` audit row.

    Its before_state summarises the removed bands (all 2), and audit_log has no
    updated_at (append-only, NFR-0160).
    """
    await _create_and_approve(
        async_client,
        test_tenant,
        {
            "config_type": "pricing",
            "operation": "create",
            "payload": {
                "bands": [
                    _pricing_band(test_tenant.id, "0", "100", "1"),
                    _pricing_band(test_tenant.id, "101", None, "2"),
                ]
            },
        },
        make_admin_token,
    )
    rows = await _pricing_rows(db_session, test_tenant)
    assert len(rows) == 2
    target = str(rows[0].id)

    await _propose_delete_and_approve(
        async_client, test_tenant, "pricing", target, make_admin_token
    )

    audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.tenant_id == test_tenant.id,
                    AuditLog.action == "pricing_config.deleted",
                )
            )
        ).scalars()
    )
    assert len(audits) == 1
    before = audits[0].before_state
    assert before is not None
    # before_state summarises every removed band of the scope (2 here).
    removed = before["deleted"]
    assert isinstance(removed, list)
    assert len(removed) == 2
    assert {b["fixed_fee"] for b in removed} == {"1.000000", "2.000000"}


# -----------------------------------------------------------------------------
# Missing target → 404 config_request_target_not_found (uniform error code)
# -----------------------------------------------------------------------------


async def test_delete_nonexistent_target_is_404_at_apply(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Approving a delete whose target is absent → 404 config_request_target_not_found.

    Delete propose does NOT check target existence (no payload to validate); the
    apply-time guard loads the target and 404s uniformly if it is gone.
    """
    body = {
        "config_type": "limit",
        "operation": "delete",
        "target_config_id": str(uuid4()),
    }
    proposed = await _propose(async_client, test_tenant, body, _maker(make_admin_token))
    assert proposed.status_code == 201, proposed.text

    resp = await async_client.post(
        _url(test_tenant, f"/{proposed.json()['id']}/approve"), headers=_checker(make_admin_token)
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "config_request_target_not_found"


# -----------------------------------------------------------------------------
# Atomicity: a mid-delete failure leaves the scope intact and request PENDING
# -----------------------------------------------------------------------------


async def test_delete_apply_failure_leaves_scope_intact(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after the scope delete but before commit rolls the whole thing back.

    The delete stages its row removals + audit then a SINGLE commit; injecting a
    failure at the audit step (post-delete, pre-commit) proves the scope is never
    left wiped and the request never reaches APPLIED.
    """
    await _create_and_approve(
        async_client,
        test_tenant,
        {
            "config_type": "pricing",
            "operation": "create",
            "payload": {
                "bands": [
                    _pricing_band(test_tenant.id, "0", "100", "1"),
                    _pricing_band(test_tenant.id, "101", None, "2"),
                ]
            },
        },
        make_admin_token,
    )
    rows = await _pricing_rows(db_session, test_tenant)
    assert len(rows) == 2
    target = str(rows[0].id)

    proposed = await _propose(
        async_client,
        test_tenant,
        {"config_type": "pricing", "operation": "delete", "target_config_id": target},
        _maker(make_admin_token),
    )
    request_id = proposed.json()["id"]

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected mid-delete failure")

    monkeypatch.setattr("app.modules.pricing.service.record_audit_for_admin", _boom)

    with pytest.raises(RuntimeError):
        await async_client.post(
            _url(test_tenant, f"/{request_id}/approve"), headers=_checker(make_admin_token)
        )

    # The scope was never wiped: both bands survive.
    remaining = await _pricing_rows(db_session, test_tenant)
    assert len(remaining) == 2

    # And the request never reached APPLIED.
    detail = await async_client.get(
        _url(test_tenant, f"/{request_id}"), headers=_maker(make_admin_token)
    )
    assert detail.json()["status"] == "PENDING"
