"""Pydantic v2 schemas for the user-type catalog.

`UserTypeCreateRequest` doubles as the maker-checker payload schema for BOTH
create and update — the config-request pipeline validates every payload against
the type's create schema (`config_requests/apply.py:build_create_schema`), and
an update is expressed as the full desired row.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.models import USER_TYPE_STATUS_ACTIVE


class UserTypeCreateRequest(BaseModel):
    """A proposed user type — the maker-checker payload for create and update.

    `code` is constrained to a lowercase snake_case identifier because it is the
    join key written verbatim into `users.user_type` and every config row, with
    no foreign key to normalise it later (spec D5: codes are immutable).

    The 20-character cap is the width of `users.user_type` and of the `user_type`
    column on every config table. A longer code would validate here and then
    fail as a raw `DataError` (500) the first time a user was created with it.
    Widening `users` — a large hot table — for ten extra characters is not worth
    it: `code` is a machine identifier, the operator-facing name is `label`,
    which has 60.
    """

    tenant_id: UUID
    code: str = Field(min_length=2, max_length=20, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=60)
    category_code: str = Field(min_length=1, max_length=30)
    requires_merchant_profile: bool = False
    # Holds another type's `code`, so it carries the same cap — a longer value
    # could never resolve to a real type.
    parent_type_code: str | None = Field(default=None, max_length=20)
    status: str = USER_TYPE_STATUS_ACTIVE


class UserTypeOut(BaseModel):
    """A user type as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    code: str
    label: str
    category_code: str
    is_system: bool
    status: str
    requires_merchant_profile: bool
    parent_type_code: str | None
    created_at: datetime


class UserTypeCategoryOut(BaseModel):
    """A category as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    display_order: int
    supports_hierarchy: bool
