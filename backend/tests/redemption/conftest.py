"""Shared fixtures and helpers for the redemption tests.

`async_client` is pre-authed with a platform-admin JWT because the admin
conversion-rate listing is admin-only; the user-facing `/internal` and
`/conversion-rates` endpoints are user-auth, so those tests override the
Authorization header per call via `_user_auth_header`.

The seeding helpers below moved here from `test_initiate_redemption.py` when
the provider redemption path was removed — they set up the points balance and
the fail-closed pricing/limit configs that internal redemption still needs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.main import app
from app.modules.rewards.service import issue_points_reward
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    LimitConfig,
    PricingConfig,
    Rule,
    StepUpPolicy,
    Tenant,
    User,
)
from tests.conftest import create_session_token_for_user

# Redemption is points-scoped: its pricing + limit configs live on the
# points_account in PTS (invariant #12 fail-closed gate, Epic 23).
_REDEMPTION_CURRENCY = "PTS"


@pytest_asyncio.fixture(autouse=True)
async def _redemption_step_up_policy(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Seed a high-threshold redemption step-up policy for every redemption test.

    Step-up is FAIL-CLOSED and runs before the config gate / idempotency in
    `initiate_internal_redemption`: with no policy the redeeming user would be
    prompted for a PIN (401), masking the pricing/limit and money-flow
    assertions. A threshold far above any test amount takes the below-threshold
    (no-PIN) path.
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


async def _seed_redemption_configs(
    session: AsyncSession,
    tenant: Tenant,
    *,
    with_pricing: bool = True,
    with_limit: bool = True,
) -> None:
    """Seed a zero-fee pricing config and/or a wide limit config for redemption.

    The fail-closed gate (invariant #12) requires BOTH a pricing and a limit
    config to resolve for the redeeming user's type before points are burned.
    Scoped to the points_account / PTS with `user_type=NULL` so the default
    covers every user type. `with_pricing` / `with_limit` let a test seed only
    one side to prove the gate fails closed when the OTHER is missing.
    """
    if with_pricing:
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type="redemption",
                account_type=ACCOUNT_TYPE_POINTS,
                currency=_REDEMPTION_CURRENCY,
                fixed_fee=Decimal("0"),
            )
        )
    if with_limit:
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type="redemption",
                account_type=ACCOUNT_TYPE_POINTS,
                currency=_REDEMPTION_CURRENCY,
                min_amount=Decimal("1"),
                max_amount=Decimal("1000000"),
            )
        )
    await session.commit()


async def _credit_user_points(
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    amount: Decimal,
    *,
    seed_key: str = "seed-pts",
) -> None:
    """Give the user points via a synthetic first_time rule reward."""
    rule = Rule(
        tenant_id=tenant.id,
        name=f"seed-rule-{seed_key}",
        rule_type="first_time",
        transaction_type="seed",
        reward_type="points",
        reward_value=amount,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    await issue_points_reward(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        rule=rule,
        triggering_event_id=seed_key,
        reward_value=amount,
    )


async def _user_auth_header(user: User) -> dict[str, str]:
    """Mint a session token for `user` and wrap in a Bearer header."""
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}
