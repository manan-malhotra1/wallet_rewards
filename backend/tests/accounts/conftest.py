"""Accounts tests override `async_client` to be pre-authed with a
platform-admin JWT — every accounts endpoint is admin-only after Phase F.4.

Mirrors `tests/reconciliation/conftest.py`. End-user balance lookups go
through the catalog `/me/summary` endpoint, tested separately.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.main import app


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
