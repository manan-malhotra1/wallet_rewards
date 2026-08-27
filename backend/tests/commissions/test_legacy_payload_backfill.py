"""A commission request stored before D8 still validates after the backfill.

This is the reason migration 0069 exists. `config_requests/apply.py` re-validates
a request's STORED JSONB payload at APPROVAL time — days after the maker wrote
it — so making the parent fields required would otherwise strand every pending
pre-deploy request in a 422 no checker could clear and no maker could resubmit.

These tests exercise the migration's own patch functions against both payload
shapes, then prove the patched result actually validates.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from app.modules.commissions.schemas import CommissionConfigCreateRequest

# Migrations are not an importable package (filenames start with a date), so
# load 0069 by path to test its logic directly rather than duplicating it.
_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260827_0069_backfill_parent_commission_payloads.py"
)
_spec = importlib.util.spec_from_file_location("migration_0069", _MIGRATION)
assert _spec is not None and _spec.loader is not None
migration_0069 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration_0069)


def _legacy_band() -> dict[str, object]:
    """A band exactly as it was written before the parent fields existed."""
    return {
        "tenant_id": str(uuid4()),
        "transaction_type": "cash_in",
        "currency": "ZAR",
        "user_type": "agent",
        "amount_from": None,
        "amount_to": None,
        "fixed_commission": "1",
        "variable_commission_pct": "0.01",
        "commission_cap": None,
    }


def test_a_legacy_band_does_not_validate_unpatched() -> None:
    """Establishes the problem the migration solves — not a hypothetical."""
    with pytest.raises(Exception) as exc:
        CommissionConfigCreateRequest(**_legacy_band())
    message = str(exc.value)
    assert "parent_fixed_commission" in message
    assert "parent_variable_commission_pct" in message


def test_patched_multi_band_payload_validates() -> None:
    """The shape the admin UI actually submits: {"bands": [...]}."""
    payload = {"bands": [_legacy_band(), _legacy_band()]}

    patched, changed = migration_0069._patch_payload(payload)

    assert changed is True
    for band in patched["bands"]:
        CommissionConfigCreateRequest(**band)  # would raise if still invalid
        assert band["parent_fixed_commission"] == "0"
        assert band["parent_variable_commission_pct"] == "0"


def test_patched_flat_payload_validates() -> None:
    """The older single-row shape is patched too."""
    patched, changed = migration_0069._patch_payload(_legacy_band())

    assert changed is True
    CommissionConfigCreateRequest(**patched)


def test_zero_reproduces_the_behaviour_the_request_was_written_under() -> None:
    """Backfilling zero is not an arbitrary default.

    No parent commission existed when these requests were proposed, so approving
    one must still pay the parent nothing.
    """
    patched, _ = migration_0069._patch_payload(_legacy_band())
    request = CommissionConfigCreateRequest(**patched)

    assert request.parent_fixed_commission == 0
    assert request.parent_variable_commission_pct == 0
    assert request.parent_commission_cap is None


def test_an_already_patched_payload_is_left_alone() -> None:
    """Idempotent — a re-run must not overwrite a real parent rate with zero."""
    band = _legacy_band()
    band["parent_fixed_commission"] = "5"
    band["parent_variable_commission_pct"] = "0.005"

    patched, changed = migration_0069._patch_payload({"bands": [band]})

    assert changed is False
    assert patched["bands"][0]["parent_fixed_commission"] == "5"
    assert patched["bands"][0]["parent_variable_commission_pct"] == "0.005"


def test_a_partially_patched_band_gains_only_what_is_missing() -> None:
    """One field present, one absent — only the absent one is added."""
    band = _legacy_band()
    band["parent_fixed_commission"] = "2"

    patched, changed = migration_0069._patch_payload(band)

    assert changed is True
    assert patched["parent_fixed_commission"] == "2"
    assert patched["parent_variable_commission_pct"] == "0"


def test_a_non_dict_payload_is_ignored_rather_than_crashing() -> None:
    """A malformed stored payload must not abort the whole migration."""
    assert migration_0069._patch_payload(None) == (None, False)
    assert migration_0069._patch_payload("garbage") == ("garbage", False)
    assert migration_0069._patch_payload({"bands": ["not-a-dict"]})[1] is False
