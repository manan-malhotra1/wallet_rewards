"""The user-operations list endpoint must run O(1) queries per page (B7.2).

Before batching, the list handler ran per-row queries (review thread, target
user-name resolution), so a page's DB cost scaled with its row count. These
tests pin the contract: the number of SQL statements a list call issues is
IDENTICAL for a small and a larger page.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from app.shared.models import Tenant, User
from tests.conftest import test_engine
from tests.user_operations.conftest import ops_url, propose


async def _query_count(action: Callable[[], Awaitable[None]]) -> int:
    """Count SQL statements executed on the test engine while `action` runs."""
    counter = {"n": 0}

    def _on_execute(*args: object, **kwargs: object) -> None:
        counter["n"] += 1

    event.listen(test_engine.sync_engine, "before_cursor_execute", _on_execute)
    try:
        await action()
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _on_execute)
    return counter["n"]


async def _propose_updates(
    client: AsyncClient,
    tenant: Tenant,
    user: User,
    maker_header: dict[str, str],
    count: int,
) -> None:
    """Propose `count` update_user operations targeting the same seeded user."""
    for i in range(count):
        await propose(
            client,
            tenant,
            maker_header,
            "update_user",
            {"target_user_id": str(user.id), "first_name": f"Ada{i}"},
        )


@pytest.mark.asyncio
async def test_list_query_count_is_independent_of_page_size(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
) -> None:
    """Verify listing 6 rows issues exactly as many queries as listing 2."""

    async def _list() -> None:
        resp = await async_client.get(ops_url(test_tenant), headers=maker_header)
        assert resp.status_code == 200

    await _propose_updates(async_client, test_tenant, test_user, maker_header, 2)
    queries_small = await _query_count(_list)

    await _propose_updates(async_client, test_tenant, test_user, maker_header, 4)
    queries_large = await _query_count(_list)

    assert queries_large == queries_small, (
        f"list queries scale with rows: {queries_small} for 2 rows, "
        f"{queries_large} for 6 rows"
    )


@pytest.mark.asyncio
async def test_list_still_resolves_target_names_after_batching(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
) -> None:
    """Verify the batched enrichment still resolves the edited user's name."""
    await _propose_updates(async_client, test_tenant, test_user, maker_header, 2)
    resp = await async_client.get(ops_url(test_tenant), headers=maker_header)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert all(op["target_name"] for op in body)
