"""ExternalEventSource and EventIngestionLog models — PRD §6.11.

These tables back Module 8 (Event Ingestion & Normalisation). Every external
event source must be REGISTERED before its events are accepted (Pay-PRD-0495).
The ingestion log dedupes by `(source_key, external_event_id)` (Pay-PRD-0500).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, uuid_pk

INGESTION_STATUS_PROCESSED = "PROCESSED"
INGESTION_STATUS_DUPLICATE = "DUPLICATE"
INGESTION_STATUS_FAILED = "FAILED"
INGESTION_STATUS_REJECTED = "REJECTED"


class ExternalEventSource(Base):
    """A registered external system that publishes events to the platform.

    Each source has a tenant-scoped name and a globally unique source_key.
    The field_mapping JSONB defines how raw event fields are translated to
    the platform's standard NormalisedEvent schema.

    Phase C adds an OPTIONAL `shared_secret_encrypted` for HMAC verification.
    It is stored Fernet-encrypted at rest (Decision D3) and recovered via
    `decrypt_secret` for signature verification. When NULL, events from this
    source are accepted without verification (test mode). Phase F makes this
    mandatory.
    """

    __tablename__ = "external_event_sources"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_external_event_sources_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Globally unique — used as the partition key for routing events to the
    # correct source registration row.
    source_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    field_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    shared_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at_col()


class EventIngestionLog(Base):
    """Audit trail for every event the platform receives (Pay-PRD-0500, 0520).

    Acts as the dedup mechanism: the UNIQUE constraint on
    (source_key, external_event_id) ensures the same event is never processed
    twice. The status field records the outcome of processing.
    """

    __tablename__ = "event_ingestion_log"
    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "external_event_id",
            name="uq_event_ingestion_log_dedup",
        ),
        CheckConstraint(
            "status IN ('PROCESSED', 'DUPLICATE', 'FAILED', 'REJECTED')",
            name="ck_event_ingestion_log_status",
        ),
        Index(
            "idx_event_ingestion_log_dedup_lookup",
            "source_key",
            "external_event_id",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = created_at_col()
