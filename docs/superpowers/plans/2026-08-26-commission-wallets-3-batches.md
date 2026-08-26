# Commission Wallets — Plan 3 of 3: Bulk Disbursement & Withdrawal

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator move accrued commission out of commission wallets in bulk — into the earner's main wallet (disbursement) or back to the operator (withdrawal) — under maker-checker, from a CSV, with partial success and downloadable rejects.

**Architecture:** A new `commission_batches` module with its own header/rows/reviews tables, reusing Epic 18's `approval_policies` and quorum semantics rather than reimplementing them. Validation runs twice: once at upload so the checker only ever sees valid rows, and again under the row lock at apply, because balances drift between approval and execution.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Python stdlib `csv`, pytest / pytest-asyncio, Next.js 16 admin UI.

**Spec:** `docs/superpowers/specs/2026-08-26-commission-wallet-design.md` — §4.5, §4.6, §4.7, §8, §9, §10, §11. Decisions D13–D17.

**Depends on:** Plans 1 and 2 complete and merged. There is nothing to disburse until commission accrues into commission wallets.

---

## Prerequisites

Read before starting:
- Spec §8 in full
- `backend/app/shared/models/money_operations.py` and `backend/app/modules/money_operations/service.py:320` — the approval flow this mirrors
- `backend/app/modules/treasury/service.py:610` `withdraw_from_user` — the posting shape a withdrawal copies

After Plan 2 the Alembic head is `0067`. This plan adds `0068`.

Note on convention: `load_reviews` and `distinct_approver_ids` are duplicated
per-module today (`money_operations` and `user_operations` each hold their own).
Follow that pattern — give `commission_batches` its own copies rather than
extracting a shared helper. Unifying all three is a separate refactor and not
this plan's job.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/shared/models/commission_batches.py` | **Create** — the three tables and their status constants |
| `backend/app/modules/commission_batches/csv_io.py` | **Create** — parse an upload, render a rejects file. Pure functions, no DB, so the format is testable without fixtures |
| `backend/app/modules/commission_batches/validation.py` | **Create** — pass-1 row checks |
| `backend/app/modules/commission_batches/service.py` | **Create** — create, list, approve, reject |
| `backend/app/modules/commission_batches/apply.py` | **Create** — pass-2 re-validation and the postings |
| `backend/app/modules/commission_batches/schemas.py` | **Create** |
| `backend/app/modules/commission_batches/router.py` | **Create** |
| `backend/app/modules/treasury/service.py` | **Modify** — wallet-type parameter on single-user withdraw |
| `backend/alembic/versions/20260826_0068_commission_batches.py` | **Create** |
| `admin-ui/app/(authenticated)/commission-disbursement/` | **Create** |
| `admin-ui/app/(authenticated)/commission-withdrawal/` | **Create** |

Five backend files rather than the usual three because the CSV format, the
validation rules and the postings are independently testable concerns, and a
single `service.py` holding all of them would be well past the size where it
can be reasoned about in one pass.

---

## Task 1: Models and migration

**Files:**
- Create: `backend/app/shared/models/commission_batches.py`
- Modify: `backend/app/shared/models/__init__.py`
- Modify: `backend/app/shared/models/money_operations.py` (the `approval_policies` CHECK)
- Create: `backend/alembic/versions/20260826_0068_commission_batches.py`
- Test: `backend/tests/commission_batches/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commission_batches/__init__.py` (empty) and
`backend/tests/commission_batches/test_models.py`:

```python
"""Batch header, rows and reviews persist with the right constraints (spec §4.5-4.7)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    BATCH_STATUS_PENDING,
    BATCH_TYPE_DISBURSEMENT,
    ROW_STATUS_VALID,
    CommissionBatch,
    CommissionBatchRow,
    Tenant,
)


async def _batch(session: AsyncSession, tenant: Tenant) -> CommissionBatch:
    batch = CommissionBatch(
        tenant_id=tenant.id,
        batch_type=BATCH_TYPE_DISBURSEMENT,
        status=BATCH_STATUS_PENDING,
        file_name="nov.csv",
        row_count_total=2,
        row_count_valid=1,
        amount_total=Decimal("1500"),
        created_by_admin_id="admin-1",
        required_approvals=1,
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return batch


@pytest.mark.asyncio
async def test_batch_and_row_persist(db_session: AsyncSession, test_tenant: Tenant) -> None:
    batch = await _batch(db_session, test_tenant)
    db_session.add(
        CommissionBatchRow(
            batch_id=batch.id,
            row_number=1,
            msisdn="27831234567",
            currency="ZAR",
            amount=Decimal("1500"),
            note="Verified against Nov statement",
            status=ROW_STATUS_VALID,
        )
    )
    await db_session.commit()
    assert batch.status == BATCH_STATUS_PENDING


@pytest.mark.asyncio
async def test_row_number_is_unique_per_batch(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    batch = await _batch(db_session, test_tenant)
    for _ in range(2):
        db_session.add(
            CommissionBatchRow(
                batch_id=batch.id,
                row_number=1,
                msisdn="27831234567",
                currency="ZAR",
                amount=Decimal("1"),
                status=ROW_STATUS_VALID,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_invalid_batch_type_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    db_session.add(
        CommissionBatch(
            tenant_id=test_tenant.id,
            batch_type="nonsense",
            status=BATCH_STATUS_PENDING,
            file_name="x.csv",
            row_count_total=0,
            row_count_valid=0,
            amount_total=Decimal("0"),
            created_by_admin_id="admin-1",
            required_approvals=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commission_batches/test_models.py -v
```

Expected: FAIL — `ImportError: cannot import name 'CommissionBatch'`.

- [ ] **Step 3: Write the models**

Create `backend/app/shared/models/commission_batches.py`:

```python
"""Bulk commission disbursement and withdrawal — Epic B8 (spec 2026-08-26 §4.5-4.6).

Three tables mirroring `money_operations.py` conventions: a header carrying the
approval state, an append-only review thread, and — unlike money_operations —
a ROWS table. That is the reason this is a separate module rather than two new
operation types: a 5,000-row file needs per-row status, which the single-payload
JSONB design cannot hold.

REJECTED is terminal (spec D16). A checker rejects the whole batch and the maker
uploads a corrected file as a NEW batch; there is deliberately no revise-in-place
loop, so no round counter is needed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

BATCH_TYPE_DISBURSEMENT = "disbursement"
BATCH_TYPE_WITHDRAWAL = "withdrawal"
BATCH_TYPES = (BATCH_TYPE_DISBURSEMENT, BATCH_TYPE_WITHDRAWAL)

BATCH_STATUS_PENDING = "PENDING"
BATCH_STATUS_APPROVED = "APPROVED"
BATCH_STATUS_APPLIED = "APPLIED"
BATCH_STATUS_APPLIED_PARTIAL = "APPLIED_PARTIAL"
BATCH_STATUS_REJECTED = "REJECTED"
BATCH_STATUS_WITHDRAWN = "WITHDRAWN"
BATCH_STATUSES = (
    BATCH_STATUS_PENDING,
    BATCH_STATUS_APPROVED,
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_APPLIED_PARTIAL,
    BATCH_STATUS_REJECTED,
    BATCH_STATUS_WITHDRAWN,
)
BATCH_TERMINAL_STATUSES = (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_APPLIED_PARTIAL,
    BATCH_STATUS_REJECTED,
    BATCH_STATUS_WITHDRAWN,
)

ROW_STATUS_VALID = "valid"
ROW_STATUS_REJECTED = "rejected"
ROW_STATUS_POSTED = "posted"
ROW_STATUS_FAILED = "failed"
ROW_STATUSES = (ROW_STATUS_VALID, ROW_STATUS_REJECTED, ROW_STATUS_POSTED, ROW_STATUS_FAILED)


class CommissionBatch(Base):
    """One uploaded disbursement or withdrawal file, pending N-eyes approval."""

    __tablename__ = "commission_batches"
    __table_args__ = (
        CheckConstraint(
            "batch_type IN ('disbursement', 'withdrawal')",
            name="ck_commission_batches_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'APPLIED', 'APPLIED_PARTIAL', "
            "'REJECTED', 'WITHDRAWN')",
            name="ck_commission_batches_status",
        ),
        CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_commission_batches_required_approvals",
        ),
        Index("ix_commission_batches_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    batch_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count_total: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count_valid: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_total: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Withdrawal only — the named operator_adjustment bank mirror the money
    # lands in. NULL for a disbursement, whose destination is derived per row
    # (the earner's own main wallet).
    destination_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    created_by_admin_id: Mapped[str] = mapped_column(String(100), nullable=False)
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class CommissionBatchRow(Base):
    """One line of the uploaded file, with its validation and posting state."""

    __tablename__ = "commission_batch_rows"
    __table_args__ = (
        CheckConstraint(
            "status IN ('valid', 'rejected', 'posted', 'failed')",
            name="ck_commission_batch_rows_status",
        ),
        UniqueConstraint("batch_id", "row_number", name="uq_commission_batch_rows_number"),
        Index("ix_commission_batch_rows_batch_status", "batch_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commission_batches.id"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    msisdn: Mapped[str] = mapped_column(String(30), nullable=False)
    # MANDATORY: a user may hold several commission wallets, so the file must
    # say which one this row moves (spec §4.6).
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Maker-supplied justification for any delta between the wallet balance and
    # the amount moved. The SYSTEM never writes here.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    # Balance at pass-1 validation, with its timestamp — shown to the checker so
    # the delta is visible, and so the staleness is visible too.
    balance_snapshot: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    snapshot_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class CommissionBatchReview(Base):
    """Append-only review thread — one row per maker/checker action."""

    __tablename__ = "commission_batch_reviews"
    __table_args__ = (
        UniqueConstraint("batch_id", "admin_id", name="uq_commission_batch_reviews_approver"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commission_batches.id"), nullable=False, index=True
    )
    admin_id: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
```

