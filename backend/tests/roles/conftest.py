"""Role tests — pre-authed async_client with platform-admin JWT.

Same pattern as `tests/reconciliation/conftest.py`. Every role CRUD endpoint
requires the `platform-admin` realm role (Phase F.1 gate), so the default
client must carry that token.
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
    """Pre-authed httpx client — admin JWT attached by default."""
    from tests.conftest import TestSessionLocal  # noqa: PLC0415

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
