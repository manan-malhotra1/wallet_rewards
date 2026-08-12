"""Apply an approved config-change request to its real config table.

Pricing v2 Epic 22. One dispatch per config type maps to that type's existing
create/delete service (which stages the row, writes its own audit, and commits).
Because the caller stages the request's status change BEFORE calling `apply`,
the config write and the request→APPLIED transition land in the SAME commit —
so a collision (409) rolls both back and the request stays actionable.

An `update` is an ATOMIC REPLACE: a per-type `replace_*_config_for_scope` helper
deletes every existing row for the payload's scope and inserts the new row(s)
within ONE transaction (one commit at the end). Composing create+delete would
commit the delete first and break atomicity, so update never does that.

A `delete` removes the WHOLE SCOPE of the target row, not just the one band the
maker clicked: the admin UI shows one row per config (scope), so for multi-band
types (pricing/commission) approving a delete via any band id wipes every band
sharing that scope. Single-row types (limit/wallet_limit/tax) hold exactly one
row per scope — identical to the legacy single-row delete.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import (
    create_commission_config,
    delete_commission_config_for_scope,
    replace_commission_config_for_scope,
)
from app.modules.limits.schemas import (
    LimitConfigCreateRequest,
    WalletLimitConfigCreateRequest,
)
from app.modules.limits.service import (
    create_limit_config,
    create_wallet_limit_config,
    delete_limit_config_for_scope,
    delete_wallet_limit_config_for_scope,
    replace_limit_config_for_scope,
    replace_wallet_limit_config_for_scope,
)
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import (
    create_pricing_config,
    delete_pricing_config_for_scope,
    replace_pricing_config_for_scope,
)
from app.modules.step_up.schemas import StepUpPolicyCreateRequest
from app.modules.step_up.service import (
    create_policy,
    delete_step_up_policy_for_scope,
    replace_step_up_policy_for_scope,
)
from app.modules.taxes.schemas import TaxConfigCreateRequest
from app.modules.taxes.service import (
    create_tax_config,
    delete_tax_config_for_scope,
    replace_tax_config_for_scope,
)
from app.shared.exceptions import AppHTTPException, ConfigRequestTargetNotFound
from app.shared.models import (
    CONFIG_OP_CREATE,
    CONFIG_OP_UPDATE,
    CONFIG_TYPE_COMMISSION,
    CONFIG_TYPE_LIMIT,
    CONFIG_TYPE_PRICING,
    CONFIG_TYPE_STEP_UP,
    CONFIG_TYPE_TAX,
    CONFIG_TYPE_WALLET_LIMIT,
    CommissionConfig,
    ConfigChangeRequest,
    LimitConfig,
    PricingConfig,
    StepUpPolicy,
    TaxConfig,
    WalletLimitConfig,
)

# A create needs the schema to parse the payload + the create fn. `_CreateFn`
# mirrors every config service's create signature.
_CreateFn = Callable[..., Awaitable[object]]
# A replace takes the validated band set + target id, deletes the scope and
# inserts the new row(s) in one commit (see the module docstring). A delete-by-
# scope takes the loaded target row and removes its whole scope in one commit.
_ReplaceFn = Callable[..., Awaitable[None]]
_DeleteScopeFn = Callable[..., Awaitable[None]]

# config_type -> (create-request schema, create fn).
_DISPATCH: dict[str, tuple[type[BaseModel], _CreateFn]] = {
    CONFIG_TYPE_PRICING: (PricingConfigCreateRequest, create_pricing_config),
    CONFIG_TYPE_LIMIT: (LimitConfigCreateRequest, create_limit_config),
    CONFIG_TYPE_WALLET_LIMIT: (WalletLimitConfigCreateRequest, create_wallet_limit_config),
    CONFIG_TYPE_COMMISSION: (CommissionConfigCreateRequest, create_commission_config),
    CONFIG_TYPE_TAX: (TaxConfigCreateRequest, create_tax_config),
    CONFIG_TYPE_STEP_UP: (StepUpPolicyCreateRequest, create_policy),
}

# config_type -> the atomic-replace helper an `update` dispatches to.
_REPLACE_DISPATCH: dict[str, _ReplaceFn] = {
    CONFIG_TYPE_PRICING: replace_pricing_config_for_scope,
    CONFIG_TYPE_LIMIT: replace_limit_config_for_scope,
    CONFIG_TYPE_WALLET_LIMIT: replace_wallet_limit_config_for_scope,
    CONFIG_TYPE_COMMISSION: replace_commission_config_for_scope,
    CONFIG_TYPE_TAX: replace_tax_config_for_scope,
    CONFIG_TYPE_STEP_UP: replace_step_up_policy_for_scope,
}

# config_type -> the scope-delete helper a `delete` dispatches to. Each removes
# EVERY row sharing the target's scope (a whole schedule for multi-band types),
# in one commit.
_DELETE_SCOPE_DISPATCH: dict[str, _DeleteScopeFn] = {
    CONFIG_TYPE_PRICING: delete_pricing_config_for_scope,
    CONFIG_TYPE_LIMIT: delete_limit_config_for_scope,
    CONFIG_TYPE_WALLET_LIMIT: delete_wallet_limit_config_for_scope,
    CONFIG_TYPE_COMMISSION: delete_commission_config_for_scope,
    CONFIG_TYPE_TAX: delete_tax_config_for_scope,
    CONFIG_TYPE_STEP_UP: delete_step_up_policy_for_scope,
}

# config_type -> its real config-table model (for the update/delete target
# existence + scope check at propose time).
_MODEL_BY_TYPE: dict[str, type[Any]] = {
    CONFIG_TYPE_PRICING: PricingConfig,
    CONFIG_TYPE_LIMIT: LimitConfig,
    CONFIG_TYPE_WALLET_LIMIT: WalletLimitConfig,
    CONFIG_TYPE_COMMISSION: CommissionConfig,
    CONFIG_TYPE_TAX: TaxConfig,
    CONFIG_TYPE_STEP_UP: StepUpPolicy,
}

# config_type -> the attributes that identify a config's SCOPE. An update must
# not move the scope: the payload's derived scope has to equal the target row's.
# Read off both an ORM config row and a create-schema band model (same attr
# names), so one helper compares them. commission has no account_type; wallet_
# limit is keyed by (currency, user_type); tax by currency alone.
_SCOPE_KEYS: dict[str, tuple[str, ...]] = {
    CONFIG_TYPE_PRICING: ("transaction_type", "account_type", "currency", "user_type"),
    CONFIG_TYPE_LIMIT: ("transaction_type", "account_type", "currency", "user_type"),
    CONFIG_TYPE_COMMISSION: ("transaction_type", "currency", "user_type"),
    CONFIG_TYPE_WALLET_LIMIT: ("currency", "user_type"),
    CONFIG_TYPE_TAX: ("currency",),
    CONFIG_TYPE_STEP_UP: ("transaction_type", "currency"),
}


def config_scope(config_type: str, obj: object) -> tuple[object, ...]:
    """Extract a config's scope tuple from an ORM row OR a create-schema band.

    `currency` is upper-cased on both sides so the comparison is case-insensitive
    (the ORM stores it upper-cased; a raw payload may not). Other keys compare
    verbatim.
    """
    values: list[object] = []
    for key in _SCOPE_KEYS[config_type]:
        value = getattr(obj, key)
        if key == "currency" and value is not None:
            value = str(value).upper()
        values.append(value)
    return tuple(values)


async def load_config_target(
    session: AsyncSession, config_type: str, target_config_id: UUID, tenant_id: UUID
) -> Any | None:
    """Load the live config row named by `target_config_id` in this tenant, or None.

    Used at propose time to reject an update/delete whose `target_config_id`
    points at a config that isn't there (404 `config_request_target_not_found`)
    and — for update — to compare the target's scope against the payload's.
    """
    model = _MODEL_BY_TYPE[config_type]
    result = await session.execute(
        select(model).where(model.id == target_config_id, model.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


# Config types whose create payload may carry MULTIPLE amount bands (Epic 25).
# A pricing/commission schedule is several bands, created + approved as a unit.
MULTI_BAND_TYPES = {CONFIG_TYPE_PRICING, CONFIG_TYPE_COMMISSION}


async def load_live_scope_as_bands(
    session: AsyncSession, config_type: str, target: object, tenant_id: UUID
) -> list[BaseModel]:
    """Mirror a live config scope into its create-schema band SHAPE (no validation).

    Gathers every live row of `config_type` in this tenant sharing `target`'s
    scope and copies each row's create-relevant fields into the type's create
    schema via `model_construct` — which BYPASSES the create validators on
    purpose. A live row may legitimately hold state a create payload cannot
    (e.g. a limit with every cap null, or an explicit "unlimited" config): the
    baseline must FAITHFULLY MIRROR the live values, never re-assert the create
    rules against them. `_normalise_create_payload`'s `model_dump(mode="json")`
    still serialises Decimals / UUIDs correctly because the declared field types
    drive JSON serialisation regardless of how the model was built.

    Multi-band types (pricing/commission) yield the whole schedule ordered by
    `amount_from` ascending; single-row types (limit/wallet_limit/tax/step_up)
    yield exactly one band.

    Used to synthesize a "current" baseline version for a scope that has no
    applied maker-checker history (see `list_config_history_for_scope`).

    Returns:
        The scope's live rows as create-schema models, amount-ascending.
    """
    model = _MODEL_BY_TYPE[config_type]
    result = await session.execute(select(model).where(model.tenant_id == tenant_id))
    target_scope = config_scope(config_type, target)
    rows = [row for row in result.scalars().all() if config_scope(config_type, row) == target_scope]
    # Order bands by amount_from ascending; single-row types have no amount_from
    # (getattr -> None) so the key is uniform and the sort is a no-op for them.
    rows.sort(
        key=lambda row: (
            getattr(row, "amount_from", None) is None,
            getattr(row, "amount_from", None) or 0,
        )
    )
    schema_cls, _ = _DISPATCH[config_type]
    return [
        schema_cls.model_construct(**{name: getattr(row, name) for name in schema_cls.model_fields})
        for row in rows
    ]


def build_create_schema(config_type: str, payload: dict[str, Any]) -> BaseModel:
    """Validate a proposal payload against its config type's create schema.

    Used both at propose time (fail fast on a malformed payload) and at apply.

    Raises:
        AppHTTPException (422): the payload doesn't match the create schema.
    """
    schema_cls, _ = _DISPATCH[config_type]
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
    """Bands must be ascending + non-overlapping; only the last may be open-ended.

    Bounds are inclusive on both ends (`[amount_from, amount_to]`), so two bands
    overlap when the next band STARTS AT OR BEFORE the previous band's inclusive
    end. This permits the common +1-gap authoring (1-200, 201-400) but rejects
    shared-boundary bands (1-200, 200-400) that would both contain 200.
    """
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
            # An open-ended earlier band, or a start at/below the previous
            # inclusive end, overlaps (bounds are inclusive on both ends).
            if prev_to is None or (frm is not None and frm <= prev_to):
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
    """Write the approved create/update/delete to the real config table.

    Delegates to the config type's own create/replace/delete service, which
    commits — persisting the request mutations the caller staged beforehand in
    the SAME transaction. The underlying service also writes its own
    `*_config.created` / `.updated` / `.deleted` audit row.

    An update is an atomic replace of the payload's scope: `replace_fn` deletes
    every existing row for the scope and inserts the new band(s) in one commit,
    so a mid-apply failure rolls the whole replace back (the scope is never left
    partially wiped).

    A delete removes the target's ENTIRE scope, not just the named row: for a
    multi-band type (pricing/commission) that is the whole schedule; for a
    single-row type (limit/wallet_limit/tax) the scope holds exactly one row, so
    it is behaviour-preserving. The scope-delete helper removes every row and
    writes one `*_config.deleted` audit in a single commit.

    Raises:
        ConfigRequestTargetNotFound (404): a delete whose target row is absent.
        AppHTTPException (409/404/422): propagated from the underlying service
            (e.g. unique collision, bad payload).
    """
    _schema_cls, create_fn = _DISPATCH[request.config_type]
    if request.operation == CONFIG_OP_CREATE:
        # A create may be a multi-band schedule — apply every band in this same
        # transaction so approval is all-or-none (a failure rolls back all rows
        # plus the request→APPLIED transition the caller staged).
        for schema in validate_band_payload(request.config_type, request.payload or {}):
            await create_fn(session, schema, admin=admin, ip_address=ip_address)
    elif request.operation == CONFIG_OP_UPDATE:
        # Atomic replace: hand the whole validated band set to the type's replace
        # helper, which deletes the scope + inserts the new row(s) in one commit.
        schemas = validate_band_payload(request.config_type, request.payload or {})
        replace_fn = _REPLACE_DISPATCH[request.config_type]
        await replace_fn(
            session,
            schemas,
            target_config_id=request.target_config_id,
            admin=admin,
            ip_address=ip_address,
        )
    else:
        # delete — remove the target's ENTIRE scope. Load the live target (its
        # id is guaranteed set by the propose validation) and 404 uniformly if
        # it is gone; the per-type helper then deletes every row of that row's
        # scope + writes one `.deleted` audit in a single commit.
        assert request.target_config_id is not None
        target = await load_config_target(
            session, request.config_type, request.target_config_id, request.tenant_id
        )
        if target is None:
            raise ConfigRequestTargetNotFound()
        delete_scope_fn = _DELETE_SCOPE_DISPATCH[request.config_type]
        await delete_scope_fn(session, target, admin=admin, ip_address=ip_address)
