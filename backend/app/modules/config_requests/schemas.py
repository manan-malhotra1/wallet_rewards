"""Pydantic v2 schemas for the config-governance (maker-checker) module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ConfigType = Literal[
    "pricing",
    "limit",
    "wallet_limit",
    "commission",
    "tax",
    "step_up",
    "conversion_rate",
]
ConfigOperation = Literal["create", "update", "delete"]


class ConfigChangeProposeRequest(BaseModel):
    """Maker's proposal of a single config create/update/delete.

    For `create`, supply `payload` (the proposed config row, matching that
    config type's create schema). For `update`, supply BOTH `payload` (the FULL
    new config, same shape as create — its scope must match the live row) and
    `target_config_id` (the live row being edited). For `delete`, supply
    `target_config_id` only.
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
    # Resolved display name for actor_admin_id (None if not yet recorded).
    actor_admin_name: str | None = None
    actor_role: str
    action: str
    comment: str | None
    created_at: datetime


class ConfigRevisionOut(BaseModel):
    """One immutable payload snapshot of the request at a given revision."""

    model_config = ConfigDict(from_attributes=True)

    revision: int
    # None for a delete proposal (no payload) or a pre-snapshot backfill gap.
    payload: dict[str, Any] | None
    created_at: datetime


class ConfigChangeRequestOut(BaseModel):
    """A config-change request, optionally with its review thread + snapshots."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    config_type: str
    operation: str
    payload: dict[str, Any] | None
    target_config_id: UUID | None
    status: str
    maker_admin_id: str
    # Resolved display names (None if the admin hasn't been recorded yet).
    maker_admin_name: str | None = None
    checker_admin_id: str | None
    checker_admin_name: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime
    reviews: list[ConfigReviewOut] = Field(default_factory=list)
    # Per-revision payload snapshots (detail endpoint only), revision-ascending.
    revisions: list[ConfigRevisionOut] = Field(default_factory=list)
    # True only for the read-time "current" baseline synthesized for a scope with
    # no applied maker-checker history (e.g. a seed-created config). The UI labels
    # it "Current (baseline)" and MUST NOT call GET /{id} for it — its id is the
    # live config row's id, not a real request id, so that fetch would 404.
    synthesized: bool = False
