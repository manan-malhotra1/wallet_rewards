"""`base_service_code` on `GET /api/v1/identity/me/services` (Task 7, spec §12.1).

`MyServiceOut.base_service_code` lets the mobile app group tiles by the
platform flow they delegate to, without knowing every derived code that will
ever exist: NULL for a base service, the base's code for a derived one. This
mirrors the `Service` model's own `kind`/`base_service_code` pairing (Task 2).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Service, Tenant, User


async def _seed_base_and_derived(session: AsyncSession, tenant: Tenant) -> None:
    """Seed a live base 'p2p' service and a derived 'p2p_diaspora' on top of it.

    Both are left unrestricted on user_type/channel (NULL arrays) so they
    surface for any caller regardless of user_type — the test only cares
    about `base_service_code`, not the access-policy filter.
    """
    session.add(
        Service(
            tenant_id=tenant.id,
            code="p2p",
            display_name="Send money",
            kind="base",
        )
    )
    session.add(
        Service(
            tenant_id=tenant.id,
            code="p2p_diaspora",
            display_name="Send money (diaspora)",
            kind="derived",
            base_service_code="p2p",
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_me_services_exposes_base_service_code_for_derived_and_null_for_base(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a derived service reports its base, and a base service reports null"""
    await _seed_base_and_derived(db_session, test_tenant)

    response = await async_client.get("/api/v1/identity/me/services", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    rows_by_code = {row["code"]: row for row in response.json()}

    assert rows_by_code["p2p"]["base_service_code"] is None
    assert rows_by_code["p2p_diaspora"]["base_service_code"] == "p2p"