Export every model and status constant from `backend/app/shared/models/__init__.py`.

- [ ] **Step 4: Extend the approval-policy CHECK**

In `backend/app/shared/models/money_operations.py`, change
`ck_approval_policies_operation` to include the two new operations:

```python
        CheckConstraint(
            "operation IS NULL OR operation IN ('fund_user', 'withdraw_user', "
            "'adjust_system_wallet', 'create_bank_mirror', "
            "'commission_disbursement', 'commission_withdrawal')",
            name="ck_approval_policies_operation",
        ),
```

This is what lets a tenant require six-eyes on a bulk run while keeping
four-eyes on a single treasury operation (spec §4.7).

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/20260826_0068_commission_batches.py` creating
the three tables with every constraint above, and recreating
`ck_approval_policies_operation` with the extended list. Follow the shape of
migration 0066's CHECK swap: `op.drop_constraint` then
`op.create_check_constraint`. Include a `downgrade` that drops the three tables
and restores the original four-value CHECK.

- [ ] **Step 6: Apply and verify**

```bash
alembic upgrade head && python scripts/check_migrations.py
```

Expected: no drift.

- [ ] **Step 7: Run the test to verify it passes**

```bash
pytest tests/commission_batches/test_models.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/shared/models/ backend/alembic/versions/20260826_0068_commission_batches.py \
  backend/tests/commission_batches/
git commit -m "feat(commission-batches): add batch, row and review models"
```

---

## Task 2: CSV parsing and rejects rendering

Pure functions over strings — no session, no fixtures. That is what makes the
file format cheap to test and cheap to change.

**Files:**
- Create: `backend/app/modules/commission_batches/__init__.py` (empty)
- Create: `backend/app/modules/commission_batches/csv_io.py`
- Test: `backend/tests/commission_batches/test_csv_io.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commission_batches/test_csv_io.py`:

```python
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
    rows = parse_batch_csv(_GOOD)
    assert [r.row_number for r in rows] == [1, 2]


def test_currency_is_upper_cased() -> None:
    rows = parse_batch_csv("msisdn,currency,amount,note\n27831234567,zar,10,\n")
    assert rows[0].currency == "ZAR"


def test_missing_header_column_is_an_error() -> None:
    with pytest.raises(ValueError, match="currency"):
        parse_batch_csv("msisdn,amount,note\n27831234567,10,\n")


def test_unparseable_amount_becomes_a_none_amount_not_an_exception() -> None:
    """A bad amount is a ROW-level reject (D15), never a whole-file failure."""
    rows = parse_batch_csv("msisdn,currency,amount,note\n27831234567,ZAR,abc,\n")
    assert rows[0].amount is None


def test_empty_file_is_an_error() -> None:
    with pytest.raises(ValueError, match="no data rows"):
        parse_batch_csv("msisdn,currency,amount,note\n")


def test_rejects_csv_round_trips_with_reasons() -> None:
    out = render_rejects_csv(
        [
            (ParsedRow(1, "27831234567", "ZAR", Decimal("10"), None), "msisdn_not_found"),
            (ParsedRow(2, "27839999999", "INR", None, "x"), "invalid_amount"),
        ]
    )
    assert out.splitlines()[0] == "row_number,msisdn,currency,amount,note,failure_reason"
    assert "msisdn_not_found" in out
    # The original columns survive, so the maker fixes and re-uploads directly.
    assert "27831234567" in out
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commission_batches/test_csv_io.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the parser**

Create `backend/app/modules/commission_batches/csv_io.py`:

```python
"""Batch CSV parsing and rejects rendering (spec §8.1).

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
REJECTS_COLUMNS = ("row_number", "msisdn", "currency", "amount", "note", "failure_reason")


@dataclass(frozen=True)
class ParsedRow:
    """One data line, structurally parsed but not yet validated.

    Attributes:
        row_number: 1-based, EXCLUDING the header — matches what the maker sees
            in their spreadsheet, so a rejects file is directly actionable.
        amount: None when the cell did not parse as a decimal. Deliberately not
            an exception: a single bad amount is a ROW-level reject (D15), and
            must not fail the whole file.
    """

    row_number: int
    msisdn: str
    currency: str
    amount: Decimal | None
    note: str | None


def parse_batch_csv(content: str) -> list[ParsedRow]:
    """Parse an uploaded batch file into rows.

    Raises:
        ValueError: the header is missing a required column, or the file has no
            data rows. These are FILE-level problems — the maker uploaded the
            wrong thing — as distinct from row-level ones, which are collected
            and reported per row.
    """
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise ValueError("The file has no header row.")

    header = {name.strip().lower() for name in reader.fieldnames}
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}.")

    rows: list[ParsedRow] = []
    for index, raw in enumerate(reader, start=1):
        note = (raw.get("note") or "").strip()
        rows.append(
            ParsedRow(
                row_number=index,
                msisdn=(raw.get("msisdn") or "").strip(),
                currency=(raw.get("currency") or "").strip().upper(),
                amount=_to_decimal(raw.get("amount")),
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
    NEW batch (D15).
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/commission_batches/test_csv_io.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/commission_batches/ backend/tests/commission_batches/test_csv_io.py
git commit -m "feat(commission-batches): parse batch CSV and render rejects"
```

---

## Task 3: Pass-1 row validation

**Files:**
- Create: `backend/app/modules/commission_batches/validation.py`
- Test: `backend/tests/commission_batches/test_validation.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commission_batches/test_validation.py`:

