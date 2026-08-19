"""Lenient UUID parsing for values read out of untyped JSONB payloads."""

from __future__ import annotations

from uuid import UUID


def parse_uuid(raw: object) -> UUID | None:
    """Parse `raw` as a UUID, returning None for anything malformed or absent.

    For best-effort display enrichment over stored payloads: a bad or missing
    id must degrade to "no name resolved", never raise.
    """
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None
