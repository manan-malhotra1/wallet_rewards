"""User-operation request models — admin create/edit user maker-checker (four-eyes).

N-eyes maker-checker control for administrator user-operations: creating a user
and editing an existing user's editable fields. A user-operation PROPOSED by one
admin (the maker) is NOT applied until `required_approvals` DISTINCT checker
approvals land (a checker must differ from the maker). A checker can request
changes with a comment; the maker revises the payload in place and resubmits —
the same request row and its append-only review thread persist across the loop.

Modelled 1:1 on `money_operations.py` (MoneyOperationRequest/Review): same
conventions — uuid_pk, tenant FK, CHECK-constrained enums, created_at/updated_at
helpers, and an append-only review thread with no `updated_at`. Unlike money
operations there is no per-operation approval policy table: user ops are
four-eyes only for now, so `propose_user_operation` always sets
`required_approvals=1` (one distinct checker). The column + CHECK still allow 2
(six-eyes) so a future per-tenant policy can raise it without a migration, but
no API path sets it above 1 yet.
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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# User operations the workflow governs.
USER_OP_CREATE = "create_user"
USER_OP_UPDATE = "update_user"
USER_OPERATIONS = (USER_OP_CREATE, USER_OP_UPDATE)

# Request lifecycle.
USER_OP_STATUS_PENDING = "PENDING"
USER_OP_STATUS_CHANGES_REQUESTED = "CHANGES_REQUESTED"
USER_OP_STATUS_APPLIED = "APPLIED"
USER_OP_STATUS_WITHDRAWN = "WITHDRAWN"
USER_OP_STATUSES = (
    USER_OP_STATUS_PENDING,
    USER_OP_STATUS_CHANGES_REQUESTED,
    USER_OP_STATUS_APPLIED,
    USER_OP_STATUS_WITHDRAWN,
)
# Terminal statuses — no further transitions.
USER_OP_TERMINAL_STATUSES = (USER_OP_STATUS_APPLIED, USER_OP_STATUS_WITHDRAWN)

# Review-thread roles.
USER_REVIEW_ROLE_MAKER = "maker"
USER_REVIEW_ROLE_CHECKER = "checker"

# Review-thread actions.
USER_REVIEW_ACTION_SUBMITTED = "submitted"
USER_REVIEW_ACTION_APPROVED = "approved"
USER_REVIEW_ACTION_CHANGES_REQUESTED = "changes_requested"
USER_REVIEW_ACTION_REVISED = "revised"
USER_REVIEW_ACTION_RESUBMITTED = "resubmitted"
USER_REVIEW_ACTION_WITHDRAWN = "withdrawn"
USER_REVIEW_ACTION_APPLIED = "applied"
USER_REVIEW_ACTIONS = (
    USER_REVIEW_ACTION_SUBMITTED,
    USER_REVIEW_ACTION_APPROVED,
    USER_REVIEW_ACTION_CHANGES_REQUESTED,
    USER_REVIEW_ACTION_REVISED,
    USER_REVIEW_ACTION_RESUBMITTED,
    USER_REVIEW_ACTION_WITHDRAWN,
    USER_REVIEW_ACTION_APPLIED,
)


class UserOperationRequest(Base):
    """A proposed admin user-operation, pending N-eyes maker-checker approval.

    Nothing is created or edited until `required_approvals` DISTINCT checker
    approvals land. The maker who proposed it may not approve their own request;
    each checker counts once. `applied_user_id` is set to the created / edited
    user when the operation is applied (NULL until APPLIED).
    """

    __tablename__ = "user_operation_requests"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('create_user', 'update_user')",
            name="ck_user_operation_requests_operation",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CHANGES_REQUESTED', 'APPLIED', 'WITHDRAWN')",
            name="ck_user_operation_requests_status",
        ),
        CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_user_operation_requests_required_approvals",
        ),
        # Covers the B7.1 approvals window query (WHERE tenant_id, status
        # ORDER BY created_at DESC, id DESC LIMIT/OFFSET) via a backward index
        # scan — no per-page sort. The (tenant_id, status) prefix still serves
        # the /counts grouped query and every status-filtered lookup.
        Index(
            "ix_user_operation_requests_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    # Operation params, editable in place by the maker across revisions — e.g.
    # identifiers / user_type / profile (create), or target_user_id + the edited
    # fields (update).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=USER_OP_STATUS_PENDING
    )
    # Keycloak admin id (sub claim) of the proposing maker.
    maker_admin_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # DISTINCT checker approvals needed before this applies, IN ADDITION to the
    # maker: 1 = four-eyes (maker + 1 checker), 2 = six-eyes (maker + 2 distinct
    # checkers).
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # The user created (create_user) or edited (update_user) when applied. NULL
    # until the request is APPLIED.
    applied_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class UserOperationReview(Base):
    """One append-only entry in a user-operation request's review/comment thread."""

    __tablename__ = "user_operation_reviews"
    __table_args__ = (
        CheckConstraint(
            "actor_role IN ('maker', 'checker')",
            name="ck_user_operation_reviews_actor_role",
        ),
        CheckConstraint(
            "action IN ('submitted', 'approved', 'changes_requested', "
            "'revised', 'resubmitted', 'withdrawn', 'applied')",
            name="ck_user_operation_reviews_action",
        ),
        Index("ix_user_operation_reviews_request", "request_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_operation_requests.id"), nullable=False
    )
    actor_admin_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Append-only — no updated_at (mirrors ledger_entries / audit_log).
    created_at: Mapped[datetime] = created_at_col()
