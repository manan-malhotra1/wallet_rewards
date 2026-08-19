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
from sqlalchemy import ColumnElement, Select, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AdminProfile


class QueueCountsOut(BaseModel):
    """A queue's row total plus a count per lifecycle status.

    `by_status` always carries every known status (zero-filled), so clients can
    render fixed status segments without null checks.
    """

    total: int
    by_status: dict[str, int]


def _escape_like(q: str) -> str:
    """Escape ILIKE metacharacters so `q` always matches literally."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_needle(q: str) -> str:
    """The escaped `%…%` ILIKE pattern for `q` (use with `escape="\\"`).

    For queue-specific extra search conditions (e.g. a subject-name EXISTS)
    that must match exactly like `queue_search_condition` does.
    """
    return f"%{_escape_like(q)}%"


def queue_search_condition(
    model: Any,
    q: str,
    extra_text_columns: Sequence[Any] = (),
    extra_conditions: Sequence[Any] = (),
) -> ColumnElement[bool]:
    """Build the WHERE clause for a free-text queue search (B7.2c).

    Case-insensitive substring match over: the request id (partial UUIDs
    work), the maker's admin sub, the maker's recorded display name
    (admin_profiles), the stored payload text (identifiers, amounts, names),
    any queue-specific text columns (e.g. `operation`, `config_type`), and any
    prebuilt queue-specific conditions (e.g. a subject-name EXISTS, built with
    `search_needle`). Searching the WHOLE queue this way is what lets the
    approvals page's search escape its fetched window.
    """
    needle = search_needle(q)
    maker_name_matches = (
        select(AdminProfile.id)
        .where(
            AdminProfile.keycloak_sub == model.maker_admin_id,
            AdminProfile.display_name.ilike(needle, escape="\\"),
        )
        .exists()
    )
    return or_(
        cast(model.id, String).ilike(needle, escape="\\"),
        model.maker_admin_id.ilike(needle, escape="\\"),
        cast(model.payload, String).ilike(needle, escape="\\"),
        maker_name_matches,
        *[column.ilike(needle, escape="\\") for column in extra_text_columns],
        *extra_conditions,
    )


async def count_queue_by_status(
    session: AsyncSession,
    model: Any,
    tenant_id: UUID,
    statuses: Sequence[str],
    *,
    q: str | None = None,
    extra_text_columns: Sequence[Any] = (),
    extra_conditions: Sequence[Any] = (),
) -> QueueCountsOut:
    """Count a tenant's queue rows per status in ONE grouped query.

    Args:
        model: The queue's ORM class; must have `tenant_id` and `status` columns
            (MoneyOperationRequest, ConfigChangeRequest, UserOperationRequest).
        statuses: The queue's full lifecycle status tuple; every entry appears
            in the result, zero-filled when absent from the DB.
        q: Optional free-text search — counts then cover only matching rows,
            so a searching page's pager and segments stay truthful.
        extra_text_columns: Queue-specific text columns q also matches.
        extra_conditions: Prebuilt queue-specific search conditions q also
            matches (see `queue_search_condition`).

    Returns:
        QueueCountsOut with the tenant's total and the per-status breakdown.
    """
    stmt = select(model.status, func.count()).where(model.tenant_id == tenant_id)
    if q:
        stmt = stmt.where(
            queue_search_condition(model, q, extra_text_columns, extra_conditions)
        )
    result = await session.execute(stmt.group_by(model.status))
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
