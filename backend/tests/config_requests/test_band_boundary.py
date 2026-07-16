"""Band-overlap validation under inclusive upper bounds (money-path boundary fix).

Bands are `[amount_from, amount_to]` inclusive on both ends. Two bands overlap
when the next band STARTS AT OR BEFORE the previous band's (inclusive) end. So
the common +1-gap authoring (1-200, 201-400) is valid, but shared-boundary bands
(1-200, 200-400 — both would contain 200) must be rejected as an overlap.
"""

from collections.abc import Callable

import pytest

from app.shared.models import Tenant

pytestmark = pytest.mark.asyncio

MAKER = "11111111-1111-4000-8000-000000000001"


def _url(t: Tenant) -> str:
    return f"/api/v1/config-requests?tenant_id={t.id}"


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


def _body(tenant_id, bands):
    return {"config_type": "pricing", "operation": "create", "payload": {"bands": bands}}


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_admin_token(roles=['platform-admin'], sub=MAKER)}"}


async def test_plus_one_gap_bands_accepted(async_client, test_tenant, make_admin_token):
    """1-200, 201-400 are contiguous with a +1 gap — valid under inclusive bounds."""
    bands = [_band(test_tenant.id, "1", "200", "1"), _band(test_tenant.id, "201", "400", "2")]
    resp = await async_client.post(
        _url(test_tenant), json=_body(test_tenant.id, bands), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 201, resp.text


async def test_shared_boundary_bands_rejected(async_client, test_tenant, make_admin_token):
    """1-200, 200-400 share the endpoint 200 (both contain it) → overlap rejected."""
    bands = [_band(test_tenant.id, "1", "200", "1"), _band(test_tenant.id, "200", "400", "2")]
    resp = await async_client.post(
        _url(test_tenant), json=_body(test_tenant.id, bands), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "config_request_band_overlap"
