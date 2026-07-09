"""MerchantProfile model — merchants-as-users extension (Epic 17 S1).

A merchant is a `user_type='merchant'` user (Decision D1) whose business +
provider metadata live here. The first vertical is airtime: the airtime
merchant carries `service_code='airtime_recharge'`, a provisioning `mode`
(simulator | live), non-secret settings in `provider_config`, and a
Fernet-encrypted `callback_secret_encrypted` used to verify provider callbacks.

The merchant is credited (via its `airtime_merchant_holding` account) when a
user buys the service it serves. At most one ACTIVE merchant may serve a given
`service_code` within a tenant (partial-unique index) so the recharge flow
resolves the counterparty unambiguously.

PRD references: user-types initiative Epic 17; NFR-0170 (secret never logged).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Provisioning mode. A simulator ships in v1; a real provider adapter swaps in
# behind the same interface later (Epic 17 S3). Keep in sync with the CHECK.
MERCHANT_MODE_SIMULATOR = "simulator"
MERCHANT_MODE_LIVE = "live"
MERCHANT_MODES = (MERCHANT_MODE_SIMULATOR, MERCHANT_MODE_LIVE)

MERCHANT_PROFILE_STATUS_ACTIVE = "active"
MERCHANT_PROFILE_STATUS_INACTIVE = "inactive"
MERCHANT_PROFILE_STATUSES = (
    MERCHANT_PROFILE_STATUS_ACTIVE,
    MERCHANT_PROFILE_STATUS_INACTIVE,
)

# The first vertical's category value.
MERCHANT_CATEGORY_AIRTIME = "airtime"


class MerchantProfile(Base):
    """Business + provider metadata for a `user_type='merchant'` user."""

    __tablename__ = "merchant_profiles"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('simulator', 'live')",
            name="ck_merchant_profiles_mode",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_merchant_profiles_status",
        ),
        Index("ix_merchant_profiles_tenant", "tenant_id"),
        Index(
            "ix_merchant_profiles_tenant_service",
            "tenant_id",
            "service_code",
            "status",
        ),
        # One profile per merchant user.
        Index("uq_merchant_profiles_user", "user_id", unique=True),
        # At most one ACTIVE merchant per (tenant, service_code) — makes the
        # recharge-time counterparty lookup deterministic. Relax with an
        # explicit selection strategy when multiple merchants per service are
        # needed.
        Index(
            "uq_merchant_profiles_active_service",
            "tenant_id",
            "service_code",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Vertical category, e.g. 'airtime'. Free-form; the airtime flow filters on it.
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # The service this merchant fulfils == Service.code == transaction_type,
    # e.g. 'airtime_recharge'. Links the merchant to the services catalog.
    service_code: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=MERCHANT_MODE_SIMULATOR
    )
    # Non-secret provider settings (endpoint URL, timeouts, provider slug).
    provider_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Fernet-encrypted shared secret used to verify provider callbacks
    # (auth.secret_box). NULL until configured; never logged (NFR-0170).
    callback_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=MERCHANT_PROFILE_STATUS_ACTIVE
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
