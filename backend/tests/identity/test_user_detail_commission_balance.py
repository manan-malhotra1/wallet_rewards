"""Admin user detail separates accrued commission from spendable balance (spec §10).

The account list already enumerates every type generically, so the wallet shows
up for free. What must NOT happen is it being counted as spendable.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.service import get_user_detail
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
)


@pytest.mark.asyncio
async def test_commission_balance_is_reported_and_not_spendable(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Both wallets are listed; only the main one counts toward spendable."""
    for account_type in (ACCOUNT_TYPE_FINANCIAL_WALLET, ACCOUNT_TYPE_COMMISSION_WALLET):
        db_session.add(
            Account(
                tenant_id=test_tenant.id,
                user_id=test_user.id,
                account_type=account_type,
                currency="ZAR",
            )
        )
    await db_session.commit()

    detail = await get_user_detail(
        db_session, user_id=test_user.id, tenant_id=test_tenant.id
    )

    by_type = {a["account_type"]: a for a in detail["accounts"]}
    assert ACCOUNT_TYPE_COMMISSION_WALLET in by_type
    assert by_type[ACCOUNT_TYPE_COMMISSION_WALLET]["spendable"] is False
    assert by_type[ACCOUNT_TYPE_FINANCIAL_WALLET]["spendable"] is True
    assert detail["spendable_total"]["ZAR"] == "0"
