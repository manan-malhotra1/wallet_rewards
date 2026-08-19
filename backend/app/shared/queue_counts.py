"""Shared queue-window mechanics for the maker-checker queues (Story B7.1).

The unified approvals page needs each queue's total and per-status counts for
its tab bar and status segments WITHOUT fetching any rows, plus a bounded
newest-first window of the rows themselves. All three queues (config_requests,
money_operations, user_operations) share one lifecycle shape, so the grouped
count query, its response schema, and the window ordering live here once.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class QueueCountsOut(BaseModel):
    """A queue's row total plus a count per lifecycle status.

    `by_status` always carries every known status (zero-filled), so clients can
    render fixed status segments without null checks.
    """

    total: int
    by_status: dict[str, int]


async def count_queue_by_status(
    session: AsyncSession,
    model: Any,
    tenant_id: UUID,
    statuses: Sequence[str],
) -> QueueCountsOut:
    """Count a tenant's queue rows per status in ONE grouped query.

    Args:
        model: The queue's ORM class; must have `tenant_id` and `status` columns
            (MoneyOperationRequest, ConfigChangeRequest, UserOperationRequest).
        statuses: The queue's full lifecycle status tuple; every entry appears
            in the result, zero-filled when absent from the DB.

    Returns:
        QueueCountsOut with the tenant's total and the per-status breakdown.
    """
    result = await session.execute(
        select(model.status, func.count())
        .where(model.tenant_id == tenant_id)
        .group_by(model.status)
    )
    found: dict[str, int] = {row[0]: row[1] for row in result.all()}
    by_status = {status: found.get(status, 0) for status in statuses}
    return QueueCountsOut(total=sum(found.values()), by_status=by_status)


def apply_newest_first_window(
    stmt: Select[Any], model: Any, *, limit: int | None, offset: int
) -> Select[Any]:
    """Order a queue query newest-first and apply the limit/offset window.

    The ordering tie-breaks on id so a fixed window never duplicates or drops
    rows created in the same instant. One definition for all three queues, so
    the pagination contract cannot drift between them.

    Args:
        model: The queue's ORM class; must have `created_at` and `id` columns.
        limit: Maximum rows to return; None means unbounded (existing callers).
        offset: Rows to skip before the window starts.
    """
    return (
        stmt.order_by(model.created_at.desc(), model.id.desc()).offset(offset).limit(limit)
    )
