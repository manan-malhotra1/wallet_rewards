"""Pydantic v2 schemas for the user-operation maker-checker module.

Each user operation carries an operation-specific `payload`. The per-operation
payload schemas below are the single source of truth for that shape —
`propose`/`revise` validate against them (fail fast, 422) and `apply` re-parses
the stored JSON back through them before dispatching to the identity service.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.identity.schemas import IdentifierIn, UserProfileIn, UserType

# -----------------------------------------------------------------------------
# Per-operation payloads
# -----------------------------------------------------------------------------


class CreateUserPayload(BaseModel):
    """Payload for `create_user` — the fields identity.create_user needs.

    At least one identifier is required and it MUST include an email or phone
    (the primary contact identifiers). `tenant_id` is NOT part of the payload —
    it comes from the request's tenant scope, resolved at apply time.
    """

    identifiers: list[IdentifierIn] = Field(min_length=1)
    user_type: UserType = "consumer"
    profile: UserProfileIn | None = None

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> Self:
        """At least one identifier must be an email or phone."""
        types = {ident.identifier_type for ident in self.identifiers}
        if not (types & {"email", "phone"}):
            raise ValueError("At least one identifier must be an email or phone.")
        return self


class UpdateUserPayload(BaseModel):
    """Payload for `update_user` — the EDITABLE fields of an existing user.

    Identifiers are NOT editable here (view-only, out of scope). At least one
    editable field must be supplied.
    """

    target_user_id: UUID
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    status: Literal["active", "suspended"] | None = None
    user_type: UserType | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> Self:
        """Reject a no-op update with no editable field set."""
        if (
            self.first_name is None
            and self.last_name is None
            and self.status is None
            and self.user_type is None
        ):
            raise ValueError("At least one editable field is required.")
        return self


# operation -> its payload schema. The single lookup used by propose/revise
# (validate) and apply (re-parse the stored JSON).
PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "create_user": CreateUserPayload,
    "update_user": UpdateUserPayload,
}


# -----------------------------------------------------------------------------
# API request / response schemas
# -----------------------------------------------------------------------------


class UserOperationProposeRequest(BaseModel):
    """A maker's proposal of a user operation.

    `payload` is validated against the schema for `operation` at propose time;
    an invalid payload is a 422 before anything is written.
    """

    operation: str
    payload: dict[str, object]


class UserOperationReviseRequest(BaseModel):
    """A maker's in-place edit of a CHANGES_REQUESTED request's payload."""

    payload: dict[str, object]


class UserOperationCommentRequest(BaseModel):
    """A checker's request-changes with the mandatory comment."""

    comment: str = Field(min_length=1, max_length=2000)


class UserReviewOut(BaseModel):
    """One entry in a user operation's append-only review thread."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_admin_id: str
    # Resolved display name for actor_admin_id (None if not yet recorded).
    actor_admin_name: str | None = None
    actor_role: str
    action: str
    comment: str | None
    created_at: datetime


class UserOperationOut(BaseModel):
    """A user-operation request, with its review thread + N-eyes progress.

    `approvals_count` is the number of DISTINCT checker approvals recorded in
    the CURRENT approval round (since the latest resubmit) — it reaches
    `required_approvals` at the moment the operation applies.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    operation: str
    payload: dict[str, object]
    status: str
    maker_admin_id: str
    # Resolved display name (None if the admin hasn't been recorded yet).
    maker_admin_name: str | None = None
    required_approvals: int
    approvals_count: int = 0
    applied_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    reviews: list[UserReviewOut] = Field(default_factory=list)
    # For update_user: the current display name of the user being edited so the
    # UI shows who's being changed. None when unresolvable / not an update.
    target_name: str | None = None
