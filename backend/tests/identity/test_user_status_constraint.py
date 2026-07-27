"""Customer status values — which account states are allowed.

`ck_users_status` gained a fourth value, `txn_locked`. This verifies the DB
accepts the four valid statuses and rejects anything else — the structural
guard behind the admin access-lock.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_CLOSED,
    USER_STATUS_SUSPENDED,
    USER_STATUS_TXN_LOCKED,
    Tenant,
    User,
)


@pytest.mark.parametrize(
    "status",
    [
        USER_STATUS_ACTIVE,
        USER_STATUS_SUSPENDED,
        USER_STATUS_CLOSED,
        USER_STATUS_TXN_LOCKED,
    ],
)
@pytest.mark.asyncio
async def test_valid_status_is_accepted(
    db_session: AsyncSession, test_tenant: Tenant, status: str
) -> None:
    """Verify every allowed customer status can be saved"""
    user = User(tenant_id=test_tenant.id, status=status)
    db_session.add(user)
    await db_session.commit()
    assert user.status == status


@pytest.mark.asyncio
async def test_unknown_status_is_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify an invalid customer status cannot be saved"""
    db_session.add(User(tenant_id=test_tenant.id, status="frozen"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
