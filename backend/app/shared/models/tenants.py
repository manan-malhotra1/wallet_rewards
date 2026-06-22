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

    business_type declares what services the tenant has switched on:
      - 'wallet'   : wallet services only (no rewards engine)
      - 'rewards'  : rewards engine only (no wallet)
      - 'both'     : wallet + rewards (full platform — Phase 1 default)

    keycloak_realm is read-only in the UI; populated from the deployment's
    KEYCLOAK_REALM env var on bootstrap (single-realm Phase 1 — per-tenant
    realms land later when multi-realm Keycloak wiring goes in).
    """

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "business_type IN ('wallet', 'rewards', 'both')",
            name="ck_tenants_business_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_tenants_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    business_type: Mapped[str] = mapped_column(String(20), nullable=False)
    keycloak_realm: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
