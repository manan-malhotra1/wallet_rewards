"""Tenant and TenantConfig models — PRD §6.1."""
import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class Tenant(Base):
    """A logical deployment of the platform.

    Deployment mode determines which modules are active:
      - 'wallet'        : full platform (ledger + rewards + ...)
      - 'rewards_only'  : rules engine + points ledger only
    """

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "deployment_mode IN ('wallet', 'rewards_only')",
            name="ck_tenants_deployment_mode",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_tenants_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    deployment_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    base_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    configs: Mapped[list["TenantConfig"]] = relationship(back_populates="tenant")


class TenantConfig(Base):
    """Per-tenant key/value configuration overrides."""

    __tablename__ = "tenant_config"
    __table_args__ = (
        UniqueConstraint("tenant_id", "config_key", name="uq_tenant_config_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    config_key: Mapped[str] = mapped_column(String(100), nullable=False)
    config_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_at: Mapped[datetime] = updated_at_col()

    tenant: Mapped[Tenant] = relationship(back_populates="configs")
