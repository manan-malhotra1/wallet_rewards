"""Points-denominated config is rejected for a wallet-only tenant (B6.1).

The UI hides the points options for a wallet-only tenant, but the API is
reachable directly, and a hidden dropdown is not enforcement: a PTS-scoped
pricing or limit row for a tenant with no points programme could never execute
— dead config of exactly the kind invariant #12 forbids. These pin the 422 at
PROPOSE time (the maker hears it immediately), and that rewards-capable modes
are untouched.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant

MAKER_SUB = "11111111-1111-4000-8000-000000000001"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _points_limit_payload(tenant_id: UUID) -> dict:
    return {
        "config_type": "limit",
        "operation": "create",
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": "redemption",
            "account_type": "points_account",
            "currency": "PTS",
            "min_amount": "1",
            "max_amount": "1000",
        },
    }


async def _wallet_only_tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(
        name=f"wallet-only-{uuid4().hex[:8]}",
        business_type="wallet",
        base_currency="USD",
    )
    session.add(tenant)
    await session.commit()
    return tenant


@pytest.mark.asyncio
async def test_points_config_is_rejected_for_a_wallet_only_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify proposing a PTS-scoped config for a wallet-only tenant 422s."""
    tenant = await _wallet_only_tenant(db_session)

    resp = await async_client.post(
        f"/api/v1/config-requests?tenant_id={tenant.id}",
        content=json.dumps(_points_limit_payload(tenant.id)),
        headers=_maker(make_admin_token),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "points_not_available"


@pytest.mark.asyncio
async def test_points_config_is_accepted_for_a_rewards_capable_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify the gate does not touch tenants whose mode includes rewards.

    `test_tenant` is 'both' mode — the same proposal must land as PENDING.
    """
    resp = await async_client.post(
        f"/api/v1/config-requests?tenant_id={test_tenant.id}",
        content=json.dumps(_points_limit_payload(test_tenant.id)),
        headers=_maker(make_admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "PENDING"


@pytest.mark.asyncio
async def test_fiat_config_is_unaffected_for_a_wallet_only_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a wallet-only tenant can still propose ordinary fiat config."""
    tenant = await _wallet_only_tenant(db_session)

    resp = await async_client.post(
        f"/api/v1/config-requests?tenant_id={tenant.id}",
        content=json.dumps(
            {
                "config_type": "limit",
                "operation": "create",
                "payload": {
                    "tenant_id": str(tenant.id),
                    "transaction_type": "p2p",
                    "account_type": "financial_wallet",
                    "currency": "USD",
                    "min_amount": "1",
                    "max_amount": "1000",
                },
            }
        ),
        headers=_maker(make_admin_token),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_points_instrument_is_rejected_for_a_wallet_only_tenant(
    db_session: AsyncSession,
) -> None:
    """Verify recreating the points surface via a new instrument also 422s.

    Provisioning no longer gives a wallet-only tenant PTS, so the instruments
    endpoint must not offer a way to bring it back.
    """
    from app.auth import AdminPrincipal
    from app.modules.instruments.schemas import InstrumentCreateRequest
    from app.modules.instruments.service import create_instrument
    from app.shared.exceptions import AppHTTPException

    tenant = await _wallet_only_tenant(db_session)

    with pytest.raises(AppHTTPException) as excinfo:
        await create_instrument(
            db_session,
            InstrumentCreateRequest(
                tenant_id=tenant.id,
                code="PTS",
                symbol="Rewards",
                display_name="Rewards Points",
                account_type="points_account",
            ),
            admin=AdminPrincipal(
                id="00000000-0000-4000-8000-0000000000ad",
                username="admin",
                roles=frozenset(),
            ),
        )
    assert excinfo.value.status_code == 422
