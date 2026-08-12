# Segmentation Phase 1 (Groups + Criteria Engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn static segments into a criteria-driven engine: segment groups, a versioned criteria DSL, a batch evaluator with exclusive-within-group tiers, seeded Gold/Silver/Bronze-style defaults, and a group-sectioned admin UI with a manual criteria builder.

**Architecture:** New `segment_groups` table + `criteria`/`priority` columns on `segments` + `source` on `user_segments`. A Pydantic `SegmentCriteria` schema and a metric registry are the single contract; a Celery-beat evaluator recomputes membership per tenant (set-based aggregates, highest-priority-wins per group, `source='criteria'` rows only). Spec: `docs/superpowers/specs/2026-08-12-ai-segmentation-design.md` (Phase 2 AI layer is a separate plan).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic v2 + Celery/Redis (backend); Next.js 16 App Router + Vitest (admin UI).

**Conventions that bind every task:** repo coding guidelines (file+function docstrings, Google style), no raw SQL, tenant_id on every query, DDL only via Alembic, routers contain no logic. Backend tests run against the real test DB — **one suite at a time** (shared test DB, see CLAUDE.md §7 gotchas). Run backend commands from `backend/` with the venv active (`source .venv/bin/activate`).

---

### Task 1: Models + migration (segment_groups, segment criteria columns, user_segments.source)

**Files:**
- Modify: `backend/app/shared/models/segments.py`
- Modify: `backend/app/shared/models/__init__.py` (export `SegmentGroup`)
- Create: `backend/alembic/versions/20260812_0052_segment_groups_and_criteria.py`
- Test: `backend/tests/segments/test_segment_groups_model.py`

- [ ] **Step 1: Write the failing test**

```python
"""Model-level tests for segment groups and dynamic-segment columns.

Verifies the Task-1 schema: a SegmentGroup row, a Segment carrying
group_id/criteria/priority, and the user_segments.source discriminator.
"""
import uuid

import pytest
from sqlalchemy import select

from app.shared.models import Segment, SegmentGroup, UserSegment


@pytest.mark.asyncio
async def test_segment_group_roundtrip_and_dynamic_segment_columns(
    db_session, test_tenant, test_user
):
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()

    segment = Segment(
        tenant_id=test_tenant.id,
        group_id=group.id,
        name="Gold",
        priority=3,
        criteria={
            "v": 1,
            "op": "AND",
            "conditions": [{"metric": "txn_count", "window_days": 90, "gte": 20}],
        },
    )
    db_session.add(segment)
    await db_session.flush()

    membership = UserSegment(
        user_id=test_user.id, segment_id=segment.id, source="criteria"
    )
    db_session.add(membership)
    await db_session.flush()

    row = (
        await db_session.execute(select(Segment).where(Segment.id == segment.id))
    ).scalar_one()
    assert row.group_id == group.id
    assert row.priority == 3
    assert row.criteria["conditions"][0]["metric"] == "txn_count"
    assert row.is_system is False
    assert row.last_evaluated_at is None

    m = (
        await db_session.execute(
            select(UserSegment).where(UserSegment.segment_id == segment.id)
        )
    ).scalar_one()
    assert m.source == "criteria"


@pytest.mark.asyncio
async def test_segment_group_name_unique_per_tenant_only(
    db_session, test_tenant, second_tenant
):
    db_session.add(SegmentGroup(tenant_id=test_tenant.id, name="Loyalty"))
    db_session.add(SegmentGroup(tenant_id=second_tenant.id, name="Loyalty"))
    await db_session.flush()  # different tenants: OK
    assert True
```

Note: `db_session`, `test_tenant`, `test_user` come from `backend/tests/conftest.py`. If `second_tenant` does not exist there, check `tests/conftest.py` for the second-tenant fixture name used by existing isolation tests (e.g. `other_tenant`) and use that; add no new fixtures.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/segments/test_segment_groups_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'SegmentGroup'`

- [ ] **Step 3: Extend the models**

In `backend/app/shared/models/segments.py`, replace the file docstring's "dynamic segments are deferred to Phase 2" note (they no longer are) and add/extend (keep existing imports style; add `Boolean, Integer, TIMESTAMP` and `JSONB`):

```python
"""Segment, SegmentGroup + UserSegment models — Epic 10 / WAL-79 + segmentation Phase 1.

Segments live inside groups (one lens per group, e.g. Customer Loyalty).
A segment with non-null `criteria` is dynamic: the batch evaluator
(app/modules/segments/evaluator.py) computes its membership; within a
group membership is exclusive and the highest `priority` match wins.
`criteria IS NULL` segments keep today's manual, admin-assigned behaviour.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class SegmentGroup(Base):
    """A segmentation lens (e.g. Customer Loyalty) holding exclusive tiers."""

    __tablename__ = "segment_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_segment_groups_name_per_tenant"),
        Index("ix_segment_groups_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Seeded groups (incl. the "General" backfill group): rename/delete protected.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
```

On the existing `Segment` class add columns (after `description`) and an index in `__table_args__` (`Index("ix_segments_group", "group_id")`):

```python
    # Every segment belongs to exactly one group (backfilled to "General").
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segment_groups.id"), nullable=False
    )
    # NULL = static/manual segment (legacy behaviour). Non-null = dynamic;
    # shape is validated by app.modules.segments.criteria.SegmentCriteria.
    criteria: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Within an exclusive group the highest matching priority wins (Gold=3 > Bronze=1).
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
```

On `UserSegment` add:

```python
    # 'manual' = admin-assigned (never touched by the evaluator); 'criteria' = computed.
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="manual")
```

Export `SegmentGroup` in `backend/app/shared/models/__init__.py` next to `Segment`.

- [ ] **Step 4: Write the migration**

Create `backend/alembic/versions/20260812_0052_segment_groups_and_criteria.py`. Set `down_revision` to the current head (run `alembic heads` — expected `0051`). The backfill creates one "General" system group **per tenant that has segments** and points existing segments at it:

```python
"""segment_groups table + dynamic-segment columns + user_segments.source.

Backfills a per-tenant system group "General" and attaches every existing
segment to it so segments.group_id can be NOT NULL.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segment_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_segment_groups_name_per_tenant"),
    )
    op.create_index("ix_segment_groups_tenant", "segment_groups", ["tenant_id"])

    op.add_column("segments", sa.Column("group_id", UUID(as_uuid=True),
                  sa.ForeignKey("segment_groups.id"), nullable=True))
    op.add_column("segments", sa.Column("criteria", JSONB(), nullable=True))
    op.add_column("segments", sa.Column("priority", sa.Integer(), nullable=False,
                  server_default="0"))
    op.add_column("segments", sa.Column("is_system", sa.Boolean(), nullable=False,
                  server_default="false"))
    op.add_column("segments", sa.Column("last_evaluated_at",
                  sa.TIMESTAMP(timezone=True), nullable=True))

    # Backfill: one "General" system group per tenant that already has segments.
    # Core-table INSERT..SELECT expressed with sqlalchemy.text is acceptable in
    # migrations (data backfill, not app code).
    op.execute(sa.text(
        "INSERT INTO segment_groups (id, tenant_id, name, description, is_system) "
        "SELECT gen_random_uuid(), t.tenant_id, 'General', "
        "'Auto-created for pre-existing segments.', true "
        "FROM (SELECT DISTINCT tenant_id FROM segments) t"
    ))
    op.execute(sa.text(
        "UPDATE segments s SET group_id = g.id FROM segment_groups g "
        "WHERE g.tenant_id = s.tenant_id AND g.name = 'General'"
    ))
    op.alter_column("segments", "group_id", nullable=False)
    op.create_index("ix_segments_group", "segments", ["group_id"])

    op.add_column("user_segments", sa.Column("source", sa.String(10), nullable=False,
                  server_default="'manual'"))


def downgrade() -> None:
    op.drop_column("user_segments", "source")
    op.drop_index("ix_segments_group", table_name="segments")
    op.drop_column("segments", "last_evaluated_at")
    op.drop_column("segments", "is_system")
    op.drop_column("segments", "priority")
    op.drop_column("segments", "criteria")
    op.drop_column("segments", "group_id")
    op.drop_index("ix_segment_groups_tenant", table_name="segment_groups")
    op.drop_table("segment_groups")
```

- [ ] **Step 5: Apply + check migrations**

Run: `alembic upgrade head && python ../scripts/check_migrations.py`
Expected: upgrade runs clean; check_migrations reports no drift. (If `server_default="'manual'"` renders wrong quotes, use `sa.text("'manual'")`.)

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/segments/test_segment_groups_model.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add app/shared/models/segments.py app/shared/models/__init__.py \
  alembic/versions/20260812_0052_segment_groups_and_criteria.py \
  tests/segments/test_segment_groups_model.py
git commit -m "feat(segments): segment_groups table + criteria/priority columns + membership source"
```

