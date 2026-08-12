"""Segments tests override `async_client` to send the admin JWT by default."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID, uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.main import app
from app.shared.models import Tenant


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


@pytest_asyncio.fixture
def make_segment_group(
    async_client: AsyncClient, admin_auth_header: dict[str, str]
) -> Callable[..., Awaitable[str]]:
    """Factory: POST a segment group via the public API, return its id.

    Since Task 7, `POST /segments` requires a `group_id` — every segment
    create test needs at least one group to attach to. A factory (rather
    than a single fixed group) lets tests that need groups in more than one
    tenant, or more than one group in the same tenant, ask for exactly what
    they need instead of sharing one fixture instance.
    """

    async def _make(tenant_id: UUID, name: str | None = None) -> str:
        resp = await async_client.post(
            "/api/v1/segment-groups",
            headers=admin_auth_header,
            json={"tenant_id": str(tenant_id), "name": name or f"group-{uuid4().hex[:8]}"},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    return _make


@pytest_asyncio.fixture
async def test_segment_group(
    make_segment_group: Callable[..., Awaitable[str]], test_tenant: Tenant
) -> str:
    """One ready-to-use segment group in `test_tenant`, for tests that just need a group_id."""
    return await make_segment_group(test_tenant.id)
