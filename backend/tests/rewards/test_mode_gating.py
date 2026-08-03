"""Deployment-mode gating: business_type drives reward behavior."""
from uuid import uuid4

import pytest

from app.shared.models.tenants import BUSINESS_TYPE_BOTH
from app.shared.tenant_mode import business_type_of, rewards_from_wallet_enabled


@pytest.mark.asyncio
async def test_business_type_of_returns_stored_mode(db_session, tenant_factory):
    """Verify a stored deployment mode reads back and 'both' enables wallet-driven rewards."""
    tenant = await tenant_factory(business_type=BUSINESS_TYPE_BOTH)
    assert await business_type_of(db_session, tenant.id) == BUSINESS_TYPE_BOTH
    assert await rewards_from_wallet_enabled(db_session, tenant.id) is True


@pytest.mark.asyncio
async def test_wallet_mode_gate_is_non_raising_for_unknown_tenant(db_session):
    """Verify an unresolved tenant never 500s a money movement — the gate returns False."""
    # On the post_transaction hot path a missing tenant must degrade to
    # "no reward trigger" (False), NOT raise — unlike business_type_of.
    assert await rewards_from_wallet_enabled(db_session, uuid4()) is False
