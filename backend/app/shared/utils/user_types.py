"""Resolve a user's user_type for type-aware pricing + limits (Epics 15/16).

The limits and pricing engines key their configs on the caller's user_type: an
exact-type config beats the `user_type IS NULL` default. This helper turns a
user_id into that type with one indexed lookup.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import USER_TYPE_CONSUMER, User

# Key under which the per-session memo lives in `Session.info` — SQLAlchemy's
# user-owned namespace, scoped to exactly one session and discarded with it.
_MEMO_KEY = "user_type_memo"


async def resolve_user_type(session: AsyncSession, tenant_id: UUID, user_id: UUID) -> str:
    """Return the user's user_type, or 'consumer' when the user is unknown.

    Memoised for the life of the session, which is one request (the
    `get_async_session` dependency opens a session per request). A single money
    move asks for the same user's type from every gate it walks — service
    resolution, permissions, pricing, and each limit window — which measured as
    seven identical round trips on one P2P transfer.

    Reusing one answer is also the more correct reading: every gate in a request
    should judge the SAME user_type. Re-reading per gate leaves a window where an
    admin retypes the user mid-request and pricing applies one type while limits
    apply another.

    Callers that CHANGE a user's type in an open session must call
    `invalidate_user_type` so a later read in that same session is not stale.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — the lookup is tenant-isolated.
        user_id: The acting user whose type drives config precedence.

    Returns:
        One of the five user types; falls back to `consumer` (the safe default,
        which also matches the NULL-default config row) if no user is found.
    """
    memo: dict[tuple[UUID, UUID], str] = session.info.setdefault(_MEMO_KEY, {})
    key = (tenant_id, user_id)
    if key in memo:
        return memo[key]

    result = await session.execute(
        select(User.user_type).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user_type = result.scalar_one_or_none() or USER_TYPE_CONSUMER
    memo[key] = user_type
    return user_type


def invalidate_user_type(session: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
    """Drop a memoised user_type after changing it in this session.

    Keeps `resolve_user_type` honest for code that retypes a user and then reads
    the type back on the same session. A no-op when nothing was memoised.
    """
    memo: dict[tuple[UUID, UUID], str] | None = session.info.get(_MEMO_KEY)
    if memo is not None:
        memo.pop((tenant_id, user_id), None)
