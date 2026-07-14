"""Pydantic v2 schemas for the taxes module (Pricing v2 Epic 19)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaxConfigCreateRequest(BaseModel):
    """Admin payload to create a tax config for a (tenant, currency).

    `fee_tax_pct` / `commission_tax_pct` are fractions (0.15 = 15%). The
    inclusive flags select axis 2 / axis 3 of the charge matrix (default
    exclusive = tax added on top).
    """

    tenant_id: UUID
    currency: str = Field(min_length=3, max_length=3)
    fee_tax_pct: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), lt=Decimal("1"))
    commission_tax_pct: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), lt=Decimal("1"))
    fee_tax_inclusive: bool = False
    commission_tax_inclusive: bool = False


class TaxConfigOut(BaseModel):
    """Tax config resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    currency: str
    fee_tax_pct: Decimal
    commission_tax_pct: Decimal
    fee_tax_inclusive: bool
    commission_tax_inclusive: bool
    created_at: datetime
    updated_at: datetime