```python
"""Pass-1 validation: every reject reason in spec §8.2, plus the happy path.

The checker must only ever see valid rows, so every one of these fires at
UPLOAD, before the batch reaches an approver.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commission_batches.csv_io import ParsedRow
from app.modules.commission_batches.validation import validate_rows
from app.shared.models import Tenant


def _row(n: int, msisdn: str, currency: str = "ZAR", amount: str = "10") -> ParsedRow:
    return ParsedRow(
        row_number=n, msisdn=msisdn, currency=currency, amount=Decimal(amount), note=None
    )


@pytest.mark.asyncio
async def test_valid_row_resolves_with_a_balance_snapshot(
    db_session: AsyncSession, batch_fixture
) -> None:
    results = await validate_rows(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        rows=[_row(1, batch_fixture.agent_msisdn, amount="50")],
    )
    assert results[0].failure_reason is None
    assert results[0].resolved_account_id == batch_fixture.agent_commission_wallet.id
    assert results[0].balance_snapshot == Decimal("100")


@pytest.mark.asyncio
async def test_unknown_msisdn(db_session: AsyncSession, batch_fixture) -> None:
    results = await validate_rows(
        db_session, tenant_id=batch_fixture.tenant.id, rows=[_row(1, "27000000000")]
    )
    assert results[0].failure_reason == "msisdn_not_found"


@pytest.mark.asyncio
async def test_consumer_is_not_eligible(db_session: AsyncSession, batch_fixture) -> None:
    results = await validate_rows(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        rows=[_row(1, batch_fixture.consumer_msisdn)],
    )
    assert results[0].failure_reason == "user_not_eligible"


@pytest.mark.asyncio
async def test_unknown_currency(db_session: AsyncSession, batch_fixture) -> None:
    results = await validate_rows(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        rows=[_row(1, batch_fixture.agent_msisdn, currency="XXX")],
    )
    assert results[0].failure_reason == "unknown_currency"


@pytest.mark.asyncio
async def test_amount_over_balance(db_session: AsyncSession, batch_fixture) -> None:
    results = await validate_rows(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        rows=[_row(1, batch_fixture.agent_msisdn, amount="1000")],
    )
    assert results[0].failure_reason == "insufficient_commission_balance"


@pytest.mark.asyncio
async def test_zero_and_negative_amounts(db_session: AsyncSession, batch_fixture) -> None:
    results = await validate_rows(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        rows=[
            _row(1, batch_fixture.agent_msisdn, amount="0"),
            _row(2, batch_fixture.agent_msisdn, amount="-5"),
        ],
    )
    assert results[0].failure_reason == "invalid_amount"
    assert results[1].failure_reason == "invalid_amount"


@pytest.mark.asyncio
async def test_unparseable_amount(db_session: AsyncSession, batch_fixture) -> None:
    row = ParsedRow(1, batch_fixture.agent_msisdn, "ZAR", None, None)
    results = await validate_rows(
        db_session, tenant_id=batch_fixture.tenant.id, rows=[row]
    )
    assert results[0].failure_reason == "invalid_amount"


@pytest.mark.asyncio
async def test_duplicate_msisdn_currency_within_the_file(
    db_session: AsyncSession, batch_fixture
) -> None:
    """The FIRST occurrence is kept; later ones reject, so the run is deterministic."""
    results = await validate_rows(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        rows=[
            _row(1, batch_fixture.agent_msisdn, amount="10"),
            _row(2, batch_fixture.agent_msisdn, amount="20"),
        ],
    )
    assert results[0].failure_reason is None
    assert results[1].failure_reason == "duplicate_row"


@pytest.mark.asyncio
async def test_same_msisdn_different_currency_is_not_a_duplicate(
    db_session: AsyncSession, batch_fixture
) -> None:
    results = await validate_rows(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        rows=[
            _row(1, batch_fixture.agent_msisdn, currency="ZAR", amount="10"),
            _row(2, batch_fixture.agent_msisdn, currency="INR", amount="10"),
        ],
    )
    assert results[0].failure_reason is None
    assert results[1].failure_reason != "duplicate_row"
```

Create `backend/tests/commission_batches/conftest.py` providing `batch_fixture`:
a flag-on tenant, an agent with a phone identifier and a ZAR commission wallet
holding exactly `Decimal("100")` (accrued via a real `post_transaction` from the
commission pool, not by inserting a ledger row by hand), an INR instrument and
INR commission wallet, and a consumer with a phone identifier. Expose
`.tenant`, `.agent_msisdn`, `.consumer_msisdn`, `.agent_commission_wallet`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commission_batches/test_validation.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement validation**

Create `backend/app/modules/commission_batches/validation.py`:

```python
"""Pass-1 batch row validation (spec §8.2).

Runs at UPLOAD so the checker only ever sees rows that could post. Every
failure is per-row and recoverable: the maker downloads the rejects, fixes them
and submits a new batch (D15). Nothing here raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.commission_batches.csv_io import ParsedRow
from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    INSTRUMENT_STATUS_ACTIVE,
    Account,
    Instrument,
    User,
    UserIdentifier,
)
from app.shared.utils.identifiers import normalize_identifier

REASON_MSISDN_NOT_FOUND = "msisdn_not_found"
REASON_USER_NOT_ELIGIBLE = "user_not_eligible"
REASON_UNKNOWN_CURRENCY = "unknown_currency"
REASON_WALLET_MISSING = "commission_wallet_missing"
REASON_INVALID_AMOUNT = "invalid_amount"
REASON_INSUFFICIENT = "insufficient_commission_balance"
REASON_DUPLICATE = "duplicate_row"


@dataclass(frozen=True)
class ValidatedRow:
    """A parsed row plus what validation resolved (or why it could not)."""

    parsed: ParsedRow
    resolved_user_id: UUID | None
    resolved_account_id: UUID | None
    balance_snapshot: Decimal | None
    snapshot_at: datetime | None
    failure_reason: str | None


async def validate_rows(
    session: AsyncSession, *, tenant_id: UUID, rows: list[ParsedRow]
) -> list[ValidatedRow]:
    """Validate every row, resolving users, wallets and balances.

    Returns one ValidatedRow per input row, IN ORDER — callers rely on the
    positional correspondence to build the rejects file.

    Duplicate (msisdn, currency) pairs keep the FIRST occurrence and reject the
    rest, so a re-run of the same file produces the same outcome. Same MSISDN
    with a different currency is not a duplicate — a user may legitimately be
    paid out of two commission wallets in one run.
    """
    currencies = {
        code
        for code in (
            await session.execute(
                select(Instrument.code).where(
                    Instrument.tenant_id == tenant_id,
                    Instrument.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                    Instrument.status == INSTRUMENT_STATUS_ACTIVE,
                    Instrument.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    }

    seen: set[tuple[str, str]] = set()
    results: list[ValidatedRow] = []

    for row in rows:
        reason = None
        user = None
        account = None
        balance = None
        snapshot_at = None

        key = (row.msisdn, row.currency)
        if key in seen:
            reason = REASON_DUPLICATE
        elif row.amount is None or row.amount <= Decimal("0"):
            reason = REASON_INVALID_AMOUNT
        elif row.currency not in currencies:
            reason = REASON_UNKNOWN_CURRENCY
        else:
            user = await _resolve_user(session, tenant_id, row.msisdn)
            if user is None:
                reason = REASON_MSISDN_NOT_FOUND
            elif not await is_commission_wallet_eligible(session, tenant_id, user.user_type):
                reason = REASON_USER_NOT_ELIGIBLE
            else:
                account = await _commission_wallet(session, tenant_id, user.id, row.currency)
                if account is None:
                    reason = REASON_WALLET_MISSING
                else:
                    balance, reserved = await derive_balance(session, account.id)
                    balance = balance - reserved
                    snapshot_at = datetime.now(UTC)
                    if row.amount > balance:
                        reason = REASON_INSUFFICIENT

        if reason is None:
            seen.add(key)

        results.append(
            ValidatedRow(
                parsed=row,
                resolved_user_id=user.id if user is not None else None,
                resolved_account_id=account.id if account is not None else None,
                balance_snapshot=balance,
                snapshot_at=snapshot_at,
                failure_reason=reason,
            )
        )

    return results


async def _resolve_user(session: AsyncSession, tenant_id: UUID, msisdn: str) -> User | None:
    """Resolve an MSISDN to a user in THIS tenant, via the canonical form.

    Normalising first is essential: identifiers are stored canonically, so a raw
    "27831234567" from a spreadsheet would otherwise miss a stored "+27 83 123
    4567" and every row would reject as msisdn_not_found.
    """
    canonical = normalize_identifier("phone", msisdn)
    identifier = (
        await session.execute(
            select(UserIdentifier).where(
                UserIdentifier.tenant_id == tenant_id,
                UserIdentifier.identifier_type == "phone",
                UserIdentifier.identifier_value == canonical,
            )
        )
    ).scalar_one_or_none()
    if identifier is None:
        return None
    return (
        await session.execute(
            select(User).where(User.id == identifier.user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


async def _commission_wallet(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, currency: str
) -> Account | None:
    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
                Account.currency == currency,
            )
        )
    ).scalar_one_or_none()
```

