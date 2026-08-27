"""A commission-wallet destination is only configurable where it can exist (D7).

Three ways a rule could name a destination with no wallet behind it: tenant flag
off, a catch-all (NULL) user_type that could match a consumer, or a
consumer-category type. All three are refused AT CONFIG WRITE, so the payout
path never has to resolve an impossible rule.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import create_commission_config
from app.shared.exceptions import CommissionDestinationNotAvailable
from app.shared.models import Tenant


def _request(tenant_id: UUID, **overrides: Any) -> CommissionConfigCreateRequest:
    """A commission-wallet-destined rule for an agent, overridable per test."""
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "transaction_type": "cash_in",
        "currency": "ZAR",
        "user_type": "agent",
        "fixed_commission": Decimal("1"),
        "variable_commission_pct": Decimal("0.01"),
        "payout_destination": "commission_wallet",
        # Required since D8 — these tests are about the DESTINATION rule, so
        # the parent leg is explicitly zero rather than absent.
        "parent_fixed_commission": Decimal("0"),
        "parent_variable_commission_pct": Decimal("0"),
    }
    payload.update(overrides)
    return CommissionConfigCreateRequest(**payload)


@pytest.mark.asyncio
async def test_refused_when_tenant_flag_is_off(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """No commission wallets exist on this tenant, so the rule is unpayable."""
    test_tenant.commission_wallet_enabled = False
    await db_session.commit()

    with pytest.raises(CommissionDestinationNotAvailable):
        await create_commission_config(db_session, _request(test_tenant.id))


@pytest.mark.asyncio
async def test_refused_for_a_catch_all_band(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A NULL user_type could match a consumer, who never has the wallet."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()

    with pytest.raises(CommissionDestinationNotAvailable):
        await create_commission_config(
            db_session, _request(test_tenant.id, user_type=None)
        )


@pytest.mark.asyncio
async def test_refused_for_a_consumer_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Consumers never hold a commission wallet (D4)."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()

    with pytest.raises(CommissionDestinationNotAvailable):
        await create_commission_config(
            db_session, _request(test_tenant.id, user_type="consumer")
        )


@pytest.mark.asyncio
async def test_allowed_for_a_retail_type_on_a_flag_on_tenant(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """The one combination that can actually pay."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()

    config = await create_commission_config(db_session, _request(test_tenant.id))
    assert config.payout_destination == "commission_wallet"


@pytest.mark.asyncio
async def test_allowed_for_a_business_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Business category is eligible too, not only Retail."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()

    config = await create_commission_config(
        db_session, _request(test_tenant.id, user_type="merchant")
    )
    assert config.payout_destination == "commission_wallet"


@pytest.mark.asyncio
async def test_main_wallet_destination_is_always_allowed(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A catch-all main-wallet rule stays legal — today's behaviour is untouched."""
    test_tenant.commission_wallet_enabled = False
    await db_session.commit()

    config = await create_commission_config(
        db_session,
        _request(test_tenant.id, user_type=None, payout_destination="main_wallet"),
    )
    assert config.payout_destination == "main_wallet"


@pytest.mark.asyncio
async def test_parent_cap_without_a_parent_rate_is_rejected(
    test_tenant: Tenant,
) -> None:
    """A cap on a zero rate is a config the operator got wrong."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        _request(
            test_tenant.id,
            payout_destination="main_wallet",
            parent_variable_commission_pct=Decimal("0"),
            parent_commission_cap=Decimal("10"),
        )