---

### Task 2: Criteria DSL schema (`SegmentCriteria`)

**Files:**
- Create: `backend/app/modules/segments/criteria.py`
- Test: `backend/tests/segments/test_criteria_schema.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Validation tests for the segment criteria DSL (spec §3)."""
import pytest
from pydantic import ValidationError

from app.modules.segments.criteria import SegmentCriteria


def valid(payload):
    return SegmentCriteria.model_validate(payload)


def test_minimal_and_criteria_validates():
    c = valid({"v": 1, "op": "AND", "conditions": [
        {"metric": "txn_sum", "txn_type": "p2p", "window_days": 90, "gte": 5000}]})
    assert c.conditions[0].metric == "txn_sum"


def test_or_with_multiple_comparators():
    c = valid({"v": 1, "op": "OR", "conditions": [
        {"metric": "days_since_last_txn", "lte": 14},
        {"metric": "account_age_days", "gte": 1, "lte": 30}]})
    assert c.op == "OR"


def test_unknown_metric_rejected():
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND",
               "conditions": [{"metric": "shoe_size", "gte": 1}]})


def test_condition_without_comparator_rejected():
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": [{"metric": "txn_count"}]})


def test_filters_rejected_on_non_transactional_metric():
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": [
            {"metric": "account_age_days", "txn_type": "p2p", "gte": 1}]})
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": [
            {"metric": "wallet_balance", "window_days": 7, "gte": 1}]})


def test_empty_conditions_and_nesting_and_bad_version_rejected():
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": []})
    with pytest.raises(ValidationError):
        valid({"v": 2, "op": "AND",
               "conditions": [{"metric": "txn_count", "gte": 1}]})
    with pytest.raises(ValidationError):  # nested op object is not a condition
        valid({"v": 1, "op": "AND", "conditions": [
            {"op": "OR", "conditions": [{"metric": "txn_count", "gte": 1}]}]})


def test_window_days_bounds():
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": [
            {"metric": "txn_count", "window_days": 0, "gte": 1}]})
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": [
            {"metric": "txn_count", "window_days": 366, "gte": 1}]})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/segments/test_criteria_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.segments.criteria`

- [ ] **Step 3: Implement the schema**

```python
"""Segment criteria DSL (v1) — the single contract for dynamic segments.

Shared by: manual builder validation, seed data, the evaluator, and (Phase 2)
the AI draft compiler. Spec: docs/superpowers/specs/2026-08-12-ai-segmentation-design.md §3.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Metric names must stay in sync with app.modules.segments.metrics.METRIC_BUILDERS
# (the registry asserts this at import time — see Task 3).
TRANSACTIONAL_METRICS = {"txn_count", "txn_sum"}
WINDOWED_METRICS = TRANSACTIONAL_METRICS | {"points_redeemed", "rewards_earned"}
ALL_METRICS = WINDOWED_METRICS | {
    "wallet_balance",
    "points_balance",
    "account_age_days",
    "days_since_last_txn",
    "referral_count",
}

MetricName = Literal[
    "txn_count", "txn_sum", "wallet_balance", "points_balance",
    "points_redeemed", "rewards_earned", "account_age_days",
    "days_since_last_txn", "referral_count",
]


class Condition(BaseModel):
    """One metric threshold. At least one comparator must be present."""

    model_config = ConfigDict(extra="forbid")

    metric: MetricName
    txn_type: str | None = Field(default=None, max_length=50)
    window_days: int | None = Field(default=None, ge=1, le=365)
    gte: float | None = None
    lte: float | None = None
    eq: float | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "Condition":
        """Reject comparator-less conditions and filters on unsupported metrics."""
        if self.gte is None and self.lte is None and self.eq is None:
            raise ValueError("condition needs at least one of gte/lte/eq")
        if self.txn_type is not None and self.metric not in TRANSACTIONAL_METRICS:
            raise ValueError(f"txn_type not allowed on metric '{self.metric}'")
        if self.window_days is not None and self.metric not in WINDOWED_METRICS:
            raise ValueError(f"window_days not allowed on metric '{self.metric}'")
        return self


class SegmentCriteria(BaseModel):
    """Top-level criteria document: one AND/OR over 1-10 flat conditions."""

    model_config = ConfigDict(extra="forbid")

    v: Literal[1]
    op: Literal["AND", "OR"]
    conditions: list[Condition] = Field(min_length=1, max_length=10)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/segments/test_criteria_schema.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/modules/segments/criteria.py tests/segments/test_criteria_schema.py
git commit -m "feat(segments): criteria DSL v1 schema (SegmentCriteria)"
```

---

### Task 3: Metric registry

**Files:**
- Create: `backend/app/modules/segments/metrics.py`
- Test: `backend/tests/segments/test_metrics.py`

Each metric is an async builder returning `dict[UUID, Decimal]` (user_id → value) for one tenant + filter combo. Missing users mean value 0 (or a large number for `days_since_last_txn` when the user never transacted).

- [ ] **Step 1: Write the failing tests**

```python
"""Per-metric correctness tests for the segment metric registry.

Each test seeds minimal rows through the ORM and asserts the per-user
value map. Uses the shared conftest fixtures (real Postgres test DB).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.modules.segments.metrics import METRIC_BUILDERS, compute_metric
from app.shared.models import Transaction, User


def _txn(tenant_id, user_id, amount, txn_type="p2p", status="COMPLETED", days_ago=0):
    """Minimal COMPLETED transaction row for metric tests."""
    return Transaction(
        tenant_id=tenant_id,
        idempotency_key=f"k-{user_id}-{amount}-{txn_type}-{days_ago}",
        transaction_type=txn_type,
        status=status,
        initiated_by=user_id,
        amount=Decimal(amount),
        currency="ZAR",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )


def test_registry_matches_dsl_vocabulary():
    from app.modules.segments.criteria import ALL_METRICS
    assert set(METRIC_BUILDERS) == ALL_METRICS


@pytest.mark.asyncio
async def test_txn_count_with_type_and_window(db_session, test_tenant, test_user):
    db_session.add_all([
        _txn(test_tenant.id, test_user.id, "10"),
        _txn(test_tenant.id, test_user.id, "20"),
        _txn(test_tenant.id, test_user.id, "30", txn_type="airtime"),
        _txn(test_tenant.id, test_user.id, "40", days_ago=120),
        _txn(test_tenant.id, test_user.id, "50", status="FAILED"),
    ])
    await db_session.flush()

    values = await compute_metric(
        db_session, test_tenant.id, "txn_count", txn_type="p2p", window_days=90
    )
    assert values[test_user.id] == Decimal(2)


@pytest.mark.asyncio
async def test_txn_sum_scopes_to_tenant(db_session, test_tenant, test_user):
    db_session.add(_txn(test_tenant.id, test_user.id, "12.50"))
    await db_session.flush()
    values = await compute_metric(db_session, test_tenant.id, "txn_sum")
    assert values[test_user.id] == Decimal("12.50")


@pytest.mark.asyncio
async def test_account_age_days(db_session, test_tenant, test_user):
    values = await compute_metric(db_session, test_tenant.id, "account_age_days")
    assert values[test_user.id] >= Decimal(0)


@pytest.mark.asyncio
async def test_days_since_last_txn_defaults_large_for_never_transacted(
    db_session, test_tenant, test_user
):
    values = await compute_metric(db_session, test_tenant.id, "days_since_last_txn")
    # No transactions seeded: treated as "very long ago" (sentinel 99999).
    assert values[test_user.id] == Decimal(99999)

    db_session.add(_txn(test_tenant.id, test_user.id, "10", days_ago=3))
    await db_session.flush()
    values = await compute_metric(db_session, test_tenant.id, "days_since_last_txn")
    assert Decimal(2) <= values[test_user.id] <= Decimal(4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/segments/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.segments.metrics`

- [ ] **Step 3: Implement the registry**

