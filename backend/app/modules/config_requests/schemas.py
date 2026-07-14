"""Pydantic v2 schemas for the config-governance (maker-checker) module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ConfigType = Literal["pricing", "limit", "wallet_limit", "commission", "tax"]
ConfigOperation = Literal["create", "delete"]


class ConfigChangeProposeRequest(BaseModel):
    """Maker's proposal of a single config create/delete.

    For `create`, supply `payload` (the proposed config row, matching that
    config type's create schema). For `delete`, supply `target_config_id`.
    """

    config_type: ConfigType
    operation: ConfigOperation
    payload: dict[str, Any] | None = None
    target_config_id: UUID | None = None


class ConfigChangeReviseRequest(BaseModel):
    """Maker's in-place edit of a CHANGES_REQUESTED request's payload."""

    payload: dict[str, Any]


class ConfigChangeCommentRequest(BaseModel):
    """A checker's request-changes with the mandatory comment."""

    comment: str = Field(min_length=1, max_length=2000)


class ConfigReviewOut(BaseModel):
    """One entry in the review/comment thread."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_admin_id: str
    actor_role: str
    action: str
    comment: str | None
    created_at: datetime


class ConfigChangeRequestOut(BaseModel):
    """A config-change request, optionally with its review thread."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    config_type: str
    operation: str
    payload: dict[str, Any] | None
    target_config_id: UUID | None
    status: str
    maker_admin_id: str
    checker_admin_id: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    reviews: list[ConfigReviewOut] = Field(default_factory=list)
