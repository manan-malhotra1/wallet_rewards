"""Multi-band pricing/commission config-change requests (Epic 25).

A pricing or commission create proposal may carry several amount bands as
`{"bands": [row, ...]}`; propose validates the set and approve applies all bands
in one all-or-none transaction. Legacy single-dict payloads still work.
"""

from collections.abc import Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import PricingConfig, Tenant

pytestmark = pytest.mark.asyncio

MAKER = "11111111-1111-4000-8000-000000000001"
CHECKER = "22222222-2222-4000-8000-000000000002"


def _url(t: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={t.id}"


def _band(tenant_id, frm, to, fixed):
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


def _bands_body(tenant_id, bands=None):
    return {
        "config_type": "pricing",
        "operation": "create",
        "payload": {
            "bands": bands
            or [_band(tenant_id, "0", "100", "1"), _band(tenant_id, "100", None, "2")]
        },
    }


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_admin_token(roles=['platform-admin'], sub=MAKER)}"}


def _checker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {make_admin_token(roles=['platform-admin', 'config-approver'], sub=CHECKER)}"
        )
    }


async def _pricing_count(session: AsyncSession, tenant: Tenant) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(PricingConfig).where(
                PricingConfig.tenant_id == tenant.id
            )
        )
    ).scalar_one()


async def test_multi_band_propose_accepted(async_client, test_tenant, make_admin_token):
    resp = await async_client.post(
        _url(test_tenant), json=_bands_body(test_tenant.id), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["payload"]["bands"]) == 2


async def test_overlapping_bands_rejected(async_client, test_tenant, make_admin_token):
    bad = [_band(test_tenant.id, "0", "100", "1"), _band(test_tenant.id, "50", "200", "2")]
    resp = await async_client.post(
        _url(test_tenant), json=_bands_body(test_tenant.id, bad), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "config_request_band_overlap"


async def test_band_scope_mismatch_rejected(async_client, test_tenant, make_admin_token):
    b2 = _band(test_tenant.id, "100", None, "2")
    b2["currency"] = "USD"  # different scope than band 1
    resp = await async_client.post(
        _url(test_tenant),
        json=_bands_body(test_tenant.id, [_band(test_tenant.id, "0", "100", "1"), b2]),
        headers=_maker(make_admin_token),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "config_request_band_scope_mismatch"


async def test_multi_band_apply_creates_all_rows(
    async_client, db_session, test_tenant, make_admin_token
):
    rid = (
        await async_client.post(
            _url(test_tenant), json=_bands_body(test_tenant.id), headers=_maker(make_admin_token)
        )
    ).json()["id"]
    resp = await async_client.post(
        _url(test_tenant, f"/{rid}/approve"), headers=_checker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert await _pricing_count(db_session, test_tenant) == 2


async def test_single_dict_payload_still_applies(
    async_client, db_session, test_tenant, make_admin_token
):
    body = {
        "config_type": "pricing",
        "operation": "create",
        "payload": _band(test_tenant.id, None, None, "5"),  # legacy flat dict
    }
    rid = (
        await async_client.post(_url(test_tenant), json=body, headers=_maker(make_admin_token))
    ).json()["id"]
    resp = await async_client.post(
        _url(test_tenant, f"/{rid}/approve"), headers=_checker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert await _pricing_count(db_session, test_tenant) == 1


def _commission_band(tenant_id, frm, to, fixed):
    """A commission band — note: NO account_type (commission is keyed without it)."""
    return {
        "tenant_id": str(tenant_id),
        "transaction_type": "cash_in",
        "currency": "ZAR",
        "user_type": "agent",
        "amount_from": frm,
        "amount_to": to,
        "fixed_commission": fixed,
    }


async def test_commission_multi_band_propose_and_apply(
    async_client, db_session, test_tenant, make_admin_token
):
    """Commission schedules (no account_type) must propose + apply, not 500."""
    from sqlalchemy import func, select

    from app.shared.models import CommissionConfig

    body = {
        "config_type": "commission",
        "operation": "create",
        "payload": {
            "bands": [
                _commission_band(test_tenant.id, "0", "100", "1"),
                _commission_band(test_tenant.id, "100", None, "2"),
            ]
        },
    }
    rid = (
        await async_client.post(_url(test_tenant), json=body, headers=_maker(make_admin_token))
    ).json()["id"]
    resp = await async_client.post(
        _url(test_tenant, f"/{rid}/approve"), headers=_checker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    n = (
        await db_session.execute(
            select(func.count()).select_from(CommissionConfig).where(
                CommissionConfig.tenant_id == test_tenant.id
            )
        )
    ).scalar_one()
    assert n == 2


async def test_list_filtered_by_config_type(async_client, test_tenant, make_admin_token):
    await async_client.post(
        _url(test_tenant), json=_bands_body(test_tenant.id), headers=_maker(make_admin_token)
    )
    resp = await async_client.get(
        f"/api/v1/config-requests?tenant_id={test_tenant.id}&config_type=commission",
        headers=_maker(make_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []  # only a pricing request exists
