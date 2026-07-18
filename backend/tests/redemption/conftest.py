"""Redemption tests share an async_client pre-authed with a platform-admin
JWT — provider registration, confirm, and fail are admin-only after Phase F.4.

The user-facing `/initiate` endpoint and `/{redemption_id}` GET are user-auth
— individual tests override the Authorization header per call with the
`alice_auth_header` fixture from the top-level conftest.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.main import app
from app.shared.models import StepUpPolicy, Tenant


@pytest_asyncio.fixture(autouse=True)
async def _redemption_step_up_policy(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Seed a high-threshold redemption step-up policy for every redemption test.

    Step-up is FAIL-CLOSED and runs before the config gate / idempotency in
    `initiate_redemption`: with no policy the redeeming user would be prompted
    for a PIN (401), masking the pricing/limit and money-flow assertions. A
    threshold far above any test amount takes the below-threshold (no-PIN) path.
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
