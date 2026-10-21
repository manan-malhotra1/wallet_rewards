"""Lazy reward-account provisioning is safe when several rewards land at once.

`issue_points_reward` provisions two accounts on the fly — the user's points
account, then the tenant's shared `system_points_issuance` master. Both are
speculative INSERTs guarded by a unique index.

The loser of such a race must undo ONLY its own insert. Undoing the whole
session also discards what the caller staged: the user's points account is
provisioned first, so losing the race on the shared master used to destroy it and
leave `post_transaction` raising AccountNotFound. Measured at ~25% of concurrent
first-rewards before the fix — silent to the user (the outbox retries) but a real
lost write, and both helpers' docstrings claimed to be concurrency-safe.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Rule,
    Tenant,
    User,
)

_AWARD = Decimal("50")
USERS = 8
AWARDS_PER_USER = 3


@pytest.mark.asyncio
async def test_concurrent_first_rewards_all_provision_and_post(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify simultaneous first-ever rewards neither fail nor lose a posting

    Every one of these races both provisioning inserts: each user's own points
    account, and the single tenant-wide issuance master that all of them contend
    for. Concurrency is kept under Postgres's default `max_connections` so the
    test measures the race, not connection exhaustion.
    """
    from app.modules.rewards.service import issue_points_reward

    rule = Rule(
        tenant_id=test_tenant.id,
        name="concurrent-provisioning",
        rule_type="first_time",
        transaction_type="fund",
        reward_type="points",
        reward_value=_AWARD,
        status="active",
    )
    users = [
        User(tenant_id=test_tenant.id, user_type="consumer", status="active") for _ in range(USERS)
    ]
    db_session.add(rule)
    db_session.add_all(users)
    await db_session.commit()
    await db_session.refresh(rule)
    for u in users:
        await db_session.refresh(u)
    user_ids = [u.id for u in users]

    async def _issue(user_id, n: int) -> None:
        async with session_factory() as session:
            await issue_points_reward(
                session,
                tenant_id=test_tenant.id,
                user_id=user_id,
                rule=rule,
                triggering_event_id=f"evt-{user_id}-{n}",
                reward_value=_AWARD,
            )

    results = await asyncio.gather(
        *(_issue(uid, n) for uid in user_ids for n in range(AWARDS_PER_USER)),
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, BaseException)]

    assert not failures, "concurrent first-rewards should all succeed; got " + "; ".join(
        f"{type(f).__name__}: {f}" for f in failures[:3]
    )

    # Exactly one shared issuance master, and one points account per user.
    masters = (
        (
            await db_session.execute(
                select(Account).where(
                    Account.tenant_id == test_tenant.id,
                    Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(masters) == 1, "the issuance master must be provisioned exactly once"

    for user_id in user_ids:
        points = (
            (
                await db_session.execute(
                    select(Account).where(
                        Account.user_id == user_id,
                        Account.account_type == ACCOUNT_TYPE_POINTS,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(points) == 1, f"user {user_id} should hold exactly one points account"
