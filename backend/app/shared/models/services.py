"""Services catalog model (Phase 2 of the Tenant Management refactor).

One row per transaction_type the tenant has switched on. `code` is the
persistent identifier referenced in downstream tables (limit_configs,
pricing_configs, rules, transactions); `display_name` is the human label.

Status values:
  - 'active'   : surfaces in the admin UI dropdowns; tenants can configure
                 limits / pricing / rules referencing this service.
  - 'disabled' : hidden from new-config dropdowns; existing rows that
                 reference this code remain valid (no FK enforcement).

Soft-deletion (`deleted_at` set) removes the row from list endpoints; the
partial-unique index on (tenant_id, code) WHERE deleted_at IS NULL lets a
tenant re-create the same code after deleting it.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

SERVICE_STATUS_ACTIVE = "active"
SERVICE_STATUS_DISABLED = "disabled"


class Service(Base):
    """A configurable service (transaction_type) on a tenant."""

    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_services_status",
        ),
        CheckConstraint("kind IN ('base', 'derived')", name="ck_services_kind"),
        CheckConstraint(
            "(kind = 'base' AND base_service_code IS NULL) "
            "OR (kind = 'derived' AND base_service_code IS NOT NULL)",
            name="ck_services_kind_base_pairing",
        ),
        CheckConstraint(
            "base_service_code IS NULL OR base_service_code <> code",
            name="ck_services_base_not_self",
        ),
        Index("ix_services_tenant", "tenant_id"),
        # Partial-UNIQUE on (tenant_id, code) — only the live (non-deleted)
        # rows count, so a tenant can soft-delete a service and re-create
        # the same code. Declared here (in addition to the migration) so
        # `Base.metadata.create_all` picks it up for the test database.
        Index(
            "uq_services_tenant_code_alive",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=SERVICE_STATUS_ACTIVE
    )
    # 'base' = a flow the platform implements (see app/shared/services_registry);
    # 'derived' = operator-created, delegates to a base. Explicit rather than
    # inferred from base_service_code being NULL, because this is the most
    # important fact about a row (spec §3).
    kind: Mapped[str] = mapped_column(String(10), nullable=False, server_default="base")
    # The base's `code`. NOT NULL for kind='derived', NULL for kind='base' —
    # enforced by ck_services_kind_base_pairing. Intentionally not an FK: the
    # base is identified by code, is per-tenant, and is soft-deletable.
    base_service_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # --- Access policy: WHO may initiate, via WHICH channel ---------------
    # This pair is the single source of truth for both the mobile app's
    # "can I show this service?" display decision and the API's server-side
    # enforcement of who may initiate a transaction of this type.
    #
    # Semantics for BOTH columns: NULL or an empty array means "no
    # restriction on this dimension" (all values allowed). A non-empty array
    # is an allow-list — only the listed values may initiate. The two
    # dimensions are ANDed: a request must satisfy both to be allowed.
    #
    # allowed_user_types values come from the user-type set:
    #   consumer, agent, super_agent, merchant, head_merchant.
    # An operator-only service (e.g. fund/withdraw) is expressed as an EMPTY
    # user-type list plus a channel list of {admin, api}: no wallet user type
    # is singled out, and the admin/api channel gate is what excludes wallet
    # users from initiating it.
    allowed_user_types: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    # allowed_channels values: web, api, mobile, ussd, admin, system.
    allowed_channels: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
