"""Pydantic v2 schemas for the events module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceRegistrationRequest(BaseModel):
    """Test-only payload to register a new external event source."""

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)
    # source_key is globally unique — used to identify the source in events.
    source_key: str = Field(min_length=1, max_length=100)
    # Optional: how to map raw event fields to the platform's standard schema.
    # Empty dict means the raw fields already match the standard schema.
    field_mapping: dict[str, str] = Field(default_factory=dict)
    # Optional: when set, events from this source must include an HMAC signature.
    # Phase C does not enforce this — Phase F will.
    shared_secret: str | None = Field(default=None, max_length=1024)


class SourceOut(BaseModel):
    """A registered source returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    source_key: str
    status: str


class RawExternalEvent(BaseModel):
    """The shape of an externally-sourced event ingested into the platform.

    Used by both the admin HTTP endpoint (Phase F.4 — `platform-admin` gated)
    and the Kafka consumer (`scripts/run_consumer.py`) — both code paths
    deserialise to this schema. Field naming follows PRD Pay-PRD-0480.
    """

    event_id: str = Field(min_length=1, max_length=255)
    source_key: str = Field(min_length=1, max_length=100)
    tenant_id: UUID
    user_id: UUID
    transaction_type: str = Field(min_length=1, max_length=50)
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3)
    merchant_id: UUID | None = None
    # ISO 8601; Pydantic v2 parses both string and datetime.
    timestamp: datetime
    # Optional raw payload — preserved for audit.
    raw: dict[str, Any] = Field(default_factory=dict)


ProcessOutcome = Literal["processed", "duplicate", "rejected", "failed"]


class FiringOut(BaseModel):
    """Summary of a single rule firing for the response."""

    rule_id: UUID
    rule_name: str
    reward_type: str
    reward_value: Decimal


class IngestResponse(BaseModel):
    """Result of processing one external event."""

    outcome: ProcessOutcome
    event_id: str
    rules_fired: list[FiringOut] = Field(default_factory=list)
    rejection_reason: str | None = None


@dataclass(frozen=True)
class NormalisedEvent:
    """The internal canonical shape after normalisation (Pay-PRD-0490)."""

    event_id: str
    source_key: str
    tenant_id: UUID
    user_id: UUID
    transaction_type: str
    amount: Decimal
    currency: str
    merchant_id: UUID | None
    timestamp: datetime
