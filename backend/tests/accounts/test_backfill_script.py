"""The retrofit script provisions eligible users and is safe to re-run (spec §6.4).

Because the tenant flag is immutable, this script is the ONLY path by which an
existing tenant adopts commission wallets — so its guards matter.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Instrument,
    Tenant,
    User,
)

# `scripts/` lives at the REPO root, one level above this backend package, so it
# is not on the path pytest builds from `rootdir`. The insert must precede the
# import, hence the noqa — the same pattern the scripts themselves use to reach
# `app`.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.backfill_commission_wallets import backfill_tenant  # noqa: E402


async def _flag_on_with_zar(session: AsyncSession, tenant: Tenant) -> None:
    """Turn the commission flag on and guarantee a live ZAR instrument."""
    tenant.commission_wallet_enabled = True
    existing = (
        await session.execute(
            select(Instrument).where(
                Instrument.tenant_id == tenant.id, Instrument.code == "ZAR"
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Instrument(
                tenant_id=tenant.id,
                code="ZAR",
                symbol="R",
                display_name="Rand",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_backfill_provisions_and_is_idempotent(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """First run creates the wallet; a second run is a no-op."""
    await _flag_on_with_zar(db_session, test_tenant)
    test_user.user_type = "agent"
    await db_session.commit()

    first = await backfill_tenant(db_session, test_tenant.id)
    await db_session.commit()
    second = await backfill_tenant(db_session, test_tenant.id)
    await db_session.commit()

    assert first > 0
    assert second == 0

    rows = (
        await db_session.execute(
            select(Account).where(
                Account.user_id == test_user.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_backfill_refuses_a_flag_off_tenant(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """The script provisions; it does not silently enable the feature."""
    test_tenant.commission_wallet_enabled = False
    test_user.user_type = "agent"
    await db_session.commit()

    with pytest.raises(ValueError, match="commission_wallet_enabled"):
        await backfill_tenant(db_session, test_tenant.id)


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """A dry run reports the count without creating rows."""
    await _flag_on_with_zar(db_session, test_tenant)
    test_user.user_type = "agent"
    await db_session.commit()

    planned = await backfill_tenant(db_session, test_tenant.id, apply=False)
    assert planned > 0

    rows = (
        await db_session.execute(
            select(Account).where(
                Account.user_id == test_user.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalars().all()
    assert rows == []
