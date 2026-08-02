"""Per-service access policy wired into the P2P money path.

Proves that `p2p_transfer` enforces the tenant's `services` access policy for the
sender's user_type on the `mobile` channel. The negative case drives the wiring
at the service layer (the gate runs BEFORE recipient resolution / any ledger
work); the positive case proves an allowed consumer still transfers end-to-end
with the consumer-only policy present.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.service import fund, p2p_transfer
from app.shared.exceptions import ServiceNotAllowedForUserType
from app.shared.models import (
    USER_TYPE_AGENT,
    Role,
    RolePermission,
    Service,
    Tenant,
    User,
    UserRole,
)
from tests.payments.test_p2p import (
    _auth_header_for,
    _make_user_with_wallet,
    _seed_p2p_config,
)


async def _restrict_p2p_to_consumers(session: AsyncSession, tenant: Tenant) -> None:
    """Add a live p2p service row limited to consumers on mobile."""
    session.add(
        Service(
            tenant_id=tenant.id,
            code="p2p",
            display_name="Send Money",
            allowed_user_types=["consumer"],
            allowed_channels=["mobile"],
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_agent_cannot_p2p_when_reserved_for_consumers(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify an agent is refused P2P when the service is reserved for consumers"""
    await _restrict_p2p_to_consumers(db_session, test_tenant)

    # An agent who holds the p2p role — the role check passes, so the per-service
    # access policy is what must stop them.
    role = Role(tenant_id=test_tenant.id, name="agent_with_p2p")
    db_session.add(role)
    await db_session.flush()
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p", permitted=True))
    agent = User(tenant_id=test_tenant.id, user_type=USER_TYPE_AGENT)
    db_session.add(agent)
    await db_session.flush()
    db_session.add(UserRole(user_id=agent.id, role_id=role.id))
    await db_session.commit()

    with pytest.raises(ServiceNotAllowedForUserType) as exc:
        await p2p_transfer(
            db_session,
            tenant_id=test_tenant.id,
            sender_user_id=agent.id,
            recipient_identifier_type="phone",
            recipient_identifier_value="+27 82 555 0001",
            amount=Decimal("10"),
            currency="ZAR",
            idempotency_key="p2p-agent-denied",
        )
    assert exc.value.error_code == "service_not_allowed_user_type"


@pytest.mark.asyncio
async def test_consumer_p2p_still_allowed_with_consumer_policy_present(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify a consumer still transfers end-to-end when the consumer-only policy is set"""
    await _restrict_p2p_to_consumers(db_session, test_tenant)
    await _seed_p2p_config(db_session, test_tenant.id)
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 9001")
    bob, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 9002")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key=f"seed-{uuid4().hex}",
    )

    alice_auth = await _auth_header_for(alice)
    resp = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 9002"},
            "amount": "50",
            "currency": "ZAR",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["recipient_user_id"] == str(bob.id)
