"""Model-level guards for the base/derived service columns.

The CHECK constraints are the reason `base_service_code IS NULL` never has to
be interpreted — these tests prove the invalid combinations are unrepresentable.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Service, Tenant


@pytest.mark.asyncio
async def test_base_service_persists_without_a_base_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a base service is stored with kind='base' and no base code"""
    db_session.add(Service(tenant_id=test_tenant.id, code="p2p", display_name="P2P", kind="base"))
    await db_session.flush()


@pytest.mark.asyncio
async def test_derived_service_requires_a_base_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify kind='derived' without a base code violates the pairing CHECK"""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Service(
                    tenant_id=test_tenant.id,
                    code="p2p_diaspora",
                    display_name="Diaspora P2P",
                    kind="derived",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_base_service_rejects_a_base_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify kind='base' carrying a base code violates the pairing CHECK"""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Service(
                    tenant_id=test_tenant.id,
                    code="p2p",
                    display_name="P2P",
                    kind="base",
                    base_service_code="cashout",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_service_cannot_be_its_own_base(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a self-referencing base code is rejected"""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Service(
                    tenant_id=test_tenant.id,
                    code="p2p",
                    display_name="P2P",
                    kind="derived",
                    base_service_code="p2p",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a kind outside base/derived violates the enum CHECK"""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Service(
                    tenant_id=test_tenant.id,
                    code="p2p",
                    display_name="P2P",
                    kind="variant",
                )
            )
            await db_session.flush()