```python
"""Metric registry for dynamic segments — name → set-based value builder.

Every builder computes ONE aggregate per tenant as {user_id: Decimal},
covering all users of the tenant in a single query (no per-user loops).
Adding a metric = add a builder here + the name in criteria.ALL_METRICS;
an import-time assert keeps the two in sync.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments.criteria import ALL_METRICS
from app.shared.models import (
    Account,
    LedgerEntry,
    Redemption,
    Referral,
    RewardEvent,
    Transaction,
    User,
)
from app.shared.models.accounts import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
)

# Users who never transacted sort as "very long ago" for recency criteria.
NEVER_TRANSACTED_DAYS = Decimal(99999)

Builder = Callable[..., Awaitable[dict[UUID, Decimal]]]


def _window_start(window_days: int | None) -> datetime | None:
    """Lower created_at bound for a rolling window, or None for lifetime."""
    if window_days is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=window_days)


async def _rows_to_map(session: AsyncSession, stmt) -> dict[UUID, Decimal]:
    """Execute a (user_id, value) select into a {user_id: Decimal} map."""
    result = await session.execute(stmt)
    return {row[0]: Decimal(row[1]) for row in result.all() if row[0] is not None}


async def _txn_aggregate(
    session: AsyncSession,
    tenant_id: UUID,
    agg,
    txn_type: str | None,
    window_days: int | None,
) -> dict[UUID, Decimal]:
    """Shared COMPLETED-transactions aggregate grouped by initiator."""
    stmt = (
        select(Transaction.initiated_by, agg)
        .where(Transaction.tenant_id == tenant_id, Transaction.status == "COMPLETED")
        .group_by(Transaction.initiated_by)
    )
    if txn_type is not None:
        stmt = stmt.where(Transaction.transaction_type == txn_type)
    start = _window_start(window_days)
    if start is not None:
        stmt = stmt.where(Transaction.created_at >= start)
    return await _rows_to_map(session, stmt)


async def txn_count(session, tenant_id, *, txn_type=None, window_days=None):
    """COMPLETED transaction count per initiating user."""
    return await _txn_aggregate(session, tenant_id, func.count(), txn_type, window_days)


async def txn_sum(session, tenant_id, *, txn_type=None, window_days=None):
    """COMPLETED transaction amount sum per initiating user."""
    return await _txn_aggregate(
        session, tenant_id, func.coalesce(func.sum(Transaction.amount), 0),
        txn_type, window_days,
    )


async def _balance(session, tenant_id, account_type):
    """Signed COMPLETED ledger sum per user for one account type.

    Mirrors ledger.service.sum_completed_balance (CREDIT +, DEBIT -),
    set-based across every user account of the tenant.
    """
    signed = func.coalesce(
        func.sum(
            case((LedgerEntry.entry_type == "CREDIT", LedgerEntry.amount),
                 else_=-LedgerEntry.amount)
        ),
        0,
    )
    stmt = (
        select(Account.user_id, signed)
        .join(LedgerEntry, LedgerEntry.account_id == Account.id)
        .where(
            Account.tenant_id == tenant_id,
            Account.account_type == account_type,
            Account.user_id.is_not(None),
            LedgerEntry.status == "COMPLETED",
        )
        .group_by(Account.user_id)
    )
    return await _rows_to_map(session, stmt)


async def wallet_balance(session, tenant_id, **_):
    """Financial-wallet balance per user."""
    return await _balance(session, tenant_id, ACCOUNT_TYPE_FINANCIAL_WALLET)


async def points_balance(session, tenant_id, **_):
    """Points-account balance per user."""
    return await _balance(session, tenant_id, ACCOUNT_TYPE_POINTS)


async def points_redeemed(session, tenant_id, *, window_days=None, **_):
    """COMPLETED redemption points per user."""
    stmt = (
        select(Redemption.user_id, func.coalesce(func.sum(Redemption.points_amount), 0))
        .where(Redemption.tenant_id == tenant_id, Redemption.status == "COMPLETED")
        .group_by(Redemption.user_id)
    )
    start = _window_start(window_days)
    if start is not None:
        stmt = stmt.where(Redemption.created_at >= start)
    return await _rows_to_map(session, stmt)


async def rewards_earned(session, tenant_id, *, window_days=None, **_):
    """Reward events per user (tenant-scoped through users — RewardEvent has no tenant_id)."""
    stmt = (
        select(RewardEvent.user_id, func.count())
        .join(User, User.id == RewardEvent.user_id)
        .where(User.tenant_id == tenant_id)
        .group_by(RewardEvent.user_id)
    )
    start = _window_start(window_days)
    if start is not None:
        stmt = stmt.where(RewardEvent.created_at >= start)
    return await _rows_to_map(session, stmt)


async def account_age_days(session, tenant_id, **_):
    """Days since signup per user."""
    age = func.extract("epoch", func.now() - User.created_at) / 86400
    stmt = select(User.id, age).where(User.tenant_id == tenant_id)
    return await _rows_to_map(session, stmt)


async def days_since_last_txn(session, tenant_id, **_):
    """Days since the user's last COMPLETED transaction (99999 if never)."""
    last = func.max(Transaction.created_at)
    days = func.extract("epoch", func.now() - last) / 86400
    stmt = (
        select(Transaction.initiated_by, days)
        .where(Transaction.tenant_id == tenant_id, Transaction.status == "COMPLETED")
        .group_by(Transaction.initiated_by)
    )
    values = await _rows_to_map(session, stmt)
    users = await session.execute(select(User.id).where(User.tenant_id == tenant_id))
    for (user_id,) in users.all():
        values.setdefault(user_id, NEVER_TRANSACTED_DAYS)
    return values


async def referral_count(session, tenant_id, **_):
    """Rewarded referrals per referrer."""
    stmt = (
        select(Referral.referrer_user_id, func.count())
        .where(Referral.tenant_id == tenant_id, Referral.status == "rewarded")
        .group_by(Referral.referrer_user_id)
    )
    return await _rows_to_map(session, stmt)


METRIC_BUILDERS: dict[str, Builder] = {
    "txn_count": txn_count,
    "txn_sum": txn_sum,
    "wallet_balance": wallet_balance,
    "points_balance": points_balance,
    "points_redeemed": points_redeemed,
    "rewards_earned": rewards_earned,
    "account_age_days": account_age_days,
    "days_since_last_txn": days_since_last_txn,
    "referral_count": referral_count,
}

# Registry and DSL vocabulary must never drift.
assert set(METRIC_BUILDERS) == ALL_METRICS


async def compute_metric(
    session: AsyncSession,
    tenant_id: UUID,
    metric: str,
    *,
    txn_type: str | None = None,
    window_days: int | None = None,
) -> dict[UUID, Decimal]:
    """Dispatch one metric computation to its registered builder."""
    return await METRIC_BUILDERS[metric](
        session, tenant_id, txn_type=txn_type, window_days=window_days
    )
```

Check the exact constant names/imports before running: `ACCOUNT_TYPE_POINTS` etc. live in `app/shared/models/accounts.py`; `Redemption`, `Referral`, `RewardEvent` exports in `app/shared/models/__init__.py` (add exports if missing). `LedgerEntry.entry_type` constant values (`CREDIT`) — confirm against `app/shared/models/ledger.py` (`ENTRY_CREDIT`); prefer importing the constants over string literals.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/segments/test_metrics.py -v`
Expected: PASS (5 tests). If `_txn(...)` fails on a NOT NULL you didn't set, check `tests/` for an existing transaction factory/fixture and reuse it.

- [ ] **Step 5: Commit**

```bash
git add app/modules/segments/metrics.py tests/segments/test_metrics.py
git commit -m "feat(segments): metric registry with set-based per-user builders"
```

---

### Task 4: Evaluator

**Files:**
- Create: `backend/app/modules/segments/evaluator.py`
- Test: `backend/tests/segments/test_evaluator.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Evaluator behaviour: exclusivity, priority, manual preservation, idempotency."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.segments.evaluator import recompute_tenant
from app.shared.models import Segment, SegmentGroup, Transaction, UserSegment


def _txn(tenant_id, user_id, n):
    return Transaction(
        tenant_id=tenant_id, idempotency_key=f"ev-{user_id}-{n}",
        transaction_type="p2p", status="COMPLETED", initiated_by=user_id,
        amount=Decimal("10"), currency="ZAR",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )


async def _tiered_group(db_session, tenant_id):
    """Loyalty group with Gold(>=3 txns, prio 3) and Bronze(>=1, prio 1)."""
    group = SegmentGroup(tenant_id=tenant_id, name="Loyalty-ev")
    db_session.add(group)
    await db_session.flush()
    gold = Segment(tenant_id=tenant_id, group_id=group.id, name="Gold-ev", priority=3,
                   criteria={"v": 1, "op": "AND", "conditions": [
                       {"metric": "txn_count", "gte": 3}]})
    bronze = Segment(tenant_id=tenant_id, group_id=group.id, name="Bronze-ev", priority=1,
                     criteria={"v": 1, "op": "AND", "conditions": [
                         {"metric": "txn_count", "gte": 1}]})
    db_session.add_all([gold, bronze])
    await db_session.flush()
    return group, gold, bronze


async def _memberships(db_session, segment_id):
    rows = await db_session.execute(
        select(UserSegment).where(UserSegment.segment_id == segment_id))
    return rows.scalars().all()