Confirm `normalize_identifier`'s import path against
`backend/app/modules/identity/service.py` and match it.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/commission_batches/test_validation.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/commission_batches/validation.py \
  backend/tests/commission_batches/
git commit -m "feat(commission-batches): validate uploaded rows"
```

---

## Task 4: Batch creation

**Files:**
- Create: `backend/app/modules/commission_batches/schemas.py`
- Create: `backend/app/modules/commission_batches/service.py`
- Test: `backend/tests/commission_batches/test_create_batch.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commission_batches/test_create_batch.py`:

```python
"""Batch creation: valid rows staged, bad rows rejected, empty batch refused."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commission_batches.service import create_batch
from app.shared.exceptions import AppHTTPException
from app.shared.models import (
    BATCH_STATUS_PENDING,
    BATCH_TYPE_DISBURSEMENT,
    ROW_STATUS_REJECTED,
    ROW_STATUS_VALID,
    CommissionBatchRow,
)


@pytest.mark.asyncio
async def test_mixed_file_stages_valid_rows_only(
    db_session: AsyncSession, batch_fixture, admin_principal
) -> None:
    content = (
        "msisdn,currency,amount,note\n"
        f"{batch_fixture.agent_msisdn},ZAR,50,Verified\n"
        "27000000000,ZAR,10,Unknown\n"
    )
    batch = await create_batch(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        batch_type=BATCH_TYPE_DISBURSEMENT,
        file_name="nov.csv",
        content=content,
        admin=admin_principal,
    )

    assert batch.status == BATCH_STATUS_PENDING
    assert batch.row_count_total == 2
    assert batch.row_count_valid == 1

    rows = (
        await db_session.execute(
            select(CommissionBatchRow).where(CommissionBatchRow.batch_id == batch.id)
        )
    ).scalars().all()
    by_status = {r.status: r for r in rows}
    assert by_status[ROW_STATUS_VALID].msisdn == batch_fixture.agent_msisdn
    assert by_status[ROW_STATUS_REJECTED].failure_reason == "msisdn_not_found"
    # Rejected rows are PERSISTED, not discarded — the maker downloads them.
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_batch_with_no_valid_rows_is_refused(
    db_session: AsyncSession, batch_fixture, admin_principal
) -> None:
    """Refused outright rather than created empty — nothing for a checker to do."""
    content = "msisdn,currency,amount,note\n27000000000,ZAR,10,\n"
    with pytest.raises(AppHTTPException) as exc:
        await create_batch(
            db_session,
            tenant_id=batch_fixture.tenant.id,
            batch_type=BATCH_TYPE_DISBURSEMENT,
            file_name="bad.csv",
            content=content,
            admin=admin_principal,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_amount_total_counts_valid_rows_only(
    db_session: AsyncSession, batch_fixture, admin_principal
) -> None:
    from decimal import Decimal

    content = (
        "msisdn,currency,amount,note\n"
        f"{batch_fixture.agent_msisdn},ZAR,50,\n"
        "27000000000,ZAR,999,\n"
    )
    batch = await create_batch(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        batch_type=BATCH_TYPE_DISBURSEMENT,
        file_name="nov.csv",
        content=content,
        admin=admin_principal,
    )
    assert Decimal(str(batch.amount_total)) == Decimal("50")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commission_batches/test_create_batch.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `create_batch`**

Create `backend/app/modules/commission_batches/service.py` with:

```python
async def create_batch(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    batch_type: str,
    file_name: str,
    content: str,
    admin: AdminPrincipal,
    destination_account_id: UUID | None = None,
    ip_address: str | None = None,
) -> CommissionBatch:
    """Parse, validate and stage an uploaded batch (spec §8.2).

    Rejected rows are PERSISTED with their reason rather than discarded — the
    maker downloads them as a rejects CSV and re-uploads a corrected NEW batch
    (D15, D16). The checker's queries filter to `valid` rows, so a reject never
    reaches an approver.

    `required_approvals` is snapshotted from `approval_policies` at creation, so
    a policy change mid-review cannot move the goalposts on a live batch.

    Raises:
        AppHTTPException 422 `batch_file_invalid`: the file is structurally
            unusable (bad header, no data rows).
        AppHTTPException 422 `batch_no_valid_rows`: nothing survived validation
            — there would be nothing for a checker to approve.
        AppHTTPException 422 `bank_mirror_required`: a withdrawal batch with no
            destination account.

    Side effects:
        Inserts one CommissionBatch, N CommissionBatchRow, and one audit row.
        Commits once.
    """
```

Body outline — write it out in full:

1. For `BATCH_TYPE_WITHDRAWAL`, require `destination_account_id` and confirm it
   is an `operator_adjustment` account in this tenant; otherwise 422.
2. `parse_batch_csv(content)`, converting its `ValueError` into a 422
   `batch_file_invalid` so a bad upload is a clean client error.
3. `validate_rows(...)`.
4. If no row has `failure_reason is None`, raise 422 `batch_no_valid_rows`.
5. Resolve `required_approvals` from `approval_policies` using the same
   resolution order as `money_operations._resolve_required_approvals`
   ((tenant, operation) → (tenant, NULL) → 1), with operation
   `"commission_disbursement"` or `"commission_withdrawal"`.
6. Insert the `CommissionBatch` with `row_count_total = len(rows)`,
   `row_count_valid` and `amount_total` over valid rows only.
7. Insert one `CommissionBatchRow` per validated row, status `valid` or
   `rejected`, carrying `resolved_user_id`, `resolved_account_id`,
   `balance_snapshot`, `snapshot_at`, `failure_reason`.
8. `record_audit_for_admin(..., action="commission_batch.created", ...)`.
9. `await session.commit()`.

Also implement in the same file:

```python
async def get_batch_rejects_csv(session: AsyncSession, batch: CommissionBatch) -> str:
    """Render this batch's rejected rows as a downloadable CSV (spec §8.2).

    Covers BOTH reject passes: rows rejected at upload (`rejected`) and rows
    that failed at apply because the balance moved (`failed`). The maker fixes
    either kind the same way — correct the data, upload a new batch.
    """
```

Add `schemas.py` with `BatchOut`, `BatchRowOut` (including `balance_snapshot`,
`snapshot_at`, `amount`, a computed `delta`, and `note`) and `BatchListOut`.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/commission_batches/test_create_batch.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/commission_batches/ backend/tests/commission_batches/
git commit -m "feat(commission-batches): create and stage a batch from CSV"
```

---

## Task 5: Approval, rejection and quorum

**Files:**
- Modify: `backend/app/modules/commission_batches/service.py`
- Test: `backend/tests/commission_batches/test_approval.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commission_batches/test_approval.py`:

```python
"""Quorum, self-approval and terminal rejection (spec §8.3, D16)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commission_batches.service import approve_batch, reject_batch
from app.shared.exceptions import (
    BatchDuplicateApprover,
    BatchInvalidState,
    SelfApprovalForbidden,
)
from app.shared.models import BATCH_STATUS_APPLIED, BATCH_STATUS_REJECTED


