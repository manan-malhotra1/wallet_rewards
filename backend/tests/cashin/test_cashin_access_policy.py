"""Per-service access policy wired into the cash-in money path.

Proves that `cash_in` enforces the tenant's `services` access policy for the
acting agent's user_type on the `mobile` channel — the API rejects exactly what
the mobile app would hide. The negative case drives the wiring at the service
layer (the gate runs BEFORE customer resolution / any ledger work); the positive
case proves an allowed agent still transacts end-to-end with the policy present.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cashin.schemas import CashInRequest, CustomerIdentifier
from app.modules.cashin.service import cash_in
from app.shared.exceptions import ServiceNotAllowedForUserType
from app.shared.models import (
    USER_TYPE_CONSUMER,
    Account,
    Role,
    RolePermission,
    Service,
    Tenant,
    User,
    UserRole,
)
from tests.cashin.conftest import cash_in_body, cash_in_headers


async def _restrict_cash_in_to_agents(session: AsyncSession, tenant: Tenant) -> None:
    """Add a live cash_in service row limited to agents on mobile."""
    session.add(
        Service(
            tenant_id=tenant.id,
            code="cash_in",
            display_name="Cash In",
            allowed_user_types=["agent", "super_agent"],
            allowed_channels=["mobile"],
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_consumer_cannot_cash_in_when_reserved_for_agents(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a consumer is refused cash-in when the service is reserved for agents"""
    await _restrict_cash_in_to_agents(db_session, test_tenant)

    # A consumer who (wrongly) holds the cash_in role — the role check would pass,
    # so the per-service access policy is what must stop them.
    role = Role(tenant_id=test_tenant.id, name="consumer_with_cashin")
    db_session.add(role)
    await db_session.flush()
    db_session.add(RolePermission(role_id=role.id, transaction_type="cash_in", permitted=True))
    consumer = User(tenant_id=test_tenant.id, user_type=USER_TYPE_CONSUMER)
    db_session.add(consumer)
    await db_session.flush()
    db_session.add(UserRole(user_id=consumer.id, role_id=role.id))
    await db_session.commit()

    with pytest.raises(ServiceNotAllowedForUserType) as exc:
        await cash_in(
            db_session,
            tenant_id=test_tenant.id,
            agent_user_id=consumer.id,
            request=CashInRequest(
                customer=CustomerIdentifier(
                    identifier_type="phone", identifier_value="+27 82 555 0000"
                ),
                amount=Decimal("10"),
                currency="ZAR",
            ),
            idempotency_key="cashin-consumer-denied",
        )
    assert exc.value.error_code == "service_not_allowed_user_type"


@pytest.mark.asyncio
async def test_agent_cash_in_still_allowed_with_agent_policy_present(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    agent_float: Account,
    customer_wallet: Account,
    worked_example_configs: None,
    agent_auth_header: dict[str, str],
) -> None:
    """Verify an agent still cashes in end-to-end when the agent-only policy is set"""
    await _restrict_cash_in_to_agents(db_session, test_tenant)

    resp = await async_client.post(
        "/api/v1/cashin",
        content=json.dumps(cash_in_body(amount="100")),
        headers=cash_in_headers(agent_auth_header),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "COMPLETED"
