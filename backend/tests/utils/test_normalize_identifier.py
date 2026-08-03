"""Unit tests for identifier normalisation (`app.shared.utils.normalize`).

Locks in the canonical phone form (E.164: a single leading '+' then digits) so
that the presence/absence of the '+' and any visual formatting collapse to ONE
identifier. This is the chokepoint behind uniqueness at create_user /
add_identifier / the maker-checker duplicate guard and auth lookup, so a
regression here re-opens the reported double-registration bug.
"""

from __future__ import annotations

import pytest

from app.shared.utils.normalize import normalize_identifier, normalize_phone

CANONICAL = "+27825550007"


@pytest.mark.parametrize(
    "raw",
    [
        "27825550007",  # the reported bug: NO leading '+'
        "+27825550007",  # already canonical
        "+27 82 555 0007",  # spaced
        "+27-82-555-0007",  # dashed
        "+27 (82) 555.0007",  # parens + dot
        "  +27825550007  ",  # surrounding whitespace
        "++27825550007",  # duplicated '+'
    ],
)
def test_phone_variants_all_normalise_to_canonical(raw: str) -> None:
    """Verify every visual/`+`-variant of one number collapses to a single identifier"""
    assert normalize_identifier("phone", raw) == CANONICAL


def test_phone_plus_and_no_plus_are_equal() -> None:
    """Verify a phone with and without the leading '+' resolve to the SAME identifier"""
    assert normalize_identifier("phone", "27825550007") == normalize_identifier(
        "phone", "+27825550007"
    )


def test_phone_spaced_equals_no_plus() -> None:
    """Verify a spaced phone and a bare-digits phone resolve to the SAME identifier"""
    assert normalize_identifier("phone", "+27 82 555 0007") == normalize_identifier(
        "phone", "27825550007"
    )


def test_normalize_phone_helper_matches_dispatch() -> None:
    """Verify the phone helper and the type-dispatch entrypoint agree"""
    assert normalize_phone("27825550007") == normalize_identifier("phone", "27825550007")


def test_empty_phone_passed_through() -> None:
    """Verify an empty phone stays empty so caller validation surfaces the miss"""
    assert normalize_identifier("phone", "") == ""


def test_all_punctuation_phone_yields_empty_not_bare_plus() -> None:
    """Verify a phone with no digits normalises to empty, never a lone '+'"""
    assert normalize_identifier("phone", "()- .") == ""


def test_email_is_lowercased_and_trimmed_unchanged() -> None:
    """Verify email normalisation is untouched by the phone fix (regression guard)"""
    assert normalize_identifier("email", "  Jane@Example.COM ") == "jane@example.com"


def test_email_not_stripped_of_plus_or_digits() -> None:
    """Verify email keeps '+' and formatting (phone stripping must not leak to email)"""
    assert normalize_identifier("email", "jane+tag@example.com") == "jane+tag@example.com"


def test_account_identifier_passthrough_trimmed() -> None:
    """Verify account identifiers keep their grouping characters (only trimmed)"""
    assert normalize_identifier("account", "  ZA-001-887-2210 ") == "ZA-001-887-2210"
