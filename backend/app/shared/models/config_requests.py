"""Config-change request models — Pricing v2 Epic 22 (maker-checker).

Dual-control ("four-eyes") for every config change. A change PROPOSED by one
admin (the maker) only takes effect once a DIFFERENT admin (the checker,
holding `config-approver`) approves it. The checker can request changes with a
comment; the maker revises the payload in place and resubmits — the same
request row and its append-only review thread persist across the whole loop.

One generic `config_change_requests` table covers every config type so
enforcement/readers keep the invariant "the active config == what's in the
config tables" (nothing is written to a real config table until APPLIED).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Config types the workflow governs.
CONFIG_TYPE_PRICING = "pricing"
CONFIG_TYPE_LIMIT = "limit"
CONFIG_TYPE_WALLET_LIMIT = "wallet_limit"
CONFIG_TYPE_COMMISSION = "commission"
CONFIG_TYPE_TAX = "tax"
CONFIG_TYPES = (
    CONFIG_TYPE_PRICING,
    CONFIG_TYPE_LIMIT,
    CONFIG_TYPE_WALLET_LIMIT,
    CONFIG_TYPE_COMMISSION,
    CONFIG_TYPE_TAX,
)

# Operations a request can carry.
CONFIG_OP_CREATE = "create"
CONFIG_OP_UPDATE = "update"
CONFIG_OP_DELETE = "delete"
CONFIG_OPERATIONS = (CONFIG_OP_CREATE, CONFIG_OP_UPDATE, CONFIG_OP_DELETE)

# Request lifecycle.
CONFIG_STATUS_PENDING = "PENDING"
CONFIG_STATUS_CHANGES_REQUESTED = "CHANGES_REQUESTED"
CONFIG_STATUS_APPLIED = "APPLIED"
CONFIG_STATUS_WITHDRAWN = "WITHDRAWN"
CONFIG_STATUSES = (
    CONFIG_STATUS_PENDING,
    CONFIG_STATUS_CHANGES_REQUESTED,
    CONFIG_STATUS_APPLIED,
    CONFIG_STATUS_WITHDRAWN,
)
# Terminal statuses — no further transitions.
CONFIG_TERMINAL_STATUSES = (CONFIG_STATUS_APPLIED, CONFIG_STATUS_WITHDRAWN)

# Review-thread roles + actions.
REVIEW_ROLE_MAKER = "maker"
REVIEW_ROLE_CHECKER = "checker"
REVIEW_ACTION_SUBMITTED = "submitted"
REVIEW_ACTION_CHANGES_REQUESTED = "changes_requested"
REVIEW_ACTION_REVISED = "revised"
REVIEW_ACTION_RESUBMITTED = "resubmitted"
REVIEW_ACTION_APPROVED = "approved"
REVIEW_ACTION_WITHDRAWN = "withdrawn"


class ConfigChangeRequest(Base):
    """A proposed create/update/delete of one config scope, pending four-eyes approval."""

    __tablename__ = "config_change_requests"
    __table_args__ = (
        CheckConstraint(
            "config_type IN ('pricing', 'limit', 'wallet_limit', 'commission', 'tax')",
            name="ck_config_change_requests_config_type",
        ),
        CheckConstraint(
            "operation IN ('create', 'update', 'delete')",
            name="ck_config_change_requests_operation",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CHANGES_REQUESTED', 'APPLIED', 'WITHDRAWN')",
            name="ck_config_change_requests_status",
        ),
        Index("ix_config_change_requests_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    config_type: Mapped[str] = mapped_column(String(20), nullable=False)
    operation: Mapped[str] = mapped_column(String(10), nullable=False)
    # The proposed config (create/update) — the FULL new config, editable in
    # place by the maker across revisions. NULL for a pure delete, which uses
    # `target_config_id`.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # The existing config row being deleted (delete) or edited (update): the
    # live row for traceability + the propose-time existence check. NULL on create.
    target_config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=CONFIG_STATUS_PENDING
    )
    # Keycloak admin ids (sub claim). The checker is NULL until an action lands.
    maker_admin_id: Mapped[str] = mapped_column(String(255), nullable=False)
    checker_admin_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ConfigChangeReview(Base):
    """One append-only entry in a request's review/comment thread."""

    __tablename__ = "config_change_reviews"
    __table_args__ = (
        CheckConstraint(
            "actor_role IN ('maker', 'checker')",
            name="ck_config_change_reviews_actor_role",
        ),
        CheckConstraint(
            "action IN ('submitted', 'changes_requested', 'revised', "
            "'resubmitted', 'approved', 'withdrawn')",
            name="ck_config_change_reviews_action",
        ),
        Index("ix_config_change_reviews_request", "request_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("config_change_requests.id"), nullable=False
    )
    actor_admin_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Append-only — no updated_at (mirrors ledger_entries / audit_log).
    created_at: Mapped[datetime] = created_at_col()


class ConfigChangeRevision(Base):
    """An immutable snapshot of a request's payload at one revision.

    The request row keeps only the LATEST payload (revise overwrites it in
    place). To let both maker and checker read what every prior version looked
    like, we append one snapshot per revision here: revision 1 at propose, then
    one more each time the maker revises. Append-only — never updated or deleted
    (mirrors ledger_entries / audit_log / config_change_reviews).
    """

    __tablename__ = "config_change_revisions"
    __table_args__ = (
        UniqueConstraint(
            "request_id", "revision", name="uq_config_change_revisions_request_revision"
        ),
        Index("ix_config_change_revisions_request", "request_id", "revision"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("config_change_requests.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    # The proposed config row as of this revision. NULL for a delete proposal,
    # which carries no payload.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Append-only — no updated_at.
    created_at: Mapped[datetime] = created_at_col()
