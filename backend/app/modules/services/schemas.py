"""Pydantic v2 schemas for the services catalog module.

`code` is the persistent identifier — once a service has been referenced
in limits / pricing / rules / transactions, renaming it would orphan that
configuration, so the PATCH schema does not include it. display_name,
description, status and the two access-policy allow-lists are editable.

Access-policy representation (matches the `Service` model + the mobile
`/me/services` query): both `allowed_user_types` and `allowed_channels` are
nullable lists where **NULL/omitted means "unrestricted"** (all values allowed)
and a **non-empty list is an allow-list**. An **empty list `[]` is a distinct,
meaningful value** — "restrict to none on this dimension" (for user_types that
is operator-only). Because NULL and `[]` differ in meaning, `ServiceOut` keeps
NULL as `null` and never normalises it to `[]`; on update, a `None` field means
"leave unchanged" while `[]` explicitly sets the empty allow-list.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, computed_field

from app.shared.services_registry import DERIVABLE_BASE_CODES

ServiceStatus = Literal["active", "disabled"]

# Canonical channel set for the `allowed_channels` allow-list. Single source of
# truth for the values documented on the `Service.allowed_channels` column.
SERVICE_CHANNELS: tuple[str, ...] = ("web", "api", "mobile", "ussd", "admin", "system")


def _validate_channels(value: list[str] | None) -> list[str] | None:
    """Reject any channel not in the canonical set (empty/None pass through).

    Raises:
        ValueError: at least one element is not a known channel (→ 422).
    """
    if value is None:
        return value
    unknown = [v for v in value if v not in SERVICE_CHANNELS]
    if unknown:
        raise ValueError(f"unknown channel(s) {unknown}; allowed: {list(SERVICE_CHANNELS)}")
    return value


# Reusable field types — keep create + update DRY and consistent.
#
# `allowed_user_types` is deliberately UNVALIDATED here. User types became
# runtime, per-tenant catalog data on this branch, so the legal set is a DB
# lookup scoped to the payload's tenant — something a sync Pydantic validator
# has neither a session nor a tenant for. Validating it against the old
# five-element `USER_TYPES` tuple made every tenant-defined type a 422 and, via
# the `allowed_user_types` membership gate in `identity.list_my_services` /
# `services.assert_service_allowed`, locked custom-type users out of every
# restricted service with no way to add them. The check now lives in
# `services.service._assert_allowed_user_types_valid`, which resolves each code
# against the tenant's catalog — the same move migration 0064 made for the four
# config tables. Channels stay here: that set really is a fixed constant.
AllowedUserTypes = list[str] | None
AllowedChannels = Annotated[list[str] | None, AfterValidator(_validate_channels)]


class ServiceReadiness(BaseModel):
    """Which of the three transacting prerequisites a service satisfies.

    `false` on any field is conclusive — no pricing row, no limit row, or no
    active role grant means NO caller can transact under this code. `true`
    means only "configured at all": pricing and limit rows are scoped by
    account_type / currency / user_type, so a row existing does not guarantee
    one resolves for every caller. Callers must not present `true` as "this
    definitely works".
    """

    model_config = ConfigDict(extra="forbid")

    pricing: bool
    limits: bool
    role: bool


class ServiceOut(BaseModel):
    """Service catalog row returned by the API.

    `allowed_user_types` / `allowed_channels` are returned verbatim from the
    row: `null` = unrestricted, `[]` = restrict-to-none, a list = allow-list.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    display_name: str
    description: str | None
    status: ServiceStatus
    kind: str
    base_service_code: str | None
    allowed_user_types: list[str] | None
    allowed_channels: list[str] | None
    created_at: datetime
    updated_at: datetime
    # Populated by the list endpoint from one grouped query set; None when a
    # caller builds a ServiceOut without asking for readiness (e.g. the
    # create/patch/delete responses, where it would be misleading anyway
    # because config is added afterwards).
    readiness: ServiceReadiness | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def derivable(self) -> bool:
        """True iff a new derived service may be pointed at THIS row.

        Served from the registry rather than left to the client to work out,
        because the rule has two parts that a client would have to duplicate:
        the row must be a base service, AND its code must be in
        `DERIVABLE_BASE_CODES` (which excludes `change_pin` — see the registry).
        A TypeScript copy of that set is exactly the drift the registry exists
        to prevent: adding a non-derivable base would leave the admin UI
        offering it in the base dropdown until someone remembered to edit the
        duplicate, and the only symptom would be a 422 at create time.
        """
        return self.kind == "base" and self.code in DERIVABLE_BASE_CODES


class ServiceCreateRequest(BaseModel):
    """Create payload — code locked at creation.

    Only derived services can be created through this endpoint (spec §6):
    base services ship with the platform and are provisioned per tenant by
    `provision_tenant_defaults`, not created here. `kind` is therefore not a
    client-supplied field at all — the service layer always sets it to
    'derived' — and `base_service_code` is required.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    code: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_]*$",
        description=(
            "Lowercase identifier used in transaction_type fields across the "
            "platform. Cannot be changed after creation."
        ),
    )
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    # Required: base services ship with the platform and are provisioned per
    # tenant, so the only thing this endpoint creates is a derived service
    # (spec §6). `kind` is deliberately NOT a client field.
    base_service_code: str = Field(
        min_length=2,
        max_length=50,
        description="Code of the platform base service this derives from.",
    )
    # NULL/omitted = unrestricted on that dimension; [] = restrict-to-none.
    allowed_user_types: AllowedUserTypes = None
    allowed_channels: AllowedChannels = None


class ServiceUpdateRequest(BaseModel):
    """Patch body for catalog admin edits.

    A field left as `None` (omitted) leaves that column unchanged so a partial
    edit never wipes an existing policy; send `[]` to explicitly clear a
    dimension to restrict-to-none.

    `base_service_code` is deliberately absent: re-pointing a live derived
    service at a different execution path would silently repurpose its
    pricing and limits, so it is immutable. Unlike `code` (which is simply
    documented as immutable above), this schema's `extra="forbid"` turns any
    attempt to set it into a 422 rather than the spec's proposed 409 — a
    stricter, simpler contract than spec §6 describes (deviation noted for
    the controller).
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: ServiceStatus | None = None
    allowed_user_types: AllowedUserTypes = None
    allowed_channels: AllowedChannels = None
