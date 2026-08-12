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
    a contradictory request.
    """

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


class SegmentOut(BaseModel):
    """Segment resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    group_id: UUID
    name: str
    description: str | None
    priority: int
    criteria: dict[str, Any] | None
    is_system: bool
    last_evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SegmentPreviewRequest(BaseModel):
    """Dry-run preview payload — count users a not-yet-saved criteria would match."""

    tenant_id: UUID
    criteria: SegmentCriteria


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