@pytest.mark.asyncio
async def test_highest_priority_wins_within_group(db_session, test_tenant, test_user):
    _, gold, bronze = await _tiered_group(db_session, test_tenant.id)
    db_session.add_all([_txn(test_tenant.id, test_user.id, i) for i in range(3)])
    await db_session.flush()

    await recompute_tenant(db_session, test_tenant.id)

    assert len(await _memberships(db_session, gold.id)) == 1   # matches both, Gold wins
    assert len(await _memberships(db_session, bronze.id)) == 0


@pytest.mark.asyncio
async def test_manual_memberships_survive_recompute(db_session, test_tenant, test_user):
    _, gold, _ = await _tiered_group(db_session, test_tenant.id)
    db_session.add(UserSegment(user_id=test_user.id, segment_id=gold.id, source="manual"))
    await db_session.flush()

    await recompute_tenant(db_session, test_tenant.id)  # user has 0 txns

    rows = await _memberships(db_session, gold.id)
    assert len(rows) == 1 and rows[0].source == "manual"


@pytest.mark.asyncio
async def test_recompute_is_idempotent_and_removes_stale(db_session, test_tenant, test_user):
    _, gold, bronze = await _tiered_group(db_session, test_tenant.id)
    db_session.add(_txn(test_tenant.id, test_user.id, 0))
    await db_session.flush()

    first = await recompute_tenant(db_session, test_tenant.id)
    assert first[bronze.id]["added"] == 1
    second = await recompute_tenant(db_session, test_tenant.id)
    assert second[bronze.id]["added"] == 0 and second[bronze.id]["removed"] == 0

    # Stale criteria row is removed when the user stops matching: simulate by
    # moving the user's membership to a segment they no longer match.
    db_session.add_all([_txn(test_tenant.id, test_user.id, i) for i in range(1, 3)])
    await db_session.flush()
    third = await recompute_tenant(db_session, test_tenant.id)  # now Gold
    assert third[gold.id]["added"] == 1 and third[bronze.id]["removed"] == 1


@pytest.mark.asyncio
async def test_static_segments_untouched(db_session, test_tenant):
    group = SegmentGroup(tenant_id=test_tenant.id, name="General-ev")
    db_session.add(group)
    await db_session.flush()
    static = Segment(tenant_id=test_tenant.id, group_id=group.id, name="vip-ev")
    db_session.add(static)
    await db_session.flush()

    summary = await recompute_tenant(db_session, test_tenant.id)
    assert static.id not in summary
    assert static.last_evaluated_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/segments/test_evaluator.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.segments.evaluator`

- [ ] **Step 3: Implement the evaluator**

```python
"""Batch evaluator for dynamic segments (spec §4).

Per tenant: compute each distinct (metric, txn_type, window_days) once,
evaluate every dynamic segment's criteria per user, resolve exclusivity
within each group (highest priority wins, oldest segment on ties), then
diff against user_segments WHERE source='criteria'. Manual rows are
never touched. Caller owns the transaction/commit.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments.criteria import Condition, SegmentCriteria
from app.modules.segments.metrics import compute_metric
from app.shared.models import Segment, UserSegment

MetricKey = tuple[str, str | None, int | None]


def _condition_met(cond: Condition, value: Decimal) -> bool:
    """Evaluate one threshold against a user's metric value."""
    if cond.gte is not None and not value >= Decimal(str(cond.gte)):
        return False
    if cond.lte is not None and not value <= Decimal(str(cond.lte)):
        return False
    if cond.eq is not None and not value == Decimal(str(cond.eq)):
        return False
    return True


def _matches(criteria: SegmentCriteria, values: dict[MetricKey, dict[UUID, Decimal]],
             user_id: UUID) -> bool:
    """Evaluate a full criteria doc for one user against precomputed metrics."""
    results = []
    for cond in criteria.conditions:
        key = (cond.metric, cond.txn_type, cond.window_days)
        value = values[key].get(user_id, Decimal(0))
        results.append(_condition_met(cond, value))
    return all(results) if criteria.op == "AND" else any(results)


async def recompute_tenant(
    session: AsyncSession, tenant_id: UUID
) -> dict[UUID, dict[str, Any]]:
    """Recompute criteria-sourced membership for every dynamic segment.

    Returns:
        {segment_id: {"added": int, "removed": int, "member_count": int}}.

    Side effects:
        Inserts/deletes user_segments rows with source='criteria' and stamps
        Segment.last_evaluated_at. Does not commit — caller commits.
    """
    dynamic = (
        (await session.execute(
            select(Segment).where(
                Segment.tenant_id == tenant_id, Segment.criteria.is_not(None))
        )).scalars().all()
    )
    if not dynamic:
        return {}

    parsed = {s.id: SegmentCriteria.model_validate(s.criteria) for s in dynamic}

    # 1. Compute each distinct metric key once.
    keys: set[MetricKey] = {
        (c.metric, c.txn_type, c.window_days)
        for crit in parsed.values() for c in crit.conditions
    }
    values: dict[MetricKey, dict[UUID, Decimal]] = {}
    for metric, txn_type, window_days in keys:
        values[(metric, txn_type, window_days)] = await compute_metric(
            session, tenant_id, metric, txn_type=txn_type, window_days=window_days)

    # 2. Union of users with any metric signal (others can't match any gte/eq>0;
    #    lte-only criteria still need the full user set — include it when any
    #    condition is lte-only).
    from app.shared.models import User  # local import avoids cycle at module load
    needs_all_users = any(
        all(c.gte is None and c.eq is None for c in crit.conditions)
        for crit in parsed.values()
    )
    user_ids: set[UUID] = set()
    if needs_all_users:
        rows = await session.execute(select(User.id).where(User.tenant_id == tenant_id))
        user_ids = {r[0] for r in rows.all()}
    else:
        for value_map in values.values():
            user_ids |= set(value_map)

    # 3. Winners per group: highest priority, then oldest segment (deterministic).
    ordered = sorted(dynamic, key=lambda s: (-s.priority, s.created_at, s.id))
    desired: dict[UUID, set[UUID]] = {s.id: set() for s in dynamic}
    for user_id in user_ids:
        won_groups: set[UUID] = set()
        for segment in ordered:
            if segment.group_id in won_groups:
                continue
            if _matches(parsed[segment.id], values, user_id):
                desired[segment.id].add(user_id)
                won_groups.add(segment.group_id)

    # 4. Diff against current criteria-sourced rows and apply the delta.
    summary: dict[UUID, dict[str, Any]] = {}
    for segment in dynamic:
        current_rows = await session.execute(
            select(UserSegment.user_id).where(
                UserSegment.segment_id == segment.id,
                UserSegment.source == "criteria")
        )
        current = {r[0] for r in current_rows.all()}
        to_add = desired[segment.id] - current
        to_remove = current - desired[segment.id]
        for user_id in to_add:
            session.add(UserSegment(
                user_id=user_id, segment_id=segment.id, source="criteria"))
        if to_remove:
            await session.execute(
                delete(UserSegment).where(
                    UserSegment.segment_id == segment.id,
                    UserSegment.source == "criteria",
                    UserSegment.user_id.in_(to_remove))
            )
        segment.last_evaluated_at = func.now()
        summary[segment.id] = {
            "added": len(to_add),
            "removed": len(to_remove),
            "member_count": len(desired[segment.id]),
        }
    await session.flush()
    return summary


async def preview_criteria(
    session: AsyncSession, tenant_id: UUID, criteria: SegmentCriteria
) -> int:
    """Dry-run: how many users would match these criteria right now."""
    values: dict[MetricKey, dict[UUID, Decimal]] = {}
    for cond in criteria.conditions:
        key = (cond.metric, cond.txn_type, cond.window_days)
        if key not in values:
            values[key] = await compute_metric(
                session, tenant_id, cond.metric,
                txn_type=cond.txn_type, window_days=cond.window_days)
    from app.shared.models import User
    rows = await session.execute(select(User.id).where(User.tenant_id == tenant_id))
    return sum(1 for (uid,) in rows.all() if _matches(criteria, values, uid))
```

Note on duplicate-membership safety: `uq_user_segments_pair` still holds — a user manually assigned to Gold who also wins Gold by criteria would violate it on insert. Guard in the diff: before adding, exclude users already present with `source='manual'` for that segment (add a second `select` of manual user_ids per segment and subtract from `to_add`). Include this guard in the implementation and add a test asserting no IntegrityError when a manual member also matches.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/segments/test_evaluator.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/modules/segments/evaluator.py tests/segments/test_evaluator.py
git commit -m "feat(segments): batch evaluator with priority-resolved exclusive groups"
```

---

### Task 5: Celery task + beat schedule

**Files:**
- Create: `backend/app/modules/segments/tasks.py`
- Modify: `backend/app/celery_app.py` (include + beat entry)
- Test: `backend/tests/segments/test_tasks.py`

- [ ] **Step 1: Read the existing async-task bootstrap**

Open `backend/app/modules/rewards/outbox.py` and note exactly how its `@shared_task` acquires an event loop and an async session (session factory import + `asyncio.run` or loop helper). **Reuse that exact pattern** in the code below — adjust the two bootstrap lines if the outbox does it differently.

- [ ] **Step 2: Write the failing test**

```python
"""Segment recompute task: per-tenant recompute over all tenants with dynamic segments."""
import pytest

from app.modules.segments import tasks


@pytest.mark.asyncio
async def test_recompute_all_tenants_touches_only_tenants_with_dynamic_segments(
    db_session, test_tenant, monkeypatch
):
    calls = []

    async def fake_recompute(session, tenant_id):
        calls.append(tenant_id)
        return {}

    monkeypatch.setattr(tasks, "recompute_tenant", fake_recompute)
    await tasks._recompute_all(db_session)
    # No dynamic segments exist yet in this test DB → no calls.
    assert calls == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/segments/test_tasks.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement the task**

```python
"""Celery tasks for segment recomputation (beat: hourly; manual: API enqueue)."""

from __future__ import annotations

import asyncio

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments.evaluator import recompute_tenant
from app.shared.models import Segment


async def _recompute_all(session: AsyncSession) -> None:
    """Recompute every tenant that has at least one dynamic segment."""
    tenants = await session.execute(
        select(Segment.tenant_id).where(Segment.criteria.is_not(None)).distinct()
    )
    for (tenant_id,) in tenants.all():
        await recompute_tenant(session, tenant_id)
    await session.commit()


@shared_task(name="segments.recompute_all")
def recompute_all_segments() -> None:
    """Beat entrypoint — mirror the session bootstrap in rewards/outbox.py."""
    from app.database import async_session_factory  # match outbox.py's import

    async def _run() -> None:
        async with async_session_factory() as session:
            await _recompute_all(session)

    asyncio.run(_run())


@shared_task(name="segments.recompute_tenant")
def recompute_one_tenant(tenant_id: str) -> None:
    """Manual-recompute entrypoint enqueued by the API."""
    from uuid import UUID

    from app.database import async_session_factory

    async def _run() -> None:
        async with async_session_factory() as session:
            await recompute_tenant(session, UUID(tenant_id))
            await session.commit()

    asyncio.run(_run())
```

In `backend/app/celery_app.py`: add `"app.modules.segments.tasks"` to `include=[...]` and a beat entry:

```python
    # Dynamic segment membership refresh (spec 2026-08-12 §4). Hourly default;
    # override via SEGMENT_RECOMPUTE_INTERVAL_SECS.
    "segments-recompute": {
        "task": "segments.recompute_all",
        "schedule": float(getattr(settings, "SEGMENT_RECOMPUTE_INTERVAL_SECS", 3600)),
    },
```

Add `SEGMENT_RECOMPUTE_INTERVAL_SECS: int = 3600` to `app/config.py` settings (mirror an existing int setting's style) and to `.env.example` with a comment.

- [ ] **Step 5: Run test + full segments suite**

Run: `pytest tests/segments/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/segments/tasks.py app/celery_app.py app/config.py ../.env.example tests/segments/test_tasks.py
git commit -m "feat(segments): hourly Celery recompute task + beat schedule"
```

---

### Task 6: Segment-group CRUD API

**Files:**
- Create: `backend/app/modules/segments/group_service.py`
- Modify: `backend/app/modules/segments/router.py` (add group routes)
- Modify: `backend/app/modules/segments/schemas.py` (group schemas)
- Test: `backend/tests/segments/test_group_api.py`

- [ ] **Step 1: Write the failing tests** — mirror the request style of `tests/segments/test_segments_crud.py` (read it first for the auth-header fixtures, e.g. `admin_headers`, and copy its exact idioms):

```python
"""API tests for /api/v1/segment-groups (happy, auth, validation, isolation, guarded delete)."""
import pytest


