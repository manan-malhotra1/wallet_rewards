"""Apply an approved config-change request to its real config table.

Pricing v2 Epic 22. One dispatch per config type maps to that type's existing
create/delete service (which stages the row, writes its own audit, and commits).
Because the caller stages the request's status change BEFORE calling `apply`,
the config write and the request→APPLIED transition land in the SAME commit —
so a collision (409) rolls both back and the request stays actionable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import (
    create_commission_config,
    delete_commission_config,
)
from app.modules.limits.schemas import (
    LimitConfigCreateRequest,
    WalletLimitConfigCreateRequest,
)
from app.modules.limits.service import (
    create_limit_config,
    create_wallet_limit_config,
    delete_limit_config,
    delete_wallet_limit_config,
)
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config, delete_pricing_config
from app.modules.taxes.schemas import TaxConfigCreateRequest
from app.modules.taxes.service import create_tax_config, delete_tax_config
from app.shared.exceptions import AppHTTPException
from app.shared.models import (
    CONFIG_OP_CREATE,
    CONFIG_TYPE_COMMISSION,
    CONFIG_TYPE_LIMIT,
    CONFIG_TYPE_PRICING,
    CONFIG_TYPE_TAX,
    CONFIG_TYPE_WALLET_LIMIT,
    ConfigChangeRequest,
)

# A create needs the schema to parse the payload + the create fn; a delete needs
# the delete fn. `_CreateFn` and `_DeleteFn` mirror every config service's shape.
_CreateFn = Callable[..., Awaitable[object]]
_DeleteFn = Callable[..., Awaitable[None]]

# config_type -> (create-request schema, create fn, delete fn).
_DISPATCH: dict[str, tuple[type[BaseModel], _CreateFn, _DeleteFn]] = {
    CONFIG_TYPE_PRICING: (
        PricingConfigCreateRequest,
        create_pricing_config,
        delete_pricing_config,
    ),
    CONFIG_TYPE_LIMIT: (LimitConfigCreateRequest, create_limit_config, delete_limit_config),
    CONFIG_TYPE_WALLET_LIMIT: (
        WalletLimitConfigCreateRequest,
        create_wallet_limit_config,
        delete_wallet_limit_config,
    ),
    CONFIG_TYPE_COMMISSION: (
        CommissionConfigCreateRequest,
        create_commission_config,
        delete_commission_config,
    ),
    CONFIG_TYPE_TAX: (TaxConfigCreateRequest, create_tax_config, delete_tax_config),
}


def build_create_schema(config_type: str, payload: dict[str, Any]) -> BaseModel:
    """Validate a proposal payload against its config type's create schema.

    Used both at propose time (fail fast on a malformed payload) and at apply.

    Raises:
        AppHTTPException (422): the payload doesn't match the create schema.
    """
    schema_cls, _, _ = _DISPATCH[config_type]
    try:
        return schema_cls.model_validate(payload)
    except ValueError as exc:
        raise AppHTTPException(
            422,
            "config_request_invalid_payload",
            f"Payload is not a valid {config_type} config: {exc}",
        ) from exc


async def apply_config_request(
    session: AsyncSession,
    request: ConfigChangeRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> None:
    """Write the approved create/delete to the real config table.

    Delegates to the config type's own create/delete service, which commits —
    persisting the request mutations the caller staged beforehand in the SAME
    transaction. The underlying service also writes its own `*_config.created` /
    `.deleted` audit row.

    Raises:
        AppHTTPException (409/404/422): propagated from the underlying service
            (e.g. unique collision, missing delete target, bad payload).
    """
    schema_cls, create_fn, delete_fn = _DISPATCH[request.config_type]
    if request.operation == CONFIG_OP_CREATE:
        schema = schema_cls.model_validate(request.payload or {})
        await create_fn(session, schema, admin=admin, ip_address=ip_address)
    else:
        # delete — target_config_id is guaranteed set by the propose validation.
        assert request.target_config_id is not None
        await delete_fn(
            session,
            request.target_config_id,
            request.tenant_id,
            admin=admin,
            ip_address=ip_address,
        )
