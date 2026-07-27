"""Reviewer names — showing who proposed and who approved a config change.

Makers/checkers are Keycloak subs internally; the API resolves each to a human
display name (recorded in `admin_profiles` when the admin acts) so the review UI
can show "alice-maker" instead of a UUID.
"""

from collections.abc import Callable
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant

pytestmark = pytest.mark.asyncio

MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"


def _propose_body(tenant_id: UUID) -> dict:
    return {
        "config_type": "pricing",
        "operation": "create",
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": "cash_in",
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "fixed_fee": "5",
        },
    }


def _url(tenant: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={tenant.id}"


async def test_maker_and_checker_names_resolved(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify the review screen shows the names of the admins who proposed and approved a change."""
    maker_token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB, username="alice-maker")
    checker_token = make_admin_token(
        roles=["platform-admin", "config-approver"],
        sub=CHECKER_SUB,
        username="bob-checker",
    )
    maker = {"Authorization": f"Bearer {maker_token}"}
    checker = {"Authorization": f"Bearer {checker_token}"}

    proposed = await async_client.post(
        _url(test_tenant), json=_propose_body(test_tenant.id), headers=maker
    )
    assert proposed.status_code == 201, proposed.text
    request_id = proposed.json()["id"]

    # Maker name is resolved even before any checker acts.
    detail = await async_client.get(_url(test_tenant, f"/{request_id}"), headers=checker)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["maker_admin_name"] == "alice-maker"
    assert body["checker_admin_name"] is None

    approved = await async_client.post(_url(test_tenant, f"/{request_id}/approve"), headers=checker)
    assert approved.status_code == 200, approved.text
    assert approved.json()["checker_admin_name"] == "bob-checker"

    # Review thread carries each actor's display name.
    final = await async_client.get(_url(test_tenant, f"/{request_id}"), headers=checker)
    reviews = final.json()["reviews"]
    actor_names = {r["action"]: r["actor_admin_name"] for r in reviews}
    assert actor_names["submitted"] == "alice-maker"
    assert actor_names["approved"] == "bob-checker"
