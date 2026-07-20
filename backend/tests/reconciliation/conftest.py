"""Reconciliation tests override `async_client` to be pre-authed with a
platform-admin JWT — every existing test just works without parameter
changes.

Auth-specific tests live in tests/auth/ and use the plain `async_client`
from the top-level conftest.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_async_session
from app.main import app
from app.shared.models import StepUpPolicy, Tenant


@pytest_asyncio.fixture(autouse=True)
async def _redemption_step_up_policy(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Seed a high-threshold redemption step-up policy for every reconciliation test.

    Step-up is FAIL-CLOSED (commit ff8ea05): with no policy, the redemption
    `initiate` these tests use as a fixture (`_make_pending_redemption`) 401s
    with step_up_required, masking the sweep/manual-resolve assertions. A
    threshold far above any test amount takes the below-threshold (no-PIN) path.
    Mirrors tests/redemption/conftest.py.
    """
    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="redemption",
            currency="PTS",
            threshold_amount=Decimal("100000000"),
        )
    )
    await db_session.commit()


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
