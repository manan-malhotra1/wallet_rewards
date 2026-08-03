"""Deployment-mode gating: business_type drives reward behavior."""
import pytest

from app.shared.models.tenants import BUSINESS_TYPE_BOTH
from app.shared.tenant_mode import business_type_of, rewards_from_wallet_enabled


@pytest.mark.asyncio
async def test_business_type_of_returns_stored_mode(db_session, tenant_factory):
    """Verify a stored deployment mode reads back and 'both' enables wallet-driven rewards."""
    tenant = await tenant_factory(business_type=BUSINESS_TYPE_BOTH)
    assert await business_type_of(db_session, tenant.id) == BUSINESS_TYPE_BOTH
    assert await rewards_from_wallet_enabled(db_session, tenant.id) is True
