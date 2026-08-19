"""Money-operation request models — Epic 18 (N-eyes maker-checker for money movements).

Dual/N-control for treasury + admin money movements (fund a user, withdraw from a
user, adjust a system wallet, create a bank-mirror account). A money operation
PROPOSED by one admin (the maker) is NOT executed until `required_approvals`
DISTINCT checker approvals land. A checker can request changes with a comment;
the maker revises the payload in place and resubmits — the same request row and
its append-only review thread persist across the whole loop.

Modelled on `config_requests.py` (ConfigChangeRequest/Review) — same conventions:
uuid_pk, tenant FK, CHECK-constrained enums, created_at/updated_at helpers, and an
append-only review thread with no `updated_at`. Adds `approval_policies` so a
tenant can require four-eyes vs six-eyes per operation.
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

# Money operations the workflow governs.
MONEY_OP_FUND_USER = "fund_user"
MONEY_OP_WITHDRAW_USER = "withdraw_user"
MONEY_OP_ADJUST_SYSTEM = "adjust_system_wallet"
MONEY_OP_CREATE_BANK_MIRROR = "create_bank_mirror"
MONEY_OPERATIONS = (
    MONEY_OP_FUND_USER,
    MONEY_OP_WITHDRAW_USER,
    MONEY_OP_ADJUST_SYSTEM,
    MONEY_OP_CREATE_BANK_MIRROR,
)

# Request lifecycle.
MONEY_OP_STATUS_PENDING = "PENDING"
MONEY_OP_STATUS_CHANGES_REQUESTED = "CHANGES_REQUESTED"
MONEY_OP_STATUS_APPLIED = "APPLIED"
MONEY_OP_STATUS_WITHDRAWN = "WITHDRAWN"
MONEY_OP_STATUSES = (
    MONEY_OP_STATUS_PENDING,
    MONEY_OP_STATUS_CHANGES_REQUESTED,
    MONEY_OP_STATUS_APPLIED,
    MONEY_OP_STATUS_WITHDRAWN,
)
# Terminal statuses — no further transitions.
MONEY_OP_TERMINAL_STATUSES = (MONEY_OP_STATUS_APPLIED, MONEY_OP_STATUS_WITHDRAWN)

# Review-thread roles.
MONEY_REVIEW_ROLE_MAKER = "maker"
MONEY_REVIEW_ROLE_CHECKER = "checker"

# Review-thread actions.
MONEY_REVIEW_ACTION_SUBMITTED = "submitted"
MONEY_REVIEW_ACTION_APPROVED = "approved"
MONEY_REVIEW_ACTION_CHANGES_REQUESTED = "changes_requested"
MONEY_REVIEW_ACTION_REVISED = "revised"
MONEY_REVIEW_ACTION_RESUBMITTED = "resubmitted"
MONEY_REVIEW_ACTION_WITHDRAWN = "withdrawn"
MONEY_REVIEW_ACTION_APPLIED = "applied"
MONEY_REVIEW_ACTIONS = (
    MONEY_REVIEW_ACTION_SUBMITTED,
    MONEY_REVIEW_ACTION_APPROVED,
    MONEY_REVIEW_ACTION_CHANGES_REQUESTED,
    MONEY_REVIEW_ACTION_REVISED,
    MONEY_REVIEW_ACTION_RESUBMITTED,
    MONEY_REVIEW_ACTION_WITHDRAWN,
    MONEY_REVIEW_ACTION_APPLIED,
)


class MoneyOperationRequest(Base):
    """A proposed money movement, pending N-eyes maker-checker approval.

    Nothing hits the ledger until `required_approvals` DISTINCT checker approvals
    land. The maker who proposed it may not approve their own request; each
    checker counts once. `applied_transaction_id` is set to the resulting ledger
    transaction when a fund/withdraw/adjust is applied (NULL for create_bank_mirror
    and for any request not yet APPLIED).
    """

    __tablename__ = "money_operation_requests"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('fund_user', 'withdraw_user', "
            "'adjust_system_wallet', 'create_bank_mirror')",
            name="ck_money_operation_requests_operation",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CHANGES_REQUESTED', 'APPLIED', 'WITHDRAWN')",
            name="ck_money_operation_requests_status",
        ),
        CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_money_operation_requests_required_approvals",
        ),
        # Covers the B7.1 approvals window query (WHERE tenant_id, status
        # ORDER BY created_at DESC, id DESC LIMIT/OFFSET) via a backward index
        # scan — no per-page sort. The (tenant_id, status) prefix still serves
        # the /counts grouped query and every status-filtered lookup.
        Index(
            "ix_money_operation_requests_tenant_status_created",
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
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    # Operation params, editable in place by the maker across revisions — e.g.
    # identifier_type/value, amount, currency, bank_mirror_account_id, name.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=MONEY_OP_STATUS_PENDING
    )
    # Keycloak admin id (sub claim) of the proposing maker.
    maker_admin_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # DISTINCT checker approvals needed before this executes, IN ADDITION to
    # the maker: 1 = four-eyes (maker + 1 checker), 2 = six-eyes (maker + 2
    # distinct checkers). Resolved from ApprovalPolicy at propose time.
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # The ledger transaction produced when applied (fund/withdraw/adjust). NULL
    # for create_bank_mirror and until the request is APPLIED.
    applied_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class MoneyOperationReview(Base):
    """One append-only entry in a money-operation request's review/comment thread."""

    __tablename__ = "money_operation_reviews"
    __table_args__ = (
        CheckConstraint(
            "actor_role IN ('maker', 'checker')",
            name="ck_money_operation_reviews_actor_role",
        ),
        CheckConstraint(
            "action IN ('submitted', 'approved', 'changes_requested', "
            "'revised', 'resubmitted', 'withdrawn', 'applied')",
            name="ck_money_operation_reviews_action",
        ),
        Index("ix_money_operation_reviews_request", "request_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("money_operation_requests.id"), nullable=False
    )
    actor_admin_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Append-only — no updated_at (mirrors ledger_entries / audit_log).
    created_at: Mapped[datetime] = created_at_col()


class ApprovalPolicy(Base):
    """Per-tenant (optionally per-operation) required-approvals policy.

    Resolution order at propose time: (tenant, operation) → (tenant, NULL default)
    → code default of 1. No rows are required — the service defaults to 1 approval
    (four-eyes: maker + 1 checker) when no policy row matches. A NULL `operation`
    row is the tenant-wide default applied to every money operation lacking a
    more specific row.
    """

    __tablename__ = "approval_policies"
    __table_args__ = (
        CheckConstraint(
            "operation IS NULL OR operation IN ('fund_user', 'withdraw_user', "
            "'adjust_system_wallet', 'create_bank_mirror')",
            name="ck_approval_policies_operation",
        ),
        CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_approval_policies_required_approvals",
        ),
        UniqueConstraint("tenant_id", "operation", name="uq_approval_policies_tenant_operation"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    # NULL = tenant default for all money ops; else one of MONEY_OPERATIONS.
    operation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
