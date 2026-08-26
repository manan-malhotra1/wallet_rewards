"""Batch CSV parsing and rejects rendering — spec 2026-08-26 §8.1.

Pure string in, data out — no DB session — so the file format is testable
without fixtures and independently of the validation rules.

CSV rather than XLSX (D17): no new dependency, and Excel reads and writes it
natively, which is all the operator needs.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

REQUIRED_COLUMNS = ("msisdn", "currency", "amount")
REJECTS_COLUMNS = (
    "row_number",
    "msisdn",
    "currency",
    "amount",
    "note",
    "failure_reason",
)


@dataclass(frozen=True)
class ParsedRow:
    """One data line, structurally parsed but not yet validated.

    Attributes:
        row_number: 1-based, EXCLUDING the header — matches what the maker sees
            in their spreadsheet, so a rejects file is directly actionable.
        msisdn: Raw, as uploaded. Normalised later, at resolution time.
        currency: Upper-cased at parse so "zar" and "ZAR" are one row, not two.
        amount: None when the cell did not parse as a decimal. Deliberately not
            an exception: a single bad amount is a ROW-level reject (D15) and
            must not fail the whole file.
        note: Maker's justification, or None when blank.
    """

    row_number: int
    msisdn: str
    currency: str
    amount: Decimal | None
    note: str | None


def parse_batch_csv(content: str) -> list[ParsedRow]:
    """Parse an uploaded batch file into rows.

    Args:
        content: The decoded file body, including its header row.

    Returns:
        One ParsedRow per data line, in file order.

    Raises:
        ValueError: the header is missing a required column, or the file has no
            data rows. These are FILE-level problems — the maker uploaded the
            wrong thing — as distinct from row-level ones, which are collected
            and reported per row rather than raised.
    """
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise ValueError("The file has no header row.")

    header = {(name or "").strip().lower() for name in reader.fieldnames}
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}.")

    rows: list[ParsedRow] = []
    for index, raw in enumerate(reader, start=1):
        normalised = {(k or "").strip().lower(): (v or "") for k, v in raw.items()}
        note = normalised.get("note", "").strip()
        rows.append(
            ParsedRow(
                row_number=index,
                msisdn=normalised.get("msisdn", "").strip(),
                currency=normalised.get("currency", "").strip().upper(),
                amount=_to_decimal(normalised.get("amount")),
                note=note or None,
            )
        )

    if not rows:
        raise ValueError("The file has no data rows.")
    return rows


def _to_decimal(value: str | None) -> Decimal | None:
    """Parse an amount cell, returning None rather than raising on garbage."""
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None


def render_rejects_csv(rejects: list[tuple[ParsedRow, str]]) -> str:
    """Render rejected rows back to CSV, original columns plus the reason.

    Keeping the original columns is what makes the file directly re-uploadable:
    the maker deletes the `failure_reason` column, fixes the data and submits a
    NEW batch (D15, D16).

    Args:
        rejects: (row, machine-readable failure reason) pairs, in file order.

    Returns:
        The CSV body, header included.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(REJECTS_COLUMNS)
    for row, reason in rejects:
        writer.writerow(
            [
                row.row_number,
                row.msisdn,
                row.currency,
                "" if row.amount is None else str(row.amount),
                row.note or "",
                reason,
            ]
        )
    return buffer.getvalue()