@pytest.mark.asyncio
async def test_maker_cannot_approve_their_own_batch(
    db_session: AsyncSession, pending_batch, admin_principal
) -> None:
    with pytest.raises(SelfApprovalForbidden):
        await approve_batch(
            db_session, pending_batch.id, pending_batch.tenant_id, admin=admin_principal
        )


@pytest.mark.asyncio
async def test_one_approval_applies_when_quorum_is_one(
    db_session: AsyncSession, pending_batch, checker_principal
) -> None:
    batch = await approve_batch(
        db_session, pending_batch.id, pending_batch.tenant_id, admin=checker_principal
    )
    assert batch.status == BATCH_STATUS_APPLIED


@pytest.mark.asyncio
async def test_same_checker_cannot_approve_twice(
    db_session: AsyncSession, pending_batch_six_eyes, checker_principal
) -> None:
    await approve_batch(
        db_session,
        pending_batch_six_eyes.id,
        pending_batch_six_eyes.tenant_id,
        admin=checker_principal,
    )
    with pytest.raises(BatchDuplicateApprover):
        await approve_batch(
            db_session,
            pending_batch_six_eyes.id,
            pending_batch_six_eyes.tenant_id,
            admin=checker_principal,
        )


@pytest.mark.asyncio
async def test_rejection_is_terminal(
    db_session: AsyncSession, pending_batch, checker_principal
) -> None:
    """No revise-in-place loop (D16) — the maker uploads a fresh batch."""
    batch = await reject_batch(
        db_session,
        pending_batch.id,
        pending_batch.tenant_id,
        admin=checker_principal,
        comment="Totals do not match the November statement",
    )
    assert batch.status == BATCH_STATUS_REJECTED

    with pytest.raises(BatchInvalidState):
        await approve_batch(
            db_session, pending_batch.id, pending_batch.tenant_id, admin=checker_principal
        )


@pytest.mark.asyncio
async def test_rejection_requires_a_comment(
    db_session: AsyncSession, pending_batch, checker_principal
) -> None:
    with pytest.raises(ValueError):
        await reject_batch(
            db_session,
            pending_batch.id,
            pending_batch.tenant_id,
            admin=checker_principal,
            comment="",
        )
```

Add `pending_batch`, `pending_batch_six_eyes` and `checker_principal` to
`backend/tests/commission_batches/conftest.py`. `checker_principal` must be a
DIFFERENT admin id from `admin_principal`, or the self-approval guard fires in
every test.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commission_batches/test_approval.py -v
```

Expected: FAIL — `ImportError` on `approve_batch`.

- [ ] **Step 3: Implement approval and rejection**

Mirror `money_operations/service.py:320` closely, including the ordering that
stages the terminal status BEFORE calling apply so both land in one commit:

```python
async def approve_batch(
    session: AsyncSession,
    batch_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> CommissionBatch:
    """Checker approves; applies once N DISTINCT approvals land (spec §8.4).

    Follows money_operations.approve_money_operation exactly, including staging
    the terminal status BEFORE `apply_batch` runs so the transition and the
    postings commit together — a failure in apply rolls the approval back too.

    Raises:
        BatchNotFound (404).
        BatchInvalidState (409): the batch is not PENDING.
        SelfApprovalForbidden (409): the approver is the maker.
        BatchDuplicateApprover (409): this admin already approved.
    """
    batch = await _load_batch(session, batch_id, tenant_id, for_update=True)
    if batch.status != BATCH_STATUS_PENDING:
        raise BatchInvalidState(batch.status)
    if admin.id == batch.created_by_admin_id:
        raise SelfApprovalForbidden()

    reviews = await load_reviews(session, batch.id)
    approvers = distinct_approver_ids(reviews)
    if admin.id in approvers:
        raise BatchDuplicateApprover()

    _add_review(session, batch, admin_id=admin.id, decision="approved", comment=None)
    _audit(session, admin, batch, "commission_batch.approved", ip_address)

    if len(approvers | {admin.id}) >= batch.required_approvals:
        await apply_batch(session, batch, admin=admin, ip_address=ip_address)
    await session.commit()
    await session.refresh(batch)
    return batch
```

`apply_batch` sets the final status (`APPLIED` or `APPLIED_PARTIAL`) — it is the
only code that knows whether every row posted, so it owns that decision rather
than the caller guessing.

`reject_batch` sets `BATCH_STATUS_REJECTED`, requires a non-empty comment
(raise `ValueError` on empty, which the router surfaces as a 422), adds the
review and the audit row, and commits. `REJECTED` is in
`BATCH_TERMINAL_STATUSES`, so `_load_batch` plus the `PENDING` check makes any
later approval a `BatchInvalidState`.

Add `BatchNotFound` (404), `BatchInvalidState` (409) and `BatchDuplicateApprover`
(409) to `backend/app/shared/exceptions/__init__.py`, following the shapes of
their `MoneyOperation*` equivalents. Reuse the existing `SelfApprovalForbidden`.

Give this module its own `load_reviews` / `distinct_approver_ids` / `_add_review`
helpers, per the per-module convention noted in the Prerequisites.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/commission_batches/test_approval.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/commission_batches/ backend/app/shared/exceptions/__init__.py \
  backend/tests/commission_batches/
