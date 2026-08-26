"""Commission wallet eligibility is a CATEGORY question (spec D4).

Never a hardcoded type list: an operator-created Business type must become
eligible with no code change. Retired types stay eligible, because an agent
onboarded under a since-retired type must keep accruing.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import Tenant


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("agent", True),
        ("super_agent", True),
        ("merchant", True),
        ("head_merchant", True),
        ("consumer", False),
    ],
)
@pytest.mark.asyncio
async def test_eligibility_by_seeded_type(
    db_session: AsyncSession, test_tenant: Tenant, code: str, expected: bool
) -> None:
    """Retail and Business are eligible; the Consumer category never is."""
    assert (
        await is_commission_wallet_eligible(db_session, test_tenant.id, code) is expected
    )


@pytest.mark.asyncio
async def test_unknown_type_is_not_eligible(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Never raise on an unresolvable type — provisioning must not 500."""
    assert (
        await is_commission_wallet_eligible(db_session, test_tenant.id, "nope") is False
    )


@pytest.mark.asyncio
async def test_operator_created_business_type_is_eligible(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """The whole point of reading the category: no code change for a new type."""
    from app.shared.models import UserTypeDef

    db_session.add(
        UserTypeDef(
            tenant_id=test_tenant.id,
            code="franchisee",
            label="Franchisee",
            category_code="business",
            is_system=False,
            status="active",
        )
    )
    await db_session.commit()

    assert (
        await is_commission_wallet_eligible(db_session, test_tenant.id, "franchisee")
        is True
    )
