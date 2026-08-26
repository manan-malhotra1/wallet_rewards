"""CSV parsing and rejects rendering (spec §8.1).

CSV only, no spreadsheet dependency (D17) — Excel reads and writes it natively.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.commission_batches.csv_io import (
    ParsedRow,
    parse_batch_csv,
    render_rejects_csv,
)

_GOOD = """msisdn,currency,amount,note
27831234567,ZAR,1500.00,"Verified against Nov statement"
27839999999,INR,250.5,
"""


def test_parses_rows_in_file_order() -> None:
    """Both rows survive, with the note optional."""
    rows = parse_batch_csv(_GOOD)
    assert len(rows) == 2
    assert rows[0] == ParsedRow(
        row_number=1,
        msisdn="27831234567",
        currency="ZAR",
        amount=Decimal("1500.00"),
        note="Verified against Nov statement",
    )
    assert rows[1].note is None
    assert rows[1].currency == "INR"


def test_row_numbers_are_one_based_and_exclude_the_header() -> None:
    """The maker matches rejects against what their spreadsheet shows."""
    assert [r.row_number for r in parse_batch_csv(_GOOD)] == [1, 2]


def test_currency_is_upper_cased() -> None:
    """So "zar" and "ZAR" are one row, not two."""
    rows = parse_batch_csv("msisdn,currency,amount,note\n27831234567,zar,10,\n")
    assert rows[0].currency == "ZAR"


def test_missing_header_column_is_a_file_level_error() -> None:
    """A wrong file is the maker's mistake, not 5000 row-level rejects."""
    with pytest.raises(ValueError, match="currency"):
        parse_batch_csv("msisdn,amount,note\n27831234567,10,\n")


def test_unparseable_amount_becomes_a_none_amount_not_an_exception() -> None:
    """A bad amount is a ROW-level reject (D15), never a whole-file failure."""
    rows = parse_batch_csv("msisdn,currency,amount,note\n27831234567,ZAR,abc,\n")
    assert rows[0].amount is None


def test_blank_amount_is_none() -> None:
    """An empty cell behaves like an unparseable one."""
    rows = parse_batch_csv("msisdn,currency,amount,note\n27831234567,ZAR,,\n")
    assert rows[0].amount is None


def test_empty_file_is_an_error() -> None:
    """A header with no rows gives a checker nothing to approve."""
    with pytest.raises(ValueError, match="no data rows"):
        parse_batch_csv("msisdn,currency,amount,note\n")


def test_note_column_is_optional() -> None:
    """Only msisdn / currency / amount are required."""
    rows = parse_batch_csv("msisdn,currency,amount\n27831234567,ZAR,10\n")
    assert rows[0].note is None
    assert rows[0].amount == Decimal("10")


def test_rejects_csv_round_trips_with_reasons() -> None:
    """The rejects file keeps the original columns so it is re-uploadable."""
    out = render_rejects_csv(
        [
            (ParsedRow(1, "27831234567", "ZAR", Decimal("10"), None), "msisdn_not_found"),
            (ParsedRow(2, "27839999999", "INR", None, "x"), "invalid_amount"),
        ]
    )
    lines = out.splitlines()
    assert lines[0] == "row_number,msisdn,currency,amount,note,failure_reason"
    assert "msisdn_not_found" in out
    assert "27831234567" in out
    assert len(lines) == 3


def test_rejects_csv_of_nothing_is_just_a_header() -> None:
    """A clean batch still yields a well-formed (empty) rejects file."""
    assert render_rejects_csv([]).strip() == (
        "row_number,msisdn,currency,amount,note,failure_reason"
    )
