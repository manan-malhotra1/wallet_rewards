"""Pydantic v2 schemas for the segments module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.segments.criteria import SegmentCriteria


class SegmentCreateRequest(BaseModel):
    """Admin create payload.

    `group_id` is required — every segment belongs to exactly one group (the
    exclusive-tier "lens" it's evaluated within; see `shared/models/segments.py`).
    `criteria`, when set, makes the segment dynamic: membership is computed by
    the batch evaluator instead of admin-assigned. Leaving it `None` keeps
    today's manual/static behaviour.
    """

    tenant_id: UUID
    group_id: UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    # Within an exclusive group the highest matching priority wins.
    priority: int = Field(default=0, ge=0, le=1000)
    criteria: SegmentCriteria | None = None


class SegmentUpdateRequest(BaseModel):
    """Admin PATCH payload — every field is optional; only provided fields change.

    IMPORTANT: `criteria=None` here means "not provided" (per Pydantic's
    optional-field convention), NOT "clear the criteria". Turning a dynamic
    segment back into a static one requires the explicit `clear_criteria=True`
    flag — this is the only way `Segment.criteria` is set to SQL NULL via this
    endpoint. Sending both `criteria` and `clear_criteria=True` is rejected as
    a contradictory request. `description`, by contrast, honours an explicit
    `null` as "clear it" — there's no separate "not provided vs. clear" split
    for a plain nullable string the way there is for the criteria/flag pair.

    `extra="forbid"`: a typo'd field name (e.g. `piority`) would otherwise be
    silently ignored by Pydantic, producing a 200 no-op PATCH instead of a
    422 the caller can actually notice.
    """

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=500)
    # Moves the segment to a different group. `None` (the default, or
    # omitted) means "don't move" — a segment always belongs to some group,
    # so there is no "clear the group" concept here.
    group_id: UUID | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    criteria: SegmentCriteria | None = None
    # Explicit "turn this dynamic segment static" switch — see class docstring.
    clear_criteria: bool = False

    @model_validator(mode="after")
    def _check_clear_criteria_not_combined_with_criteria(self) -> Self:
        """Reject a payload that both clears and sets criteria in one request.

        Returns:
            The validated `SegmentUpdateRequest`, unchanged.

        Raises:
            ValueError: Both `clear_criteria=True` and a `criteria` payload
                were supplied — the caller must pick one.
        """
        if self.clear_criteria and self.criteria is not None:
            raise ValueError("clear_criteria cannot be combined with a criteria payload")
        return self

    @model_validator(mode="after")
    def _check_not_empty(self) -> Self:
        """Reject a PATCH body with no fields at all — mirrors `TenantUpdateRequest`.

        An empty `{}` body would otherwise be a silent 200 no-op, which
        almost always indicates a client bug (a field that failed to
        serialize, a typo'd key already caught by `extra="forbid"` above,
        etc.) rather than a deliberate request. `model_fields_set` — not a
        check for "every field is at its default" — is what makes this
        correctly reject `{}` while still accepting `{"priority": 0}` (an
        explicit value equal to the default is still a real request).

        Returns:
            The validated `SegmentUpdateRequest`, unchanged.

        Raises:
            ValueError: No field was present in the request body.
        """
        if not self.model_fields_set:
            raise ValueError("PATCH body must include at least one field to update")
        return self


class SegmentOut(BaseModel):
    """Segment resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    group_id: UUID
    name: str
    description: str | None
    priority: int
    # Deliberately `dict[str, Any]`, not `SegmentCriteria` — lenient by
    # design. `GET /segments` must never 500 the whole list because one row
    # holds hand-edited/poisoned criteria that no longer parses against the
    # strict DSL schema (see `evaluator.recompute_tenant`'s poison-isolation
    # note); a loosely-typed passthrough here can always render, even for a
    # row the evaluator itself would skip.
    criteria: dict[str, Any] | None
    is_system: bool
    last_evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SegmentPreviewRequest(BaseModel):
    """Dry-run preview payload — count users a not-yet-saved criteria would match."""

    tenant_id: UUID
    criteria: SegmentCriteria


class SegmentPreviewResponse(BaseModel):
    """Response for `POST /segments/preview`."""

    match_count: int


class SegmentRecomputeResponse(BaseModel):
    """Response for `POST /segments/recompute`."""

    status: str


class MetricInfo(BaseModel):
    """One entry of the criteria DSL's metric vocabulary (GET /segments/metrics)."""

    name: str
    supports_txn_type: bool
    supports_window: bool


class AddUserToSegmentRequest(BaseModel):
    """Admin payload to assign a user to a segment."""

    user_id: UUID


class SegmentGroupCreateRequest(BaseModel):
    """Admin create payload for a segment group."""

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class SegmentGroupOut(BaseModel):
    """Segment-group resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime
