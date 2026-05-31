"""Event normalisation — Pay-PRD-0490, Pay-PRD-0510.

Maps a raw external event payload to the platform's standard NormalisedEvent
shape. The `field_mapping` JSONB on `external_event_sources` defines per-source
how to translate raw field names into the standard ones.

Phase C treats empty mapping as identity (raw already uses standard names).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.events.schemas import NormalisedEvent, RawExternalEvent


def normalise(
    raw: RawExternalEvent, field_mapping: dict[str, str] | None
) -> NormalisedEvent:
    """Translate a RawExternalEvent into a NormalisedEvent.

    Args:
        raw: The validated incoming event.
        field_mapping: Source-specific mapping. Keys are standard field names,
            values are the corresponding raw field names. Phase C only uses
            identity mapping (empty dict), but the parameter is accepted so
            we don't have to re-architect when partner schemas land.

    Returns:
        The NormalisedEvent ready for rules evaluation.
    """
    # Phase C: the RawExternalEvent already validates and parses everything
    # via Pydantic. The mapping argument is reserved for future use when
    # partners send their own field names.
    _ = field_mapping

    return NormalisedEvent(
        event_id=raw.event_id,
        source_key=raw.source_key,
        tenant_id=raw.tenant_id,
        user_id=raw.user_id,
        transaction_type=raw.transaction_type,
        amount=Decimal(raw.amount),
        currency=raw.currency.upper(),
        merchant_id=raw.merchant_id,
        timestamp=raw.timestamp,
    )


# Bind types to the import graph so linters don't complain about unused imports.
_ = (datetime, UUID)