git commit -m "feat(commission-batches): maker-checker approval and terminal rejection"
```

---

## Task 6: Apply — postings, re-validation and partial success

**Files:**
- Create: `backend/app/modules/commission_batches/apply.py`
- Test: `backend/tests/commission_batches/test_apply.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commission_batches/test_apply.py`:

```python
"""Apply: postings, drift handling, partial success and idempotency (spec §8.4)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.commission_batches.service import approve_batch
from app.shared.models import (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_APPLIED_PARTIAL,
    ROW_STATUS_FAILED,
    ROW_STATUS_POSTED,
    CommissionBatchRow,
)


async def _rows(session: AsyncSession, batch_id) -> list[CommissionBatchRow]:
    return list(
        (
            await session.execute(
                select(CommissionBatchRow).where(CommissionBatchRow.batch_id == batch_id)
            )
        ).scalars().all()
    )


@pytest.mark.asyncio
async def test_disbursement_moves_commission_to_the_main_wallet(
    db_session: AsyncSession, pending_batch, batch_fixture, checker_principal
) -> None:
    commission_before, _ = await derive_balance(
        db_session, batch_fixture.agent_commission_wallet.id
    )
    main_before, _ = await derive_balance(db_session, batch_fixture.agent_main_wallet.id)

    await approve_batch(
        db_session, pending_batch.id, pending_batch.tenant_id, admin=checker_principal
    )

    commission_after, _ = await derive_balance(
        db_session, batch_fixture.agent_commission_wallet.id
    )
    main_after, _ = await derive_balance(db_session, batch_fixture.agent_main_wallet.id)

    moved = commission_before - commission_after
    assert moved > Decimal("0")
    assert main_after - main_before == moved


@pytest.mark.asyncio
async def test_withdrawal_moves_commission_to_the_bank_mirror(
    db_session: AsyncSession, pending_withdrawal_batch, batch_fixture, checker_principal
) -> None:
    mirror_before, _ = await derive_balance(db_session, batch_fixture.bank_mirror.id)

    await approve_batch(
        db_session,
        pending_withdrawal_batch.id,
        pending_withdrawal_batch.tenant_id,
        admin=checker_principal,
    )

    mirror_after, _ = await derive_balance(db_session, batch_fixture.bank_mirror.id)
    assert mirror_after > mirror_before


@pytest.mark.asyncio
async def test_balance_drift_between_approval_and_apply_yields_partial(
    db_session: AsyncSession, pending_batch, batch_fixture, checker_principal
) -> None:
    """The snapshot is a decision aid, not a guarantee — apply re-checks."""
    await batch_fixture.drain_commission_wallet()

    batch = await approve_batch(
        db_session, pending_batch.id, pending_batch.tenant_id, admin=checker_principal
    )

    assert batch.status == BATCH_STATUS_APPLIED_PARTIAL
    failed = [r for r in await _rows(db_session, batch.id) if r.status == ROW_STATUS_FAILED]
    assert failed
    assert failed[0].failure_reason == "insufficient_commission_balance"


@pytest.mark.asyncio
async def test_all_rows_posting_yields_applied(
    db_session: AsyncSession, pending_batch, checker_principal
) -> None:
    batch = await approve_batch(
        db_session, pending_batch.id, pending_batch.tenant_id, admin=checker_principal
    )
    assert batch.status == BATCH_STATUS_APPLIED
    assert all(
        r.status == ROW_STATUS_POSTED
        for r in await _rows(db_session, batch.id)
        if r.failure_reason is None
    )


@pytest.mark.asyncio
async def test_posted_rows_carry_their_transaction_id(
    db_session: AsyncSession, pending_batch, checker_principal
) -> None:
    batch = await approve_batch(
        db_session, pending_batch.id, pending_batch.tenant_id, admin=checker_principal
    )
    posted = [r for r in await _rows(db_session, batch.id) if r.status == ROW_STATUS_POSTED]
    assert all(r.transaction_id is not None for r in posted)


@pytest.mark.asyncio
async def test_reapplying_is_a_no_op(
    db_session: AsyncSession, pending_batch, batch_fixture, checker_principal
) -> None:
    from app.modules.commission_batches.apply import apply_batch

    batch = await approve_batch(
        db_session, pending_batch.id, pending_batch.tenant_id, admin=checker_principal
    )
    balance_after_first, _ = await derive_balance(
        db_session, batch_fixture.agent_commission_wallet.id
    )

    await apply_batch(db_session, batch, admin=checker_principal)
    await db_session.commit()

    balance_after_second, _ = await derive_balance(
        db_session, batch_fixture.agent_commission_wallet.id
    )
    assert balance_after_second == balance_after_first
```

Add `pending_withdrawal_batch`, `batch_fixture.agent_main_wallet`,
`batch_fixture.bank_mirror` and `batch_fixture.drain_commission_wallet()` to the
conftest. `drain_commission_wallet` posts a real transaction emptying the
wallet, simulating drift between approval and apply.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commission_batches/test_apply.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement apply**

Create `backend/app/modules/commission_batches/apply.py`:

```python
"""Batch execution — pass-2 re-validation and the postings (spec §8.4).

Separate from `service.py` because the approval workflow and the money movement
are independently testable, and because this file is where every ledger
invariant applies.

Two properties this file must never lose:
  - Idempotency per (batch, row). A retried apply must not double-pay, so the
    idempotency key is derived from the row id, not from a timestamp or a
    counter.
  - Per-row isolation. One failing row marks itself `failed` and the batch
    APPLIED_PARTIAL; it never rolls back rows that already posted.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_APPLIED_PARTIAL,
    BATCH_TERMINAL_STATUSES,
    BATCH_TYPE_DISBURSEMENT,
    BATCH_TYPE_WITHDRAWAL,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ROW_STATUS_FAILED,
    ROW_STATUS_POSTED,
    ROW_STATUS_VALID,
    Account,
    CommissionBatch,
    CommissionBatchRow,
)

_TXN_TYPE = {
    BATCH_TYPE_DISBURSEMENT: "commission_disbursement",
    BATCH_TYPE_WITHDRAWAL: "commission_withdrawal",
}


async def apply_batch(
    session: AsyncSession,
    batch: CommissionBatch,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> None:
    """Post every valid row, re-validating under the row lock.

    Balances can move between approval and apply — more commission accrues, or
    a single-user withdrawal lands — so the checker's snapshot is a decision
    aid, not a guarantee. A row that no longer covers its amount is marked
    `failed` with its reason and the batch lands APPLIED_PARTIAL, downloadable
    as a second rejects file.

    Sets the batch's terminal status. Does NOT commit — the caller
    (`approve_batch`) commits, so the status transition and the postings land
    together.
    """
    if batch.status in BATCH_TERMINAL_STATUSES:
        return  # Already applied — re-entry is a no-op (spec §8.4).

    rows = list(
        (
            await session.execute(
                select(CommissionBatchRow).where(
                    CommissionBatchRow.batch_id == batch.id,
                    CommissionBatchRow.status == ROW_STATUS_VALID,
                )
            )
        ).scalars().all()
    )

    failures = 0
    for row in rows:
        try:
            transaction = await _post_row(session, batch, row)
        except AppHTTPException as exc:
            # Per-row isolation: this row failed, the ones already posted stand.
            row.status = ROW_STATUS_FAILED
            row.failure_reason = exc.error_code
            failures += 1
            continue
        row.status = ROW_STATUS_POSTED
        row.transaction_id = transaction.id

    batch.status = (
        BATCH_STATUS_APPLIED_PARTIAL if failures else BATCH_STATUS_APPLIED
    )


async def _post_row(
    session: AsyncSession, batch: CommissionBatch, row: CommissionBatchRow
):
    """Post one row: commission wallet -> main wallet, or -> the bank mirror.

    The DEBIT side is the commission wallet in both cases, so the ledger's
    non-negative floor (invariant #11, third shape) does the balance
    re-validation for us under the FOR UPDATE lock — there is deliberately no
    separate check-then-act read here, which would race exactly the way M-01
    did.

    The CREDIT into a main wallet is cap-exempt: it is an earned payout the
    user already owns, and a max_balance rejection would strand it (spec §8.4).
    """
    destination_id = (
        await _main_wallet_id(session, batch, row)
        if batch.batch_type == BATCH_TYPE_DISBURSEMENT
        else batch.destination_account_id
    )

    amount = Decimal(str(row.amount))
    return await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=batch.tenant_id,
            # Derived from the ROW id, so a retried apply replays rather than
            # double-paying (Pay-PRD-0200).
            idempotency_key=f"commission-batch:{batch.id}:{row.id}",
            transaction_type=_TXN_TYPE[batch.batch_type],
            currency=row.currency,
            amount=amount,
            entries=[
                LedgerEntryRequest(row.resolved_account_id, ENTRY_DEBIT, amount),
                LedgerEntryRequest(destination_id, ENTRY_CREDIT, amount),
            ],
            skip_receive_cap=True,
        ),
    )


async def _main_wallet_id(
    session: AsyncSession, batch: CommissionBatch, row: CommissionBatchRow
) -> UUID:
    """The earner's main wallet in this row's currency.

    Raises:
        AppHTTPException 422 `main_wallet_missing`: unreachable once Plan 1
            provisioning is in place, kept as a backstop so a missing wallet
            fails this ROW rather than the whole batch.
    """
    account = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == batch.tenant_id,
                Account.user_id == row.resolved_user_id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                Account.currency == row.currency,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise AppHTTPException(
            422, "main_wallet_missing", "The earner has no main wallet in this currency."
        )
    return account.id
```

Confirm `AppHTTPException` exposes `error_code`; if the attribute is named
differently, use the real name in the `except` branch.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/commission_batches/test_apply.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Verify the ledger still balances**

```bash
pytest tests/invariants -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/commission_batches/apply.py \
  backend/tests/commission_batches/test_apply.py
git commit -m "feat(commission-batches): apply batches with per-row isolation"
```

---

## Task 7: Router and tenant isolation

**Files:**
- Create: `backend/app/modules/commission_batches/router.py`
- Modify: `backend/app/main.py` (register the router)
- Test: `backend/tests/commission_batches/test_router.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commission_batches/test_router.py`:

```python
"""Endpoint surface and tenant isolation."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_upload_returns_the_validation_summary(
    async_client: AsyncClient, batch_fixture, admin_headers
) -> None:
    content = (
        "msisdn,currency,amount,note\n"
        f"{batch_fixture.agent_msisdn},ZAR,50,Verified\n"
        "27000000000,ZAR,10,Unknown\n"
    )
    response = await async_client.post(
        "/api/v1/commission-batches",
        headers=admin_headers,
        files={"file": ("nov.csv", content, "text/csv")},
        data={"batch_type": "disbursement"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["row_count_total"] == 2
    assert body["row_count_valid"] == 1


@pytest.mark.asyncio
async def test_rejects_download_is_a_csv(
    async_client: AsyncClient, pending_batch, admin_headers
) -> None:
    response = await async_client.get(
        f"/api/v1/commission-batches/{pending_batch.id}/rejects", headers=admin_headers
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert response.text.startswith("row_number,msisdn,currency,amount,note,failure_reason")


@pytest.mark.asyncio
async def test_another_tenants_batch_is_not_visible(
    async_client: AsyncClient, pending_batch, other_tenant_admin_headers
) -> None:
    response = await async_client.get(
        f"/api/v1/commission-batches/{pending_batch.id}",
        headers=other_tenant_admin_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_checker_view_exposes_balance_amount_and_delta(
    async_client: AsyncClient, pending_batch, admin_headers
) -> None:
    """The delta is the whole point of the checker screen (spec §8.3)."""
    response = await async_client.get(
        f"/api/v1/commission-batches/{pending_batch.id}", headers=admin_headers
    )
    row = response.json()["rows"][0]
    assert "balance_snapshot" in row
    assert "snapshot_at" in row
    assert "amount" in row
    assert "delta" in row
    assert "note" in row
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commission_batches/test_router.py -v
```

Expected: FAIL — 404 on every route.

- [ ] **Step 3: Write the router**

Create `backend/app/modules/commission_batches/router.py` with these endpoints,
all admin-authenticated and tenant-scoped from the token (invariant #7), all
business logic delegated to the service (invariant #5):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/commission-batches` | Upload (multipart: `file`, `batch_type`, optional `destination_account_id`) |
| `GET` | `/api/v1/commission-batches` | List, filterable by `batch_type` and `status` |
| `GET` | `/api/v1/commission-batches/{id}` | Detail with rows, each carrying `delta = balance_snapshot - amount` |
| `GET` | `/api/v1/commission-batches/{id}/rejects` | CSV download of `rejected` + `failed` rows |
| `POST` | `/api/v1/commission-batches/{id}/approve` | Checker approval |
| `POST` | `/api/v1/commission-batches/{id}/reject` | Whole-batch rejection with a mandatory comment |

Enforce an upload row cap (spec R6) — reject a file above the cap with a clear
422 rather than parsing it and timing out. Register the router in
`backend/app/main.py` alongside the other module routers.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/commission_batches/test_router.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/commission_batches/router.py backend/app/main.py \
  backend/tests/commission_batches/test_router.py
git commit -m "feat(commission-batches): add the batch API surface"
```

---

## Task 8: Single-user withdrawal from a commission wallet

**Files:**
- Modify: `backend/app/modules/treasury/service.py:305` (`resolve_user_financial_wallet`) and `:610` (`withdraw_from_user`)
- Modify: `backend/app/modules/money_operations/schemas.py`
- Test: `backend/tests/treasury/test_withdraw_commission_wallet.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/treasury/test_withdraw_commission_wallet.py`:

```python
"""Single-user withdrawal can target a commission wallet (spec §9)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.treasury.service import resolve_user_wallet
from app.shared.models import ACCOUNT_TYPE_COMMISSION_WALLET, ACCOUNT_TYPE_FINANCIAL_WALLET


@pytest.mark.asyncio
async def test_resolves_the_commission_wallet_when_asked(
    db_session: AsyncSession, batch_fixture
) -> None:
    account = await resolve_user_wallet(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        user_id=batch_fixture.agent.id,
        currency="ZAR",
        wallet_type="commission_wallet",
    )
    assert account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET


@pytest.mark.asyncio
async def test_defaults_to_the_main_wallet(
    db_session: AsyncSession, batch_fixture
) -> None:
    """Existing payloads carry no wallet_type and must keep working unchanged."""
    account = await resolve_user_wallet(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        user_id=batch_fixture.agent.id,
        currency="ZAR",
    )
    assert account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET


@pytest.mark.asyncio
async def test_withdrawing_more_than_accrued_is_refused(
    db_session: AsyncSession, batch_fixture
) -> None:
    from app.shared.exceptions import InsufficientCommissionBalance
    from app.modules.treasury.service import post_user_withdraw

    balance, _ = await derive_balance(db_session, batch_fixture.agent_commission_wallet.id)
    with pytest.raises(InsufficientCommissionBalance):
        await post_user_withdraw(
            db_session,
            tenant_id=batch_fixture.tenant.id,
            account=batch_fixture.agent_commission_wallet,
            destination_account_id=batch_fixture.bank_mirror.id,
            amount=balance + Decimal("1"),
            idempotency_key="over-withdraw",
        )
```

Match `post_user_withdraw`'s real signature at
`backend/app/modules/treasury/service.py:379` before running.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/treasury/test_withdraw_commission_wallet.py -v
```

Expected: FAIL — `ImportError: cannot import name 'resolve_user_wallet'`.

- [ ] **Step 3: Generalise the resolver**

Rename `resolve_user_financial_wallet` to `resolve_user_wallet` and add the
parameter:

```python
async def resolve_user_wallet(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    currency: str,
    wallet_type: str = "main_wallet",
) -> Account:
    """Resolve one of a user's wallets for a treasury operation (spec §9).

    Args:
        wallet_type: 'main_wallet' (the default, so every existing caller and
            every stored money-operation payload keeps working unchanged) or
            'commission_wallet'.

    Raises:
        AccountNotFound: 404 — the user holds no such wallet in this currency.
    """
    account_type = (
        ACCOUNT_TYPE_COMMISSION_WALLET
        if wallet_type == "commission_wallet"
        else ACCOUNT_TYPE_FINANCIAL_WALLET
    )
```

Keep the body otherwise as-is, swapping the hardcoded constant for
`account_type`. Update every caller — grep for the old name:

```bash
grep -rn "resolve_user_financial_wallet" backend/app/
```

- [ ] **Step 4: Add `wallet_type` to the money-operation payload**

In `backend/app/modules/money_operations/schemas.py`, on the `withdraw_user`
payload schema:

```python
    # Defaults to the main wallet so payloads stored before this change keep
    # validating and applying exactly as they did (spec §9).
    wallet_type: Literal["main_wallet", "commission_wallet"] = "main_wallet"
```

Thread it through `money_operations/apply.py` to `resolve_user_wallet`.

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/treasury/test_withdraw_commission_wallet.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run treasury and money-operations suites**

```bash
pytest tests/treasury tests/money_operations -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/treasury/ backend/app/modules/money_operations/ \
  backend/tests/treasury/test_withdraw_commission_wallet.py
git commit -m "feat(treasury): allow single-user withdrawal from a commission wallet"
```

---

## Task 9: Mobile balance surface

**Files:**
- Modify: `backend/app/modules/identity/service.py:1050-1110` (the mobile payload)
- Modify: `mobile/app/` balance cards — find the file with `grep -rln "balance" mobile/app/`
- Test: `backend/tests/identity/test_mobile_commission_balance.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/identity/test_mobile_commission_balance.py`:

