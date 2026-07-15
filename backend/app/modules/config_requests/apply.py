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


# Config types whose create payload may carry MULTIPLE amount bands (Epic 25).
# A pricing/commission schedule is several bands, created + approved as a unit.
MULTI_BAND_TYPES = {CONFIG_TYPE_PRICING, CONFIG_TYPE_COMMISSION}


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


def validate_band_payload(config_type: str, payload: dict[str, Any]) -> list[BaseModel]:
    """Validate a create payload — a multi-band `{"bands":[...]}` or a single dict.

    For pricing/commission a `{"bands": [row, ...]}` payload is a schedule: every
    row is validated against the create schema, all rows must share the same
    scope (service/account/currency/user_type), and the bands must be ascending
    and non-overlapping (only the last may be open-ended). A plain dict (or any
    non-multi-band type) is treated as a single band — preserving legacy payloads.

    Returns:
        The validated create-schema models, one per band.

    Raises:
        AppHTTPException (422): empty set, malformed row, mismatched scope, or
            overlapping / mis-ordered bands.
    """
    if config_type in MULTI_BAND_TYPES and isinstance(payload.get("bands"), list):
        rows = payload["bands"]
    else:
        rows = [payload]
    if not rows:
        raise AppHTTPException(
            422, "config_request_invalid_payload", "At least one band is required."
        )
    models = [build_create_schema(config_type, row) for row in rows]
    # Band-set rules only apply to the band-bearing types; limit/wallet_limit/tax
    # are always a single row and lack the transaction_type/amount_from fields.
    if config_type in MULTI_BAND_TYPES:
        _assert_shared_scope(models)
        _assert_bands_ordered(models)
    return models


def _assert_shared_scope(models: list[BaseModel]) -> None:
    """All bands must share their scope keys.

    `account_type` only exists on pricing rows (commission is keyed without it),
    so read it defensively — a commission schedule shares service/currency/type.
    """
    scopes = {
        (
            m.transaction_type,  # type: ignore[attr-defined]
            getattr(m, "account_type", None),
            m.currency,  # type: ignore[attr-defined]
            m.user_type,  # type: ignore[attr-defined]
        )
        for m in models
    }
    if len(scopes) > 1:
        raise AppHTTPException(
            422,
            "config_request_band_scope_mismatch",
            "All bands must share the same service, currency and user type.",
        )


def _assert_bands_ordered(models: list[BaseModel]) -> None:
    """Bands must be ascending + non-overlapping; only the last may be open-ended."""
    bands = sorted(
        models,
        key=lambda m: (m.amount_from is None, m.amount_from or 0),  # type: ignore[attr-defined]
    )
    for i, band in enumerate(bands):
        frm = band.amount_from  # type: ignore[attr-defined]
        to = band.amount_to  # type: ignore[attr-defined]
        if to is not None and frm is not None and to <= frm:
            raise AppHTTPException(
                422, "config_request_band_invalid", "amount_to must exceed amount_from."
            )
        if i > 0:
            prev_to = bands[i - 1].amount_to  # type: ignore[attr-defined]
            # An open-ended earlier band, or a start below the previous end, overlaps.
            if prev_to is None or (frm is not None and frm < prev_to):
                raise AppHTTPException(
                    422, "config_request_band_overlap", "Bands must not overlap."
                )


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
    _schema_cls, create_fn, delete_fn = _DISPATCH[request.config_type]
    if request.operation == CONFIG_OP_CREATE:
        # A create may be a multi-band schedule — apply every band in this same
        # transaction so approval is all-or-none (a failure rolls back all rows
        # plus the request→APPLIED transition the caller staged).
        for schema in validate_band_payload(request.config_type, request.payload or {}):
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
