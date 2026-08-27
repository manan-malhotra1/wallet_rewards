"""Backfill parent-commission terms into stored commission config-request payloads.

Spec: docs/superpowers/specs/2026-08-26-commission-wallet-design.md D8.

`CommissionConfigCreateRequest` now REQUIRES `parent_fixed_commission` and
`parent_variable_commission_pct` — zero must be an explicit decision, not an
omission. But `config_requests/apply.py` re-validates a request's STORED JSONB
payload against that schema at APPROVAL time, which can be days after the maker
submitted it. Without this backfill, every commission request written before the
parent fields existed would 422 forever: a checker could never clear it and the
maker could never resubmit it unchanged.

Scope: only NON-TERMINAL requests (PENDING / CHANGES_REQUESTED) — the ones that
can still be approved. APPLIED and WITHDRAWN rows are history and are left
exactly as written, so the audit trail keeps showing what was actually proposed.
`config_request_revisions` snapshots are likewise untouched: they are display-only
history and are never re-validated.

Zero is the correct backfill value because it reproduces the behaviour those
requests were proposed under — no parent commission existed when they were
written, so approving one must still pay the parent nothing.

Revision ID: 0069
Revises: 0068
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: str | Sequence[str] | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The two now-required fields, with the values that reproduce "no parent leg".
_DEFAULTS = {
    "parent_fixed_commission": "0",
    "parent_variable_commission_pct": "0",
}


def _patch_band(band: Any) -> tuple[Any, bool]:
    """Add the missing parent terms to one band. Returns (band, changed)."""
    if not isinstance(band, dict):
        return band, False
    changed = False
    for key, value in _DEFAULTS.items():
        if key not in band:
            band[key] = value
            changed = True
    return band, changed


def _patch_payload(payload: Any) -> tuple[Any, bool]:
    """Patch a payload in either shape: {"bands": [...]} or a single flat dict."""
    if not isinstance(payload, dict):
        return payload, False

    bands = payload.get("bands")
    if isinstance(bands, list):
        changed = False
        for index, band in enumerate(bands):
            bands[index], band_changed = _patch_band(band)
            changed = changed or band_changed
        return payload, changed

    return _patch_band(payload)


def upgrade() -> None:
    """Add explicit zero parent terms to every still-appliable commission payload."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, payload FROM config_change_requests "
            "WHERE config_type = 'commission' "
            "AND status IN ('PENDING', 'CHANGES_REQUESTED') "
            "AND payload IS NOT NULL"
        )
    ).fetchall()

    patched = 0
    for row in rows:
        payload = row.payload
        # psycopg may hand back JSONB as a str depending on the driver/codec.
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload, changed = _patch_payload(payload)
        if not changed:
            continue
        bind.execute(
            sa.text(
                "UPDATE config_change_requests SET payload = CAST(:payload AS jsonb) "
                "WHERE id = :id"
            ),
            {"payload": json.dumps(payload), "id": row.id},
        )
        patched += 1

    if patched:
        print(f"  backfilled parent commission terms into {patched} pending request(s)")


def downgrade() -> None:
    """No-op.

    Removing the keys again would leave those payloads invalid against whichever
    schema version is live, and the values are semantically correct either way —
    an explicit zero parent commission is exactly what these requests meant.
    """
