"""Shared fixtures for treasury endpoint tests (Epic 18).

The treasury money-moving endpoints now PROPOSE a money operation instead of
executing directly, so these tests drive the proposal to execution via the
money-operations approval endpoint. `approver_header` is a treasury-approver
distinct from the default `admin_auth_header` maker (sub differs), satisfying the
distinct-approver rule.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient, Response

# Re-exported so the commission-wallet withdrawal tests can reuse the batch
# fixture (a flag-on tenant with a real accrued balance) rather than duplicating
# ~100 lines of setup. Fixtures are directory-scoped in pytest, so a conftest
# must bind the name for it to resolve here.
from tests.commission_batches.conftest import (  # noqa: F401
    BatchFixture,
    batch_fixture,
    maker_admin,
)

# A treasury-approver whose sub differs from admin_auth_header's default maker
# sub (00000000-0000-4000-8000-000000000001) so approvals are by a distinct admin.
TREASURY_APPROVER_SUB = "aaaaaaaa-aaaa-4000-8000-0000000000aa"


@pytest.fixture
def approver_header(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """A treasury-approver header distinct from the default maker."""
    token = make_admin_token(roles=["treasury-approver"], sub=TREASURY_APPROVER_SUB)
    return {"Authorization": f"Bearer {token}"}


async def approve_op(
    client: AsyncClient, tenant_id: str, op_id: str, approver_header: dict[str, str]
) -> Response:
    """Approve a proposed money operation via the money-operations endpoint."""
    return await client.post(
        f"/api/v1/money-operations/{op_id}/approve?tenant_id={tenant_id}",
        headers=approver_header,
    )
