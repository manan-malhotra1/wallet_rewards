"""Pydantic v2 schemas for the bonus multipliers module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BonusMultiplierCreateRequest(BaseModel):
    """Admin create payload — at least one of rule_id/segment_id may be NULL."""

    tenant_id: UUID
    rule_id: UUID | None = None
    segment_id: UUID | None = None
    multiplier: Decimal = Field(gt=Decimal("0"))
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> BonusMultiplierCreateRequest:
        """When both bounds are set, valid_from must precede valid_until."""
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_from >= self.valid_until
        ):
            raise ValueError("valid_from must be strictly before valid_until")
        return self


class BonusMultiplierOut(BaseModel):
    """BonusMultiplier resource."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    rule_id: UUID | None
    segment_id: UUID | None
    multiplier: Decimal
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime
