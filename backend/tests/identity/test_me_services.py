"""My services — the home tiles a signed-in mobile user may initiate.

`GET /api/v1/identity/me/services` returns the active, non-deleted services
whose access policy (`allowed_user_types` x `allowed_channels`) admits the
caller's user_type on the `mobile` channel. The mobile app renders one tile
per row.

Covers:
  - A consumer sees consumer/mobile services (p2p, airtime, cashout) and NOT
    the agent-only cash_in.
  - An agent sees cash_in and NOT the consumer-only p2p.
  - NULL / empty policy arrays mean "unrestricted" on that dimension.
  - Soft-deleted / disabled / non-mobile services never surface.
  - 401 without a session token.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    SERVICE_STATUS_DISABLED,
    Service,
    Tenant,
    User,
)


async def _seed_catalog(session: AsyncSession, tenant: Tenant) -> None:
    """Seed a representative slice of the service catalog for a tenant.

    Mirrors the shipped per-code seed: consumer/mobile services, an agent-only
    cash_in, an operator-only fund (empty user-types + admin/api channels), plus
    edge rows (disabled, soft-deleted, unrestricted) so the filter is exercised.
    """
    from datetime import UTC, datetime

    session.add_all(
        [
            Service(
                tenant_id=tenant.id,
                code="p2p",
                display_name="Send money",
                allowed_user_types=["consumer"],
                allowed_channels=["mobile"],
            ),
            Service(
                tenant_id=tenant.id,
                code="airtime_recharge",
                display_name="Buy airtime",
                allowed_user_types=["consumer"],
                allowed_channels=["mobile"],
            ),
            Service(
                tenant_id=tenant.id,
                code="cashout",
                display_name="Cash out",
                allowed_user_types=["consumer"],
                allowed_channels=["mobile"],
            ),
            # Agent-only deposit — a consumer must NOT see this.
            Service(
                tenant_id=tenant.id,
                code="cash_in",
                display_name="Cash in",
                allowed_user_types=["agent", "super_agent"],
                allowed_channels=["mobile"],
            ),
            # Operator-only: empty user-types + admin/api channels → no wallet
            # user, on no wallet channel, may see it.
            Service(
                tenant_id=tenant.id,
                code="fund",
                display_name="Fund wallet",
                allowed_user_types=[],
                allowed_channels=["admin", "api"],
            ),
            # Unrestricted on both dimensions (NULL arrays) → visible to anyone
            # on any channel, including mobile.
            Service(
                tenant_id=tenant.id,
                code="change_pin",
                display_name="Change PIN",
                allowed_user_types=None,
                allowed_channels=None,
            ),
            # Disabled — never surfaces even though it would otherwise match.
            Service(
                tenant_id=tenant.id,
                code="p2p_disabled",
                display_name="Disabled service",
                status=SERVICE_STATUS_DISABLED,
                allowed_user_types=["consumer"],
                allowed_channels=["mobile"],
            ),
            # Soft-deleted — never surfaces.
            Service(
                tenant_id=tenant.id,
                code="p2p_deleted",
                display_name="Deleted service",
                allowed_user_types=["consumer"],
                allowed_channels=["mobile"],
                deleted_at=datetime.now(UTC),
            ),
            # Web-only — a mobile caller must NOT see it (channel mismatch).
            Service(
                tenant_id=tenant.id,
                code="web_only",
                display_name="Web only",
                allowed_user_types=["consumer"],
                allowed_channels=["web"],
            ),
        ]
    )
    await session.commit()


@pytest.mark.asyncio
async def test_me_services_consumer_sees_consumer_mobile_services(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a consumer sees the services they can start and nothing else"""
    # test_user defaults to user_type 'consumer'.
    await _seed_catalog(db_session, test_tenant)

    response = await async_client.get("/api/v1/identity/me/services", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    codes = [row["code"] for row in response.json()]

    # Consumer/mobile services + the unrestricted one are present.
    assert "p2p" in codes
    assert "airtime_recharge" in codes
    assert "cashout" in codes
    assert "change_pin" in codes
    # Agent-only, operator-only, web-only, disabled, deleted are all excluded.
    assert "cash_in" not in codes
    assert "fund" not in codes
    assert "web_only" not in codes
    assert "p2p_disabled" not in codes
    assert "p2p_deleted" not in codes


@pytest.mark.asyncio
async def test_me_services_ordered_by_display_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify the tiles come back in a stable display-name order"""
    await _seed_catalog(db_session, test_tenant)

    response = await async_client.get("/api/v1/identity/me/services", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    names = [row["display_name"] for row in response.json()]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_me_services_agent_sees_cash_in_not_p2p(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify an agent sees agent services and not consumer-only ones"""
    from tests.conftest import create_session_token_for_user

    # Promote the seeded user to an agent so the same session maps to user_type
    # 'agent'.
    test_user.user_type = "agent"
    db_session.add(test_user)
    await db_session.commit()
    await _seed_catalog(db_session, test_tenant)

    token = await create_session_token_for_user(test_user.id, test_user.tenant_id)
    response = await async_client.get(
        "/api/v1/identity/me/services",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    codes = [row["code"] for row in response.json()]

    # Agent sees the agent-only deposit + the unrestricted service.
    assert "cash_in" in codes
    assert "change_pin" in codes
    # Consumer-only services are hidden from the agent.
    assert "p2p" not in codes
    assert "airtime_recharge" not in codes
    assert "cashout" not in codes
    # Operator-only fund is still hidden (agent is not an admin/api channel).
    assert "fund" not in codes


@pytest.mark.asyncio
async def test_me_services_does_not_leak_other_tenant_services(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a user never sees another tenant's services"""
    # Seed a matching service ONLY in the other tenant.
    db_session.add(
        Service(
            tenant_id=other_tenant.id,
            code="p2p",
            display_name="Send money",
            allowed_user_types=["consumer"],
            allowed_channels=["mobile"],
        )
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/services", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    # test_user's tenant has no services seeded → empty list, never the other
    # tenant's row.
    assert response.json() == []


@pytest.mark.asyncio
async def test_me_services_no_token_is_401(async_client: AsyncClient) -> None:
    """Verify listing services requires signing in"""
    response = await async_client.get("/api/v1/identity/me/services")
    assert response.status_code == 401