@pytest.mark.asyncio
async def test_create_list_group_happy_path(async_client, admin_headers, test_tenant):
    resp = await async_client.post(
        "/api/v1/segment-groups",
        json={"tenant_id": str(test_tenant.id), "name": "Customer Loyalty",
              "description": "Tenure and engagement tiers."},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Customer Loyalty" and body["is_system"] is False

    listed = await async_client.get(
        f"/api/v1/segment-groups?tenant_id={test_tenant.id}", headers=admin_headers)
    assert listed.status_code == 200
    assert any(g["id"] == body["id"] for g in listed.json())


@pytest.mark.asyncio
async def test_group_requires_auth(async_client, test_tenant):
    resp = await async_client.post(
        "/api/v1/segment-groups",
        json={"tenant_id": str(test_tenant.id), "name": "x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_group_name_validation(async_client, admin_headers, test_tenant):
    resp = await async_client.post(
        "/api/v1/segment-groups",
        json={"tenant_id": str(test_tenant.id), "name": ""}, headers=admin_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_group_duplicate_name_409(async_client, admin_headers, test_tenant):
    payload = {"tenant_id": str(test_tenant.id), "name": "Dup Group"}
    await async_client.post("/api/v1/segment-groups", json=payload, headers=admin_headers)
    resp = await async_client.post("/api/v1/segment-groups", json=payload, headers=admin_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_blocked_while_segments_exist_and_for_system_groups(
    async_client, admin_headers, test_tenant
):
    group = (await async_client.post(
        "/api/v1/segment-groups",
        json={"tenant_id": str(test_tenant.id), "name": "Deletable"},
        headers=admin_headers)).json()

    seg = await async_client.post(
        "/api/v1/segments",
        json={"tenant_id": str(test_tenant.id), "name": "in-group",
              "group_id": group["id"]},
        headers=admin_headers)
    assert seg.status_code == 201

    resp = await async_client.delete(
        f"/api/v1/segment-groups/{group['id']}?tenant_id={test_tenant.id}",
        headers=admin_headers)
    assert resp.status_code == 409  # segments still inside
```

(Adjust fixture names to the actual conftest — the existing `test_segments_crud.py` shows the canonical spelling; also add the standard cross-tenant-isolation test copied from that file's pattern.)

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/segments/test_group_api.py -v`
Expected: FAIL — 404s (routes don't exist).

- [ ] **Step 3: Implement schemas, service, routes**

`schemas.py` additions:

```python
class SegmentGroupCreateRequest(BaseModel):
    """Admin create payload for a segment group."""

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class SegmentGroupOut(BaseModel):
    """Segment-group resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime
```

`group_service.py` (mirror `service.py`'s create_segment structure: tenant assert, IntegrityError → 409 `AppHTTPException`, `record_audit_for_admin` calls with `action="segment_group.created"` / `"segment_group.deleted"`):

```python
"""Segment-group service — CRUD for segmentation lenses (spec §2/§7)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.segments.schemas import SegmentGroupCreateRequest
from app.shared.exceptions import AppHTTPException
from app.shared.models import Segment, SegmentGroup, Tenant


async def create_group(
    session: AsyncSession,
    request: SegmentGroupCreateRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None,
) -> SegmentGroup:
    """Create a segment group. 409 on duplicate name within the tenant."""
    tenant = await session.get(Tenant, request.tenant_id)
    if tenant is None:
        raise AppHTTPException(status_code=404, error_code="tenant_not_found",
                               message="Tenant not found.")
    group = SegmentGroup(tenant_id=request.tenant_id, name=request.name,
                         description=request.description)
    session.add(group)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise AppHTTPException(status_code=409, error_code="segment_group_name_taken",
                               message="A group with that name already exists.") from exc
    await record_audit_for_admin(
        session, admin, tenant_id=request.tenant_id, action="segment_group.created",
        entity_type="segment_group", entity_id=str(group.id),
        after_state={"name": group.name}, ip_address=ip_address)
    return group


async def list_groups(session: AsyncSession, tenant_id: UUID) -> list[SegmentGroup]:
    """All groups in the tenant, name-ordered."""
    rows = await session.execute(
        select(SegmentGroup).where(SegmentGroup.tenant_id == tenant_id)
        .order_by(SegmentGroup.name))
    return list(rows.scalars().all())


async def delete_group(
    session: AsyncSession, group_id: UUID, tenant_id: UUID,
    *, admin: AdminPrincipal, ip_address: str | None,
) -> None:
    """Delete an empty, non-system group. 409 when segments remain or system."""
    group = (await session.execute(
        select(SegmentGroup).where(SegmentGroup.id == group_id,
                                   SegmentGroup.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if group is None:
        raise AppHTTPException(status_code=404, error_code="segment_group_not_found",
                               message="Segment group not found.")
    if group.is_system:
        raise AppHTTPException(status_code=409, error_code="segment_group_protected",
                               message="System groups cannot be deleted.")
    count = (await session.execute(
        select(func.count()).select_from(Segment).where(Segment.group_id == group_id))
    ).scalar_one()
    if count:
        raise AppHTTPException(status_code=409, error_code="segment_group_not_empty",
                               message="Move or delete the group's segments first.")
    await session.delete(group)
    await record_audit_for_admin(
        session, admin, tenant_id=tenant_id, action="segment_group.deleted",
        entity_type="segment_group", entity_id=str(group_id),
        before_state={"name": group.name}, ip_address=ip_address)
```

Router: copy the exact dependency style of the existing segment routes in `router.py` (`require_admin_role("platform-admin")`, `get_async_session`, `_client_ip` helper as in multipliers). Add `POST /api/v1/segment-groups` (201), `GET /api/v1/segment-groups?tenant_id=`, `DELETE /api/v1/segment-groups/{group_id}?tenant_id=` (204). Verify `AppHTTPException`'s constructor signature in `app/shared/exceptions/` and match it.

- [ ] **Step 4: Run tests**

Run: `pytest tests/segments/test_group_api.py -v` — expected PASS. Note the create-segment call in the delete test needs Task 7's `group_id` support; if running tasks strictly in order, mark that one test `@pytest.mark.xfail(reason="group_id lands in Task 7")` and un-xfail it in Task 7.

- [ ] **Step 5: Commit**

```bash
git add app/modules/segments/ tests/segments/test_group_api.py
git commit -m "feat(segments): segment-group CRUD API with guarded delete"
```

---

### Task 7: Segment endpoints — group_id/criteria/priority, metrics vocabulary, preview, recompute

**Files:**
- Modify: `backend/app/modules/segments/schemas.py`, `service.py`, `router.py`
- Test: `backend/tests/segments/test_dynamic_segments_api.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Dynamic-segment API: create with criteria, vocabulary, preview, recompute enqueue."""
import pytest


@pytest.fixture
async def group_id(async_client, admin_headers, test_tenant):
    resp = await async_client.post(
        "/api/v1/segment-groups",
        json={"tenant_id": str(test_tenant.id), "name": "API Loyalty"},
        headers=admin_headers)
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_create_dynamic_segment(async_client, admin_headers, test_tenant, group_id):
    resp = await async_client.post(
        "/api/v1/segments",
        json={"tenant_id": str(test_tenant.id), "name": "Gold-api",
              "group_id": group_id, "priority": 3,
              "criteria": {"v": 1, "op": "AND", "conditions": [
                  {"metric": "txn_count", "window_days": 90, "gte": 20}]}},
        headers=admin_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["priority"] == 3 and body["criteria"]["op"] == "AND"


@pytest.mark.asyncio
async def test_create_rejects_invalid_criteria(async_client, admin_headers,
                                               test_tenant, group_id):
    resp = await async_client.post(
        "/api/v1/segments",
        json={"tenant_id": str(test_tenant.id), "name": "Bad", "group_id": group_id,
              "criteria": {"v": 1, "op": "AND", "conditions": [
                  {"metric": "shoe_size", "gte": 1}]}},
        headers=admin_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_metrics_vocabulary_endpoint(async_client, admin_headers):
    resp = await async_client.get("/api/v1/segments/metrics", headers=admin_headers)
    assert resp.status_code == 200
    names = {m["name"] for m in resp.json()}
    assert "txn_count" in names and "wallet_balance" in names


@pytest.mark.asyncio
async def test_preview_returns_match_count(async_client, admin_headers, test_tenant):
    resp = await async_client.post(
        "/api/v1/segments/preview",
        json={"tenant_id": str(test_tenant.id),
              "criteria": {"v": 1, "op": "AND", "conditions": [
                  {"metric": "account_age_days", "gte": 0}]}},
        headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["match_count"] >= 1  # conftest seeds at least one user


@pytest.mark.asyncio
async def test_recompute_enqueues(async_client, admin_headers, test_tenant, monkeypatch):
    from app.modules.segments import tasks
    enqueued = []
    monkeypatch.setattr(tasks.recompute_one_tenant, "delay",
                        lambda tid: enqueued.append(tid))
    resp = await async_client.post(
        f"/api/v1/segments/recompute?tenant_id={test_tenant.id}",
        headers=admin_headers)
    assert resp.status_code == 202
    assert enqueued == [str(test_tenant.id)]
```

Plus copy the standard 401 + tenant-isolation cases from `test_segments_crud.py` for the new routes.

- [ ] **Step 2: Run to verify failures** — `pytest tests/segments/test_dynamic_segments_api.py -v` → 404/422 failures.

- [ ] **Step 3: Implement**

`schemas.py` — extend `SegmentCreateRequest` and `SegmentOut`:

```python
from app.modules.segments.criteria import SegmentCriteria


class SegmentCreateRequest(BaseModel):
    """Admin create payload (extended for groups + dynamic criteria)."""

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    group_id: UUID
    priority: int = Field(default=0, ge=0, le=1000)
    criteria: SegmentCriteria | None = None
```

`SegmentOut` gains `group_id: UUID`, `priority: int`, `criteria: dict | None`, `is_system: bool`, `last_evaluated_at: datetime | None`. Add:

```python
class SegmentPreviewRequest(BaseModel):
    """Dry-run criteria against a tenant's users."""

    tenant_id: UUID
    criteria: SegmentCriteria


class MetricInfo(BaseModel):
    """Vocabulary entry for the manual builder UI."""

    name: str
    supports_txn_type: bool
    supports_window: bool
```

`service.py` — `create_segment` passes `group_id=request.group_id`, `priority=request.priority`, `criteria=request.criteria.model_dump() if request.criteria else None`, and validates the group exists in the same tenant (404 `segment_group_not_found` otherwise). Add `PATCH` support (`update_segment`) for `criteria`/`priority`/`description` (name/delete protected when `is_system`, error_code `segment_protected`).

`router.py` — new routes (order matters: register `/segments/metrics`, `/segments/preview`, `/segments/recompute` **before** any `/segments/{segment_id}` route so the literal paths don't get captured):

```python
@router.get("/metrics", response_model=list[MetricInfo])
async def get_metric_vocabulary(
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
) -> list[MetricInfo]:
    """The criteria vocabulary the manual builder renders."""
    _ = admin
    from app.modules.segments.criteria import (
        ALL_METRICS, TRANSACTIONAL_METRICS, WINDOWED_METRICS)
    return [MetricInfo(name=m, supports_txn_type=m in TRANSACTIONAL_METRICS,
                       supports_window=m in WINDOWED_METRICS)
            for m in sorted(ALL_METRICS)]


@router.post("/preview")
async def post_preview(
    request: SegmentPreviewRequest,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Dry-run matched-user count for a criteria document."""
    _ = admin
    count = await preview_criteria(session, request.tenant_id, request.criteria)
    return {"match_count": count}


@router.post("/recompute", status_code=202)
async def post_recompute(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
) -> dict:
    """Enqueue an immediate membership recompute for the tenant."""
    _ = admin
    from app.modules.segments.tasks import recompute_one_tenant
    recompute_one_tenant.delay(str(tenant_id))
    return {"status": "enqueued"}
```

- [ ] **Step 4: Run the whole segments suite** — `pytest tests/segments/ -v` → all PASS (un-xfail the Task 6 test).

- [ ] **Step 5: Run repo gates** — `make check` (alembic check + ruff + mypy) → clean.

- [ ] **Step 6: Commit**

```bash
git add app/modules/segments/ tests/segments/
git commit -m "feat(segments): dynamic-segment API (criteria create, vocabulary, preview, recompute)"
```

---

### Task 8: Seed default groups + tiers

**Files:**
- Modify: `scripts/seed.py`

- [ ] **Step 1: Read the seed script's segment/rule section** to find its session usage and print style; add a `seed_segment_defaults(session, tenant_id)` function called from the main flow after users exist:

```python
DEFAULT_SEGMENT_GROUPS = [
    ("Customer Loyalty", "Tenure + engagement tiers.", [
        ("Gold", 3, {"v": 1, "op": "AND", "conditions": [
            {"metric": "txn_count", "window_days": 90, "gte": 20}]}),
        ("Silver", 2, {"v": 1, "op": "AND", "conditions": [
            {"metric": "txn_count", "window_days": 90, "gte": 5}]}),
        ("Bronze", 1, {"v": 1, "op": "AND", "conditions": [
            {"metric": "txn_count", "window_days": 90, "gte": 1}]}),
    ]),
    ("Transaction Value", "Gross transaction value bands (rolling 90d).", [
        ("High", 3, {"v": 1, "op": "AND", "conditions": [
            {"metric": "txn_sum", "window_days": 90, "gte": 10000}]}),
        ("Mid", 2, {"v": 1, "op": "AND", "conditions": [
            {"metric": "txn_sum", "window_days": 90, "gte": 1000}]}),
        ("Low", 1, {"v": 1, "op": "AND", "conditions": [
            {"metric": "txn_sum", "window_days": 90, "gte": 0.01}]}),
    ]),
    ("Engagement", "Recency of activity.", [
        ("Active", 3, {"v": 1, "op": "AND", "conditions": [
            {"metric": "days_since_last_txn", "lte": 14}]}),
        ("New", 2, {"v": 1, "op": "AND", "conditions": [
            {"metric": "account_age_days", "lte": 30}]}),
        ("Dormant", 1, {"v": 1, "op": "AND", "conditions": [
            {"metric": "days_since_last_txn", "gte": 60}]}),
    ]),
]
```

The function validates each criteria dict through `SegmentCriteria.model_validate` (fail loud on drift), creates groups + segments with `is_system=True`, skips ones that already exist by (tenant, name), and prints one `+ Created segment group: ...` line per group in the seed's established style.

- [ ] **Step 2: Verify by running the seed against the dev stack**

Run: `make seed` (dev stack up, from `backend/`)
Expected: three `+ Created segment group` lines; re-running is a no-op (skip messages, no duplicates).

- [ ] **Step 3: Commit**

```bash
git add ../scripts/seed.py
git commit -m "feat(seed): default segment groups (Loyalty, Value, Engagement) with tiered criteria"
```

---

### Task 9: Admin UI — API types, client functions, criteria lib helpers

**Files:**
- Modify: `admin-ui/lib/api-types.ts`, `admin-ui/lib/api-endpoints.ts`
- Create: `admin-ui/lib/segment-criteria.ts`
- Test: `admin-ui/lib/segment-criteria.test.ts`

- [ ] **Step 1: Add types** (in `api-types.ts`, next to `Segment`; extend the existing `Segment` interface with the new fields rather than duplicating it):

```typescript
/** One criteria condition (DSL v1) — mirrors backend SegmentCriteria. */
export interface CriteriaCondition {
  metric: string;
  txn_type?: string | null;
  window_days?: number | null;
  gte?: number | null;
  lte?: number | null;
  eq?: number | null;
}

/** Criteria document for a dynamic segment. */
export interface SegmentCriteriaDoc {
  v: 1;
  op: "AND" | "OR";
  conditions: CriteriaCondition[];
}

/** A segmentation lens holding exclusive tiers. */
export interface SegmentGroup {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  created_at: string;
  updated_at: string;
}

/** Metric vocabulary entry served by /segments/metrics. */
export interface SegmentMetricInfo {
  name: string;
  supports_txn_type: boolean;
  supports_window: boolean;
}
```

`Segment` gains: `group_id: string; priority: number; criteria: SegmentCriteriaDoc | null; is_system: boolean; last_evaluated_at: string | null;`

- [ ] **Step 2: Add client functions** (in `api-endpoints.ts`, following the multiplier section's style):

```typescript
export interface CreateSegmentGroupPayload {
  tenant_id: string;
  name: string;
  description?: string;
}

export const listSegmentGroups = (tenant_id: string) =>
  apiGet<SegmentGroup[]>("/api/v1/segment-groups", { query: { tenant_id } });

export const createSegmentGroup = (payload: CreateSegmentGroupPayload) =>
  apiPost<SegmentGroup>("/api/v1/segment-groups", payload);

export const deleteSegmentGroup = (group_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/segment-groups/${group_id}`, { query: { tenant_id } });

export const listSegmentMetrics = () =>
  apiGet<SegmentMetricInfo[]>("/api/v1/segments/metrics");

export const previewSegmentCriteria = (
  tenant_id: string,
  criteria: SegmentCriteriaDoc,
) =>
  apiPost<{ match_count: number }>("/api/v1/segments/preview", {
    tenant_id,
    criteria,
  });

export const recomputeSegments = (tenant_id: string) =>
  apiPost<{ status: string }>("/api/v1/segments/recompute", undefined, {
    query: { tenant_id },
  });
```

Extend the existing `CreateSegmentPayload` with `group_id: string; priority?: number; criteria?: SegmentCriteriaDoc;`. Check `apiPost`'s signature in `lib/api.ts` for the query-param form used by `recomputeSegments` and match it.

- [ ] **Step 3: Write failing tests for the lib helpers**

```typescript
/**
 * Tests for segment-criteria helpers: human summary + client-side validation.
 */
import { describe, expect, it } from "vitest";

import {
  emptyCriteria,
  summarizeCriteria,
  validateCriteria,
} from "@/lib/segment-criteria";

describe("summarizeCriteria", () => {
  it("Verify a two-condition AND criteria reads as English", () => {
    expect(
      summarizeCriteria({
        v: 1,
        op: "AND",
        conditions: [
          { metric: "txn_sum", txn_type: "p2p", window_days: 90, gte: 5000 },
          { metric: "days_since_last_txn", lte: 14 },
        ],
      }),
    ).toBe(
      "txn_sum (p2p, last 90d) ≥ 5000 AND days_since_last_txn ≤ 14",
    );
  });

  it("Verify eq renders with =", () => {
    expect(
      summarizeCriteria({
        v: 1, op: "OR",
        conditions: [{ metric: "referral_count", eq: 0 }],
      }),
    ).toBe("referral_count = 0");
  });
});

describe("validateCriteria", () => {
  it("Verify a comparator-less condition is reported", () => {
    const errors = validateCriteria({
      v: 1, op: "AND", conditions: [{ metric: "txn_count" }],
    });
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatch(/threshold/i);
  });

  it("Verify an empty criteria is reported", () => {
    expect(validateCriteria(emptyCriteria())).toHaveLength(1);
  });

  it("Verify a valid criteria has no errors", () => {
    expect(
      validateCriteria({
        v: 1, op: "AND",
        conditions: [{ metric: "txn_count", gte: 1 }],
      }),
    ).toHaveLength(0);
  });
});
```

- [ ] **Step 4: Run to verify failure** — `cd admin-ui && npx vitest run lib/segment-criteria.test.ts` → module not found.

- [ ] **Step 5: Implement `lib/segment-criteria.ts`**

```typescript
/**
 * Pure helpers for the segment criteria builder: an empty-document factory,
 * a human-readable one-line summary, and client-side validation mirroring
 * the backend SegmentCriteria rules (backend remains the authority).
 */
import type { CriteriaCondition, SegmentCriteriaDoc } from "@/lib/api-types";

/** A fresh, empty criteria document for the builder's initial state. */
export function emptyCriteria(): SegmentCriteriaDoc {
  return { v: 1, op: "AND", conditions: [] };
}

/** Render one condition, e.g. "txn_sum (p2p, last 90d) ≥ 5000". */
function summarizeCondition(c: CriteriaCondition): string {
  const filters: string[] = [];
  if (c.txn_type) filters.push(c.txn_type);
  if (c.window_days) filters.push(`last ${c.window_days}d`);
  const scope = filters.length > 0 ? ` (${filters.join(", ")})` : "";
  const parts: string[] = [];
  if (c.gte != null) parts.push(`≥ ${c.gte}`);
  if (c.lte != null) parts.push(`≤ ${c.lte}`);
  if (c.eq != null) parts.push(`= ${c.eq}`);
  return `${c.metric}${scope} ${parts.join(" and ")}`.trim();
}

/** One-line English summary of a criteria document. */
export function summarizeCriteria(doc: SegmentCriteriaDoc): string {
  return doc.conditions.map(summarizeCondition).join(` ${doc.op} `);
}

/** Client-side validation errors (empty array = valid). */
export function validateCriteria(doc: SegmentCriteriaDoc): string[] {
  const errors: string[] = [];
  if (doc.conditions.length === 0) {
    errors.push("Add at least one condition.");
  }
  doc.conditions.forEach((c, i) => {
    if (c.gte == null && c.lte == null && c.eq == null) {
      errors.push(`Condition ${i + 1} needs a threshold (≥, ≤ or =).`);
    }
  });
  return errors;
}
```

- [ ] **Step 6: Run tests** — `npx vitest run lib/segment-criteria.test.ts` → PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add lib/api-types.ts lib/api-endpoints.ts lib/segment-criteria.ts lib/segment-criteria.test.ts
git commit -m "feat(admin-ui): segment-group API client + criteria lib helpers"
```

---

### Task 10: Admin UI — criteria builder component + dynamic create dialog

**Files:**
- Create: `admin-ui/app/(authenticated)/segments/_components/criteria-builder.tsx`
- Modify: `admin-ui/app/(authenticated)/segments/_components/create-segment-dialog.tsx`
- Modify: `admin-ui/app/(authenticated)/segments/_actions.ts` (preview + extended create actions)
- Test: `admin-ui/app/(authenticated)/segments/_components/criteria-builder.test.tsx`

- [ ] **Step 1: Add server actions** (`_actions.ts`, mirroring the existing result-shape pattern):

```typescript
export async function previewCriteriaAction(
  tenantId: string,
  criteria: SegmentCriteriaDoc,
): Promise<{ ok: true; count: number } | { ok: false; errorCode: string; message: string }> {
  try {
    const { match_count } = await previewSegmentCriteria(tenantId, criteria);
    return { ok: true, count: match_count };
  } catch (err) {
    if (err instanceof ApiError) {
      return { ok: false, errorCode: err.errorCode, message: err.message };
    }
    return { ok: false, errorCode: "internal_error",
             message: err instanceof Error ? err.message : "Unknown error" };
  }
}
```

`createSegmentAction` stays as-is (its payload type now carries `group_id`/`priority`/`criteria`). Add `recomputeSegmentsAction(tenantId)` and `createSegmentGroupAction(payload)` / `deleteSegmentGroupAction(id, tenantId)` in the same shape (each `revalidatePath("/segments")`).

- [ ] **Step 2: Write the failing component test**

```typescript
/**
 * Interaction tests for <CriteriaBuilder>: add/edit/remove conditions and
 * surface validation errors. Pure client component — no server actions.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CriteriaBuilder } from "@/app/(authenticated)/segments/_components/criteria-builder";
import { emptyCriteria } from "@/lib/segment-criteria";

const METRICS = [
  { name: "txn_count", supports_txn_type: true, supports_window: true },
  { name: "wallet_balance", supports_txn_type: false, supports_window: false },
];

function setup(onChange = vi.fn()) {
  render(
    <CriteriaBuilder
      value={emptyCriteria()}
      metrics={METRICS}
      services={[{ code: "p2p", display_name: "P2P" }]}
      onChange={onChange}
    />,
  );
  return onChange;
}

describe("CriteriaBuilder", () => {
  it("Verify adding a condition emits a document with one condition", async () => {
    const user = userEvent.setup();
    const onChange = setup();
    await user.click(screen.getByRole("button", { name: /add condition/i }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        conditions: [expect.objectContaining({ metric: "txn_count" })],
      }),
    );
  });

  it("Verify the empty state shows the validation message", () => {
    setup();
    expect(screen.getByText("Add at least one condition.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify failure** — `npx vitest run "app/(authenticated)/segments"` → component missing.

- [ ] **Step 4: Implement `<CriteriaBuilder>`** — controlled component: props `{value, metrics, services, onChange}`. Renders the AND/OR `Select`, one row per condition (metric `Select`; conditional `txn_type` `Select` fed by `services` and `window_days` numeric `Input` per the metric's `supports_*` flags; three numeric inputs ≥/≤/=; remove button), an "Add condition" button appending `{metric: metrics[0].name, gte: undefined,...}`, and a footer that shows `validateCriteria(value)` errors plus `summarizeCriteria(value)` when valid. Number inputs parse with `Number(...)`, storing `null` for empty strings. Match the multipliers dialog's Tailwind idioms (`grid grid-cols-…`, `Label`/`Input`/`Select` primitives, `font-mono tabular-nums` on numerics). Keep the file under ~200 lines; JSDoc on the component and each helper.

- [ ] **Step 5: Extend `<CreateSegmentDialog>`** — new props `{groups, metrics, services}`. Form gains: group `Select` (required), priority numeric `Input` (default 0), a "Dynamic segment" checkbox that mounts `<CriteriaBuilder>`, and a "Preview matches" button calling `previewCriteriaAction` and rendering "~N users match". Submit blocks on `validateCriteria` errors when dynamic; payload includes `group_id`, `priority`, and `criteria` (only when dynamic). Update its existing test file for the new required props (pass fixture `groups`/`metrics`/`services`; assert payload carries `group_id`).

- [ ] **Step 6: Run the segments component tests** — `npx vitest run "app/(authenticated)/segments"` → PASS.

- [ ] **Step 7: Commit**

```bash
git add "app/(authenticated)/segments" 
git commit -m "feat(admin-ui): criteria builder + dynamic segment create dialog"
```

---

### Task 11: Admin UI — group-sectioned segments page

**Files:**
- Modify: `admin-ui/app/(authenticated)/segments/page.tsx`
- Create: `admin-ui/app/(authenticated)/segments/_components/group-section.tsx`
- Create: `admin-ui/app/(authenticated)/segments/_components/create-group-dialog.tsx`
- Test: `admin-ui/app/(authenticated)/segments/_components/group-section.test.tsx`

- [ ] **Step 1: Page (server component)** — fetch in parallel: `listSegmentGroups`, `listSegments`, `listSegmentMetrics`, `listServices(tenantId, "active")`. Header actions: "New group" (`<CreateGroupDialog>`), "New segment" (existing dialog with new props), "Recompute now" button (client component calling `recomputeSegmentsAction`, success toast "Recompute enqueued"). Body: one `<GroupSection>` per group (segments sorted by `priority` desc), then an "Ungrouped" guard is unnecessary (group_id is required).

- [ ] **Step 2: `<GroupSection>`** — client component: collapsible section titled with group name + segment count + system badge; rows show name, static/dynamic badge, `summarizeCriteria` snippet (muted, truncated), priority (`font-mono tabular-nums`), member count if provided, `last_evaluated_at` via `formatTimestamp`, and the existing assign-user affordance for static segments only. Delete-group button (non-system, confirm dialog, surfacing the 409 error codes as toasts).

- [ ] **Step 3: `<CreateGroupDialog>`** — clone of the old create-segment-dialog shape: name + description, calls `createSegmentGroupAction`, toast + close on success.

- [ ] **Step 4: Component test** — render `<GroupSection>` with one dynamic + one static segment fixture; assert the tier ordering (higher priority first), the dynamic badge, and the criteria summary text appear:

```typescript
it("Verify segments render priority-ordered with dynamic badges", () => {
  render(<GroupSection group={GROUP} segments={[bronze, gold]} />);
  const rows = screen.getAllByRole("row");
  expect(rows[1]).toHaveTextContent("Gold");   // priority 3 before 1
  expect(rows[2]).toHaveTextContent("Bronze");
  expect(screen.getAllByText("Dynamic")).toHaveLength(2);
});
```

(Write the full test file with fixtures mirroring Task 10's style; run it failing first, then implement.)

- [ ] **Step 5: Run all frontend gates** — `npm test && npx eslint "app/(authenticated)/segments" lib/segment-criteria.ts && npx tsc --noEmit` → clean.

- [ ] **Step 6: Commit**

```bash
git add "app/(authenticated)/segments"
git commit -m "feat(admin-ui): group-sectioned segments page with recompute + group CRUD"
```

---

### Task 12: End-to-end verification + docs

**Files:**
- Modify: `docs/09-epics-and-stories.md` (add Segmentation Phase 1 entry, status Shipped)

- [ ] **Step 1: Backend gates** — from `backend/`: `make check && make test` (full suite; remember: one pytest run at a time). Expected: clean.

- [ ] **Step 2: Frontend gates** — from `admin-ui/`: `npm test && npm run lint && npm run build`. Expected: clean (the one pre-existing repo-wide lint error was fixed in `36ee954`; the gate should be green).

- [ ] **Step 3: Live smoke test** — `scripts/dev.sh start`; `make seed` (fresh DB or the skip-path); as `admin-test` on `/segments`: three seeded groups visible with tiers; create a dynamic segment via the builder; "Preview matches" returns a count; "Recompute now" then reload shows `last_evaluated_at` set and Alice/Bob in the expected Engagement tiers (send a P2P in the simulator first to make Alice "Active").

- [ ] **Step 4: Update epics doc** — add a "Segmentation Phase 1" entry (groups, DSL, evaluator, defaults, UI — Shipped; AI layer — Planned, spec link).

- [ ] **Step 5: Commit**

```bash
git add docs/09-epics-and-stories.md
git commit -m "docs(epics): segmentation phase 1 shipped; AI layer planned"
```

---

## Self-review notes (already applied)

- Spec coverage: §2 → Tasks 1; §3 → Task 2; §4 → Tasks 3–5, 7 (preview/recompute); §5 → Task 8; §7 → Tasks 6–7; §8 → Tasks 9–11; §9 → tests embedded per task. §6 (AI) is Phase 2 — separate plan.
- Manual/criteria unique-constraint collision handled via the guard note in Task 4 Step 3 (implementer must subtract manual members before insert + test it).
- Idempotency-Key: the repo's mutating-endpoint convention applies to segment/group create — copy whatever `test_segments_crud.py` asserts today for POST /segments; recompute (202, enqueue-only) and preview (read-only) follow the spec's exemption note.
- Type consistency: `SegmentCriteriaDoc`/`SegmentCriteria`, `recompute_tenant`, `preview_criteria`, `compute_metric` names used consistently across tasks.