```python
"""Mobile shows accrued commission as a separate, non-spendable balance (spec §10)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import ACCOUNT_TYPE_COMMISSION_WALLET


@pytest.mark.asyncio
async def test_mobile_payload_marks_commission_non_spendable(
    db_session: AsyncSession, batch_fixture
) -> None:
    from app.modules.identity.service import get_mobile_home

    payload = await get_mobile_home(
        db_session, batch_fixture.tenant.id, batch_fixture.agent.id
    )

    commission = next(
        a for a in payload["accounts"] if a["account_type"] == ACCOUNT_TYPE_COMMISSION_WALLET
    )
    assert commission["spendable"] is False
    assert commission["balance"] > 0
```

Match the mobile payload function's real name at
`backend/app/modules/identity/service.py:1050`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/identity/test_mobile_commission_balance.py -v
```

Expected: FAIL — `KeyError: 'spendable'`.

- [ ] **Step 3: Add the flag to the mobile payload**

Apply the same `spendable` derivation Plan 1 Task 12 added to the admin
payload — an explicit `account_type == ACCOUNT_TYPE_FINANCIAL_WALLET` test, not
a balance test.

- [ ] **Step 4: Render it in the app**

In the mobile balance cards, render a non-spendable account as a distinct,
visually secondary card labelled "Accrued commission", with a one-line
explanation that it becomes spendable after a disbursement run. Do not include
it in any headline total.

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/identity/test_mobile_commission_balance.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/identity/ backend/tests/identity/ mobile/app/
git commit -m "feat(mobile): show accrued commission as a non-spendable balance"
```

---

## Task 10: Admin UI — the two menus

**Files:**
- Create: `admin-ui/app/(authenticated)/commission-disbursement/{page.tsx,_actions.ts,_components/}`
- Create: `admin-ui/app/(authenticated)/commission-withdrawal/{page.tsx,_actions.ts,_components/}`
- Modify: the sidebar navigation

Follow an existing maker-checker screen as the template:

```bash
ls admin-ui/app/\(authenticated\)/ | grep -i "operation\|approval"
```

- [ ] **Step 1: Build the shared batch components**

Both menus are the same flow with different labels and one extra field, so
build the pieces once in a shared `_components` directory and import them into
both routes rather than duplicating:

- `BatchUploadForm` — file picker, submit, and the validation summary returned by the POST (total rows, valid rows, total amount, a "Download rejected rows" button when any row rejected)
- `BatchRowTable` — MSISDN, currency, balance snapshot with its as-of timestamp, amount, **delta**, note
- `BatchApprovalPanel` — approve, or reject-whole-batch with a mandatory comment

```tsx
// The delta column is the reason this screen exists (spec §8.3): it makes
// "accrued R1,620, paying R1,500" visible at a glance, with the maker's note
// supplying the why. Render a non-zero delta prominently — it is the signal
// the checker is here to evaluate, not an incidental column.
```

- [ ] **Step 2: Add the withdrawal-only bank-mirror picker**

The withdrawal route adds a required destination selector listing the tenant's
named `operator_adjustment` bank mirrors. Disbursement has no such control —
its destination is each earner's own main wallet.

- [ ] **Step 3: Show the as-of timestamp honestly**

```tsx
// The snapshot can be stale by the time the checker looks, and apply
// re-validates under the row lock. Showing the timestamp is what stops the
// checker treating the number as a guarantee; APPLIED_PARTIAL plus a second
// rejects file is what happens when it has moved.
```

- [ ] **Step 4: Add both menus to the sidebar**

Place them together under the existing money-operations grouping, permission-
gated the same way the treasury screens are.

- [ ] **Step 5: Verify by hand**

```bash
cd admin-ui && npm run dev
```

Walk both flows end to end: upload a mixed file, download the rejects, confirm
the checker table shows the delta and the note, reject a batch and confirm the
maker must re-upload, approve one and confirm the balances move.

- [ ] **Step 6: Commit**

```bash
git add admin-ui/app/\(authenticated\)/commission-disbursement/ \
  admin-ui/app/\(authenticated\)/commission-withdrawal/ admin-ui/
git commit -m "feat(admin-ui): commission disbursement and withdrawal menus"
```

---

## Task 11: Reconciliation test

The spec requires accrual totals to reconcile exactly to the ledger. This is
the test that proves the statement is derived rather than a second source of
truth.

**Files:**
- Test: `backend/tests/commission_batches/test_reconciliation.py`

- [ ] **Step 1: Write the test**

```python
"""Batch totals reconcile exactly to the ledger (spec §14).

If this ever fails, the batch screens have become a second source of truth
about money — which is the failure mode the append-only ledger exists to
prevent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commission_batches.service import approve_batch
from app.shared.models import ENTRY_CREDIT, ENTRY_DEBIT, LedgerEntry


@pytest.mark.asyncio
async def test_disbursed_total_equals_the_ledger_movement(
    db_session: AsyncSession, pending_batch, batch_fixture, checker_principal
) -> None:
    wallet_id = batch_fixture.agent_commission_wallet.id

    async def net() -> Decimal:
        result = await db_session.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.case(
                            (LedgerEntry.entry_type == ENTRY_CREDIT, LedgerEntry.amount),
                            else_=-LedgerEntry.amount,
                        )
                    ),
                    0,
                )
            ).where(LedgerEntry.account_id == wallet_id)
        )
        return Decimal(str(result.scalar_one()))

    before = await net()
    batch = await approve_batch(
        db_session, pending_batch.id, pending_batch.tenant_id, admin=checker_principal
    )
    after = await net()

    assert before - after == Decimal(str(batch.amount_total))
```

Match the `func.case` call style against
`backend/tests/invariants/test_ledger_sum_to_zero.py`, which already does this
aggregation — reuse its exact form rather than inventing a second one.

- [ ] **Step 2: Run it**

```bash
pytest tests/commission_batches/test_reconciliation.py -v
```

Expected: PASS. If it fails, the bug is in Task 6, not in this test.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/commission_batches/test_reconciliation.py
git commit -m "test(commission-batches): reconcile batch totals to the ledger"
```

---

## Task 12: Documentation and full verification

- [ ] **Step 1: Update the PRD and epics**

Add the commission-wallet requirements to `docs/02-prd.md` with `Pay-PRD-####`
IDs, and mark Epic B8 in `docs/BACKLOG.md` as delivered, pointing at the spec
and these three plans. Add a design doc under `docs/design/` describing the
commission-batches module, following the conventions of its siblings.

- [ ] **Step 2: Run everything**

```bash
cd backend && make test && make check
```

Expected: all green, including `tests/invariants`.

- [ ] **Step 3: Full manual walkthrough**

```bash
make seed && make dev
```

1. Cash in as the seeded agent — commission accrues to their commission wallet, the super-agent's parent commission accrues to theirs
2. Confirm the agent's spendable balance excludes it, in both admin and mobile
3. Upload a disbursement CSV with one good and one bad row — download the rejects, confirm the reason
4. Approve as a different admin — confirm the money lands in the main wallet
5. Upload a withdrawal CSV against a bank mirror — approve — confirm the mirror balance rises
6. Reject a batch — confirm it is terminal and the maker must re-upload

- [ ] **Step 4: Commit**

```bash
git add docs/
git commit -m "docs(commission-wallets): PRD requirements, epic status and design doc"
```

---

## Done when

- An operator can upload a CSV of MSISDN / currency / amount / note and see valid and rejected rows separated, with reasons
- Rejected rows download as a re-uploadable CSV
- A checker sees each row's wallet balance, the amount, the delta and the maker's note before approving
- Whole-batch rejection is terminal and sends the maker back to a fresh upload
- Approval at quorum posts commission → main wallet (disbursement) or → bank mirror (withdrawal)
- A balance that moved between approval and apply produces `APPLIED_PARTIAL` and a second rejects file, never a silent partial
- Batch totals reconcile exactly to the ledger
- Single-user treasury withdrawal can target a commission wallet
- `make test` and `make check` are green

**This completes the commission wallet epic.** Spec: `docs/superpowers/specs/2026-08-26-commission-wallet-design.md`.
