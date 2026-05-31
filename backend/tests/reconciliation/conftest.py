"""Reconciliation tests override `async_client` to be pre-authed with a
platform-admin JWT — every existing test just works without parameter
changes.

Auth-specific tests live in tests/auth/ and use the plain `async_client`
from the top-level conftest.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_async_session
from app.main import app


@pytest_asyncio.fixture
async def async_client(
    admin_auth_header: dict[str, str],
) -> AsyncIterator[AsyncClient]:
    """Pre-authed httpx client — every request sends the admin JWT by default.

    Reconciliation endpoints all require `platform-admin`. Without this
    override every test would need to thread the header through manually.
    Individual tests can still override by passing `headers={...}` per call.
    """
    # Lazy import to avoid loading test infrastructure at collection time.
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


# Helper symbols re-exported for the import above.
_ = (async_sessionmaker, Callable)
