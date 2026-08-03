"""Events tests override `async_client` to be pre-authed with a
platform-admin JWT — both events endpoints are admin-only after Phase F.4.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.main import app
from app.shared.models import Tenant


@pytest_asyncio.fixture
async def test_tenant(db_session: AsyncSession) -> Tenant:
    """Override the global `test_tenant` to REWARDS mode for events tests.

    External Kafka events may issue rewards only for `rewards`-mode tenants
    (`process_external_event`'s deployment-mode gate). The global fixture is
    `both`-mode, which the gate now rejects with `wrong_mode`, so every ingest
    test in this package binds to a rewards-mode tenant instead. Dependent
    fixtures (`test_user`, `user_points`, `default_user_role`) resolve through
    this override automatically. No float is pre-funded — external events issue
    points, they never move the cash float.
    """
    tenant = Tenant(
        name=f"events-tenant-{uuid4().hex[:8]}",
        business_type="rewards",
        base_currency="ZAR",
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def async_client(
    admin_auth_header: dict[str, str],
) -> AsyncIterator[AsyncClient]:
    """Pre-authed httpx client — every request sends the admin JWT by default."""
    from tests.conftest import TestSessionLocal

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_async_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=admin_auth_header,
    ) as client:
        yield client
    app.dependency_overrides.clear()
