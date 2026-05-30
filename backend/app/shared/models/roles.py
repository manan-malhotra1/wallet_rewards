"""Role, RolePermission, UserRole models — PRD §6.4 (Module 7).

Platform-side roles distinct from Keycloak realm roles. Keycloak roles gate
operator/admin endpoints (Phase F.1). Platform roles gate which transaction
types a regular user can initiate (this module).

Step 1 of Pay-PRD-0260 orchestration sequence consumes these — a user must
hold at least one active role granting the transaction_type before the
ledger is touched.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.models.base import Base, created_at_col, uuid_pk

# Role status constants — keep in sync with CHECK constraint.
ROLE_STATUS_ACTIVE = "active"
ROLE_STATUS_INACTIVE = "inactive"


class Role(Base):
    """A named permission group within a tenant.

    Examples: "standard_user" (grants p2p + top_up + redemption),
    "merchant" (grants merchant payments only), "frozen" (grants nothing).

    A role's permissions are defined in `role_permissions`. Users are
    assigned roles via `user_roles`. A user can hold multiple roles; if any
    active role grants a transaction_type, the user can perform it.
    """

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_roles_name_per_tenant"),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_roles_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=ROLE_STATUS_ACTIVE
    )
    created_at: Mapped[datetime] = created_at_col()

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all"
    )


class RolePermission(Base):
    """Permission for a single transaction_type within a role.

    `permitted=true` is the default — explicitly denying (`permitted=false`)
    is supported to override a more permissive default in the future. The
    unique constraint on (role_id, transaction_type) ensures one row per
    role-type pair.
    """

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role_id",
            "transaction_type",
            name="uq_role_permissions_per_type",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    permitted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    role: Mapped[Role] = relationship(back_populates="permissions")


class UserRole(Base):
    """Many-to-many — assigns a role to a user."""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles_pair"),
        Index("ix_user_roles_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    assigned_at: Mapped[datetime] = created_at_col()
