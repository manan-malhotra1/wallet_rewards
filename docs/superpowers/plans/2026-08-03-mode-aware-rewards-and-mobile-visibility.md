# Mode-Aware Internal Rewards + Mobile Rewards Visibility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `both`-mode wallet transactions into the rewards engine via a transactional outbox (durable + reconcilable), gate all reward behavior on `tenants.business_type`, and expose rewards + progress + an earned-signal to the mobile app.

**Architecture:** `post_transaction` writes a `reward_outbox` row atomically with the ledger commit when the caller passes a `reward_trigger` and the tenant is `both`. A post-commit immediate attempt (and a Celery recon sweep) drain outbox rows through the shared `evaluate_and_issue_firings` core (also used by `process_external_event`). External Kafka events are code-restricted to `rewards` tenants. `GET /me/rewards` projects `user_rule_progress` into catalog+progress; `reward_events.seen_at` drives a one-shot mobile celebration.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, Celery+Redis, pytest (backend); Expo/React Native + Tamagui (mobile, tests deferred).

**Spec:** `docs/superpowers/specs/2026-08-03-mode-aware-rewards-and-mobile-visibility-design.md`

---

## File Structure

**Backend — create:**
- `backend/app/shared/tenant_mode.py` — mode resolver + constants re-export.
- `backend/app/modules/rewards/outbox.py` — build event, drain, immediate attempt, recon task.
- `backend/tests/rewards/test_outbox_internal.py`, `test_mode_gating.py`, `test_me_rewards.py`.

**Backend — modify:**
- `backend/app/shared/models/tenants.py` — `BUSINESS_TYPE_*` constants.
- `backend/app/shared/models/rewards.py` — `RewardOutbox` model + `RewardEvent.seen_at`.
- `backend/app/modules/ledger/schemas.py` — `RewardTrigger` + `PostTransactionRequest.reward_trigger`.
- `backend/app/modules/ledger/service.py` — outbox write inside `post_transaction`.
- `backend/app/modules/events/service.py` — extract `evaluate_and_issue_firings`; add mode-reject in `process_external_event`.
- `backend/app/modules/payments/service.py` + `money_operations`/`airtime` services — set `reward_trigger`; call `attempt_immediate` post-commit.
- `backend/app/modules/identity/router.py` + `service.py` + `schemas.py` — `GET /me/rewards`, `POST /me/rewards/seen`.
- `backend/app/worker/…` (Celery beat schedule) — register `recon_sweep`.
- `backend/alembic/versions/` — one migration (outbox table + `seen_at`).

**Mobile — create:**
- `mobile/lib/api/rewards.ts`, `mobile/app/rewards/index.tsx`, `mobile/components/rewards/RewardCelebration.tsx`.

**Mobile — modify:**
- `mobile/app/home.tsx` — Rewards tile route + celebration trigger.

---

## Task 1: Business-type constants + resolver

**Files:**
- Modify: `backend/app/shared/models/tenants.py`
- Create: `backend/app/shared/tenant_mode.py`
- Test: `backend/tests/rewards/test_mode_gating.py`

- [ ] **Step 1: Add constants to the tenants model**

In `backend/app/shared/models/tenants.py`, above the `Tenant` class:
```python
# Deployment modes (tenants.business_type). Load-bearing as of 2026-08-03:
# gates whether wallet activity and/or external Kafka events drive rewards.
BUSINESS_TYPE_WALLET = "wallet"
BUSINESS_TYPE_REWARDS = "rewards"
BUSINESS_TYPE_BOTH = "both"
BUSINESS_TYPES = (BUSINESS_TYPE_WALLET, BUSINESS_TYPE_REWARDS, BUSINESS_TYPE_BOTH)
```

- [ ] **Step 2: Write the failing test for the resolver**

Create `backend/tests/rewards/test_mode_gating.py`:
```python
"""Deployment-mode gating: business_type drives reward behavior."""
import pytest
from app.shared.tenant_mode import business_type_of, rewards_from_wallet_enabled
from app.shared.models.tenants import BUSINESS_TYPE_BOTH


@pytest.mark.asyncio
async def test_business_type_of_returns_stored_mode(session, tenant_factory):
    tenant = await tenant_factory(business_type=BUSINESS_TYPE_BOTH)
    assert await business_type_of(session, tenant.id) == BUSINESS_TYPE_BOTH
    assert await rewards_from_wallet_enabled(session, tenant.id) is True
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_mode_gating.py::test_business_type_of_returns_stored_mode -v`
Expected: FAIL — `ModuleNotFoundError: app.shared.tenant_mode`.

- [ ] **Step 4: Implement the resolver**

Create `backend/app/shared/tenant_mode.py`:
```python
"""Single reader of `tenants.business_type` — the deployment-mode gate.

Every reward path consults this: wallet activity drives rewards only in
`both`; external Kafka events issue rewards only in `rewards`.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models.tenants import (
    BUSINESS_TYPE_BOTH,
    BUSINESS_TYPE_REWARDS,
    Tenant,
)


async def business_type_of(session: AsyncSession, tenant_id: UUID) -> str:
    """Return the tenant's business_type ('wallet' | 'rewards' | 'both')."""
    result = await session.execute(select(Tenant.business_type).where(Tenant.id == tenant_id))
    value = result.scalar_one_or_none()
    if value is None:
        raise ValueError(f"tenant {tenant_id} not found")
    return value


async def rewards_from_wallet_enabled(session: AsyncSession, tenant_id: UUID) -> bool:
    """True when internal wallet transactions should drive rewards (both mode)."""
    return await business_type_of(session, tenant_id) == BUSINESS_TYPE_BOTH


async def external_events_allowed(session: AsyncSession, tenant_id: UUID) -> bool:
    """True when external Kafka events may issue rewards (rewards-only mode)."""
    return await business_type_of(session, tenant_id) == BUSINESS_TYPE_REWARDS
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_mode_gating.py::test_business_type_of_returns_stored_mode -v`
Expected: PASS. (If `tenant_factory` isn't a fixture yet, add one in `backend/tests/conftest.py` that inserts a `Tenant` with the given `business_type`.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/shared/models/tenants.py backend/app/shared/tenant_mode.py backend/tests/rewards/test_mode_gating.py
git commit -m "feat(rewards): business_type constants + mode resolver"
```

---

## Task 2: `reward_outbox` model + `reward_events.seen_at` + migration

**Files:**
- Modify: `backend/app/shared/models/rewards.py`
- Create: `backend/alembic/versions/20260803_0050_reward_outbox_and_seen_at.py`
- Test: `backend/tests/rewards/test_outbox_internal.py`

- [ ] **Step 1: Add the model + column**

In `backend/app/shared/models/rewards.py` add:
```python
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

# reward_outbox.status
OUTBOX_PENDING = "pending"
OUTBOX_PROCESSED = "processed"
OUTBOX_FAILED = "failed"

# Wallet transaction types that drive rewards (loop-safe allowlist — excludes
# reward_issuance / cashback_reward / redemption).
REWARDABLE_TYPES = ("p2p", "cash_in", "cash_out", "airtime")


class RewardOutbox(Base):
    """Durable trigger written atomically with a rewardable wallet transaction.

    Drained (immediately post-commit and by a Celery recon sweep) into the
    rules evaluator. Stuck rows ARE the reward reconciliation signal. Carries
    `transaction_id` so a future reversal can look up and claw back.
    """

    __tablename__ = "reward_outbox"
    __table_args__ = (Index("idx_reward_outbox_tenant_status", "tenant_id", "status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    merchant_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=OUTBOX_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)
```
(Confirm `UUID`, `uuid4`, `Decimal`, `func`, `Base` are already imported at top of the file; add any missing.)

Add to the existing `RewardEvent` class:
```python
    seen_at: Mapped[datetime | None] = mapped_column(nullable=True)
```

- [ ] **Step 2: Generate the migration**

Run: `cd backend && alembic revision --autogenerate -m "reward_outbox and seen_at"`
Then rename the file to `20260803_0050_reward_outbox_and_seen_at.py` and review it: it must `create_table('reward_outbox', …)` with the index and `add_column('reward_events', sa.Column('seen_at', sa.DateTime(), nullable=True))`. Remove any unrelated autogen noise.

- [ ] **Step 3: Write the tenant-isolation + column test**

Create `backend/tests/rewards/test_outbox_internal.py`:
```python
"""Internal wallet → rewards outbox behavior."""
import pytest
from sqlalchemy import select
from app.shared.models.rewards import RewardOutbox, OUTBOX_PENDING


@pytest.mark.asyncio
async def test_outbox_row_is_tenant_scoped(session, tenant_factory, user_factory):
    t1 = await tenant_factory()
    t2 = await tenant_factory()
    u1 = await user_factory(tenant_id=t1.id)
    session.add(RewardOutbox(
        tenant_id=t1.id, user_id=u1.id, transaction_id=u1.id,  # any uuid for the FK-less unit test; see note
        transaction_type="p2p", amount=100, currency="ZAR", status=OUTBOX_PENDING,
    ))
    await session.commit()
    rows_t2 = (await session.execute(select(RewardOutbox).where(RewardOutbox.tenant_id == t2.id))).scalars().all()
    assert rows_t2 == []
```
Note: if the FK to `transactions.id` blocks the unit insert, create a real transaction via `post_transaction` in the fixture, or drop the FK to a plain indexed column — prefer a real transaction to keep the FK.

- [ ] **Step 4: Apply migration + run test**

Run: `cd backend && alembic upgrade head && python scripts/check_migrations.py && python -m pytest tests/rewards/test_outbox_internal.py::test_outbox_row_is_tenant_scoped -v`
Expected: migration applies clean; test PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/shared/models/rewards.py backend/alembic/versions/20260803_0050_reward_outbox_and_seen_at.py backend/tests/rewards/test_outbox_internal.py
git commit -m "feat(rewards): reward_outbox table + reward_events.seen_at"
```

---

## Task 3: `RewardTrigger` schema on `PostTransactionRequest`

**Files:**
- Modify: `backend/app/modules/ledger/schemas.py`
- Test: `backend/tests/rewards/test_outbox_internal.py`

- [ ] **Step 1: Write the failing test**

Append to `test_outbox_internal.py`:
```python
from decimal import Decimal
from app.modules.ledger.schemas import RewardTrigger, PostTransactionRequest


def test_reward_trigger_optional_defaults_none():
    # A request without a trigger is valid and defaults to None (no outbox).
    assert PostTransactionRequest.model_fields["reward_trigger"].default is None


def test_reward_trigger_shape(uuid4_value):
    rt = RewardTrigger(user_id=uuid4_value, transaction_type="p2p", amount=Decimal("100"), currency="ZAR")
    assert rt.merchant_id is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_reward_trigger_shape -v`
Expected: FAIL — `ImportError: cannot import name 'RewardTrigger'`.

- [ ] **Step 3: Implement**

In `backend/app/modules/ledger/schemas.py`:
```python
class RewardTrigger(BaseModel):
    """Set by money services when a transaction should drive reward evaluation.

    Its presence (plus tenant business_type == 'both') makes post_transaction
    write a reward_outbox row. Reward-issuance calls leave it None → no loop.
    """
    user_id: UUID
    transaction_type: str
    amount: Decimal
    currency: str
    merchant_id: UUID | None = None
```
Add `reward_trigger: RewardTrigger | None = None` to `PostTransactionRequest`.
(Confirm `BaseModel`, `UUID`, `Decimal` imports exist.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py -k reward_trigger -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/ledger/schemas.py backend/tests/rewards/test_outbox_internal.py
git commit -m "feat(rewards): RewardTrigger on PostTransactionRequest"
```

---

## Task 4: Write outbox row inside `post_transaction` (gated by mode)

**Files:**
- Modify: `backend/app/modules/ledger/service.py`
- Test: `backend/tests/rewards/test_outbox_internal.py`

- [ ] **Step 1: Write the failing test**

Append to `test_outbox_internal.py` (assumes a `post_rewardable_txn` helper that builds a balanced `PostTransactionRequest` with a `reward_trigger`; add it to the test module):
```python
@pytest.mark.asyncio
async def test_outbox_written_only_in_both_mode(session, both_tenant, wallet_tenant, user_factory):
    from app.shared.models.rewards import RewardOutbox
    # both → row written
    ub = await user_factory(tenant_id=both_tenant.id)
    await post_rewardable_txn(session, both_tenant.id, ub.id, "p2p", Decimal("100"), "ZAR")
    assert len((await session.execute(select(RewardOutbox).where(RewardOutbox.tenant_id == both_tenant.id))).scalars().all()) == 1
    # wallet → no row
    uw = await user_factory(tenant_id=wallet_tenant.id)
    await post_rewardable_txn(session, wallet_tenant.id, uw.id, "p2p", Decimal("100"), "ZAR")
    assert (await session.execute(select(RewardOutbox).where(RewardOutbox.tenant_id == wallet_tenant.id))).scalars().all() == []


@pytest.mark.asyncio
async def test_no_outbox_without_reward_trigger(session, both_tenant, user_factory):
    from app.shared.models.rewards import RewardOutbox
    u = await user_factory(tenant_id=both_tenant.id)
    # reward-issuance-style txn: no reward_trigger → loop avoidance
    await post_plain_txn(session, both_tenant.id, u.id, "reward_issuance", Decimal("50"), "PTS")
    assert (await session.execute(select(RewardOutbox).where(RewardOutbox.tenant_id == both_tenant.id))).scalars().all() == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py -k outbox_written -v`
Expected: FAIL — no rows written (feature absent).

- [ ] **Step 3: Implement the outbox write**

In `backend/app/modules/ledger/service.py`, inside `post_transaction`, AFTER `_enforce_balance_guard(...)` and after the transaction + entries are added to the session but BEFORE the commit:
```python
    # Internal wallet → rewards trigger (spec 2026-08-03). Written atomically
    # with the ledger commit so the intent can never be lost. Gated to `both`
    # tenants; only money services pass reward_trigger, so reward issuance
    # itself never loops. Defense-in-depth: enforce the rewardable allowlist.
    if request.reward_trigger is not None:
        from app.shared.models.rewards import REWARDABLE_TYPES, RewardOutbox
        from app.shared.tenant_mode import rewards_from_wallet_enabled

        rt = request.reward_trigger
        if (
            rt.transaction_type in REWARDABLE_TYPES
            and await rewards_from_wallet_enabled(session, request.tenant_id)
        ):
            session.add(
                RewardOutbox(
                    tenant_id=request.tenant_id,
                    user_id=rt.user_id,
                    transaction_id=txn.id,          # the Transaction built above
                    transaction_type=rt.transaction_type,
                    amount=rt.amount,
                    currency=rt.currency,
                    merchant_id=rt.merchant_id,
                )
            )
```
(Use the local variable name for the built `Transaction` as it exists in `post_transaction` — grep the function for the object added to the session; it is committed at the existing `await session.commit()`.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py -k "outbox_written or without_reward_trigger" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/ledger/service.py backend/tests/rewards/test_outbox_internal.py
git commit -m "feat(rewards): post_transaction writes reward_outbox in both mode"
```

---

## Task 5: Extract `evaluate_and_issue_firings` (DRY the issuance core)

**Files:**
- Modify: `backend/app/modules/events/service.py`
- Test: `backend/tests/rewards/test_outbox_internal.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_evaluate_and_issue_firings_issues_points(session, both_tenant, user_factory, first_time_rule_factory):
    from app.modules.events.service import evaluate_and_issue_firings
    from app.modules.events.schemas import NormalisedEvent
    from datetime import datetime, timezone
    u = await user_factory(tenant_id=both_tenant.id)
    await first_time_rule_factory(tenant_id=both_tenant.id, transaction_type="p2p", reward_value=50)
    ev = NormalisedEvent(event_id="txn-1", source_key="internal:wallet", tenant_id=both_tenant.id,
                         user_id=u.id, transaction_type="p2p", amount=Decimal("100"), currency="ZAR",
                         merchant_id=None, timestamp=datetime.now(timezone.utc))
    firings = await evaluate_and_issue_firings(session, ev)
    await session.commit()
    assert len(firings) == 1 and firings[0].reward_value == Decimal("50")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_evaluate_and_issue_firings_issues_points -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate_and_issue_firings'`.

- [ ] **Step 3: Extract the function and reuse it in `process_external_event`**

In `backend/app/modules/events/service.py` add:
```python
async def evaluate_and_issue_firings(session: AsyncSession, event: NormalisedEvent) -> list[FiringOut]:
    """Evaluate active rules for an event and issue points for each firing.

    Shared by the external Kafka path (process_external_event) and the internal
    wallet outbox drainer. Does NOT commit — the caller owns the transaction.
    Idempotent via reward_events(user, rule, triggering_event_id).
    """
    firings: list[RuleFiring] = await evaluate_active_rules_for_event(session, event)
    issued: list[FiringOut] = []
    for firing in firings:
        await issue_points_reward(
            session,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            rule=firing.rule,
            triggering_event_id=event.event_id,
            reward_value=firing.reward_value,
        )
        issued.append(
            FiringOut(
                rule_id=firing.rule.id,
                rule_name=firing.rule.name,
                reward_type=firing.rule.reward_type,
                reward_value=firing.reward_value,
            )
        )
    return issued
```
Then replace the inline steps 6–7 in `process_external_event` with:
```python
    event = normalise(raw, source.field_mapping)
    issued = await evaluate_and_issue_firings(session, event)
    await session.commit()
    return IngestResponse(outcome="processed", event_id=raw.event_id, rules_fired=issued)
```

- [ ] **Step 4: Run the new test + the existing external-event tests**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_evaluate_and_issue_firings_issues_points tests/events -v`
Expected: new test PASS; existing event tests still PASS (behavior unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/events/service.py backend/tests/rewards/test_outbox_internal.py
git commit -m "refactor(rewards): extract evaluate_and_issue_firings shared core"
```

---

## Task 6: Outbox drainer + immediate attempt

**Files:**
- Create: `backend/app/modules/rewards/outbox.py`
- Test: `backend/tests/rewards/test_outbox_internal.py`

- [ ] **Step 1: Write the failing test (immediate attempt issues + marks processed + idempotent)**

```python
@pytest.mark.asyncio
async def test_attempt_immediate_issues_and_is_idempotent(session_factory, both_tenant, user_factory, first_time_rule_factory):
    from app.modules.rewards.outbox import attempt_immediate
    from app.shared.models.rewards import RewardOutbox, RewardEvent, OUTBOX_PROCESSED
    from sqlalchemy import select, func
    async with session_factory() as s:
        u = await user_factory(tenant_id=both_tenant.id)
        await first_time_rule_factory(tenant_id=both_tenant.id, transaction_type="p2p", reward_value=50)
        await post_rewardable_txn(s, both_tenant.id, u.id, "p2p", Decimal("100"), "ZAR")
    # first drain issues one reward
    firings = await attempt_immediate(session_factory, tenant_id=both_tenant.id, user_id=u.id)
    assert len(firings) == 1
    # second drain finds no pending rows → no double issue
    firings2 = await attempt_immediate(session_factory, tenant_id=both_tenant.id, user_id=u.id)
    assert firings2 == []
    async with session_factory() as s:
        assert (await s.execute(select(func.count()).select_from(RewardEvent).where(RewardEvent.user_id == u.id))).scalar_one() == 1
        assert (await s.execute(select(RewardOutbox.status).where(RewardOutbox.user_id == u.id))).scalar_one() == OUTBOX_PROCESSED
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_attempt_immediate_issues_and_is_idempotent -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.rewards.outbox`.

- [ ] **Step 3: Implement the drainer**

Create `backend/app/modules/rewards/outbox.py`:
```python
"""Drain reward_outbox rows into the rules evaluator.

Two callers: `attempt_immediate` (post-commit fast path, for the mobile
celebration) and `recon_sweep` (Celery beat — durability + reconciliation).
Both go through `evaluate_and_issue_firings`, which is idempotent, so running
both can never double-issue.

Reversal hook (designed, NOT implemented): reward_outbox.transaction_id records
the source transaction. When reversals exist, a reversal txn will emit its own
row and a handler here will look up the original reward_events and post an
append-only claw-back. No claw-back logic is built now.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.events.schemas import FiringOut, NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.shared.models.rewards import (
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PROCESSED,
    RewardOutbox,
)

MAX_ATTEMPTS = 5
INTERNAL_SOURCE_KEY = "internal:wallet"


def _event_from_row(row: RewardOutbox) -> NormalisedEvent:
    return NormalisedEvent(
        event_id=str(row.transaction_id),   # idempotency key for reward_events
        source_key=INTERNAL_SOURCE_KEY,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        transaction_type=row.transaction_type,
        amount=row.amount,
        currency=row.currency,
        merchant_id=row.merchant_id,
        timestamp=row.created_at,
    )


async def _drain_row(session: AsyncSession, row: RewardOutbox) -> list[FiringOut]:
    """Issue rewards for one outbox row and mark it processed. Caller commits."""
    firings = await evaluate_and_issue_firings(session, _event_from_row(row))
    row.status = OUTBOX_PROCESSED
    row.processed_at = datetime.now(timezone.utc)
    return firings


async def attempt_immediate(
    session_factory: async_sessionmaker[AsyncSession], *, tenant_id: UUID, user_id: UUID
) -> list[FiringOut]:
    """Fast-path drain of this user's pending rows, in a fresh session.

    Called by money services AFTER post_transaction commits (invariant 6).
    Failures are swallowed and recorded on the row for the recon sweep to retry
    — a reward hiccup must never surface on the money path.
    """
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(RewardOutbox)
                .where(
                    RewardOutbox.tenant_id == tenant_id,
                    RewardOutbox.user_id == user_id,
                    RewardOutbox.status == OUTBOX_PENDING,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        all_firings: list[FiringOut] = []
        for row in rows:
            try:
                all_firings.extend(await _drain_row(session, row))
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - fail-open, recon retries
                await session.rollback()
                row.attempts += 1
                row.last_error = str(exc)[:500]
                row.status = OUTBOX_FAILED
                await session.commit()
        return all_firings
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_attempt_immediate_issues_and_is_idempotent -v`
Expected: PASS. (If `session_factory` isn't a fixture, add one wrapping the test engine's `async_sessionmaker`.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/rewards/outbox.py backend/tests/rewards/test_outbox_internal.py
git commit -m "feat(rewards): outbox drainer + immediate post-commit attempt"
```

---

## Task 7: Celery recon sweep

**Files:**
- Modify: `backend/app/modules/rewards/outbox.py`, Celery app/beat config (grep for `celery` app: `backend/app/worker/celery_app.py` or similar).
- Test: `backend/tests/rewards/test_outbox_internal.py`

- [ ] **Step 1: Write the failing test (recon drains a stuck pending row)**

```python
@pytest.mark.asyncio
async def test_recon_sweep_drains_pending(session_factory, both_tenant, user_factory, first_time_rule_factory):
    from app.modules.rewards.outbox import recon_sweep_async
    from app.shared.models.rewards import RewardOutbox, OUTBOX_PROCESSED
    from sqlalchemy import select
    async with session_factory() as s:
        u = await user_factory(tenant_id=both_tenant.id)
        await first_time_rule_factory(tenant_id=both_tenant.id, transaction_type="p2p", reward_value=50)
        await post_rewardable_txn(s, both_tenant.id, u.id, "p2p", Decimal("100"), "ZAR")
    processed = await recon_sweep_async(session_factory, batch=50)
    assert processed == 1
    async with session_factory() as s:
        assert (await s.execute(select(RewardOutbox.status).where(RewardOutbox.user_id == u.id))).scalar_one() == OUTBOX_PROCESSED
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_recon_sweep_drains_pending -v`
Expected: FAIL — `cannot import name 'recon_sweep_async'`.

- [ ] **Step 3: Implement recon (async core + Celery task wrapper)**

Append to `backend/app/modules/rewards/outbox.py`:
```python
async def recon_sweep_async(
    session_factory: async_sessionmaker[AsyncSession], *, batch: int = 100
) -> int:
    """Drain up to `batch` pending/retryable-failed rows across all tenants.

    This is the reconciliation: any reward missed by the immediate attempt
    (crash, transient error) is picked up here. Returns count processed.
    """
    processed = 0
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(RewardOutbox)
                .where(
                    RewardOutbox.status.in_((OUTBOX_PENDING, OUTBOX_FAILED)),
                    RewardOutbox.attempts < MAX_ATTEMPTS,
                )
                .order_by(RewardOutbox.created_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for row in rows:
            try:
                await _drain_row(session, row)
                await session.commit()
                processed += 1
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                row.attempts += 1
                row.last_error = str(exc)[:500]
                row.status = OUTBOX_FAILED
                await session.commit()
    return processed
```
Register the Celery task in the worker module (match the existing pattern for other periodic tasks — grep for `@shared_task` / `beat_schedule`):
```python
@shared_task(name="rewards.recon_sweep")
def recon_sweep() -> int:
    from app.shared.db import async_session_factory  # the app's sessionmaker
    return asyncio.run(recon_sweep_async(async_session_factory))
```
Add to `beat_schedule` (every 60s):
```python
"rewards-recon-sweep": {"task": "rewards.recon_sweep", "schedule": 60.0},
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_recon_sweep_drains_pending -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/rewards/outbox.py backend/app/worker/ backend/tests/rewards/test_outbox_internal.py
git commit -m "feat(rewards): Celery recon sweep for outbox reconciliation"
```

---

## Task 8: Wire money services to trigger rewards (p2p first, then the rest)

**Files:**
- Modify: `backend/app/modules/payments/service.py` (p2p); then `cash_in`/`cash_out`/`airtime` services.
- Test: `backend/tests/rewards/test_outbox_internal.py`

- [ ] **Step 1: Write the failing end-to-end test (p2p in both mode issues a reward inline)**

```python
@pytest.mark.asyncio
async def test_p2p_in_both_mode_issues_reward_inline(client, both_tenant, seed_two_users, first_time_rule_factory):
    # seed_two_users returns (sender_headers, sender_id, recipient_identifier)
    headers, sender_id, recipient = seed_two_users
    await first_time_rule_factory(tenant_id=both_tenant.id, transaction_type="p2p", reward_value=50)
    resp = await client.post("/api/v1/payments/p2p",
        headers={**headers, "Idempotency-Key": "k1"},
        json={"recipient_identifier": recipient, "amount": "100", "currency": "ZAR"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["earned_points"] == "50"  # inline reward for the celebration
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_p2p_in_both_mode_issues_reward_inline -v`
Expected: FAIL — `earned_points` is 0/absent (no trigger wired).

- [ ] **Step 3: Set `reward_trigger` and call `attempt_immediate` in the p2p service**

In `backend/app/modules/payments/service.py`, where the p2p `PostTransactionRequest` is built, add:
```python
    reward_trigger=RewardTrigger(
        user_id=sender_id, transaction_type="p2p", amount=amount, currency=currency,
    ),
```
After `post_transaction(...)` returns (post-commit), drain and surface inline:
```python
    from app.modules.rewards.outbox import attempt_immediate
    firings = await attempt_immediate(async_session_factory, tenant_id=tenant_id, user_id=sender_id)
    earned_points = sum((f.reward_value for f in firings if f.reward_type == "points"), Decimal("0"))
    # include earned_points in the response schema (extend the existing P2PResult)
```
(Match the existing response schema field the mobile app reads — the Explore map shows `earned_points` already flows to `mobile/app/p2p/success.tsx`. Reuse that field.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_p2p_in_both_mode_issues_reward_inline -v`
Expected: PASS.

- [ ] **Step 5: Repeat for cash_in / cash_out / airtime**

For each money service, set `reward_trigger` with the **initiator** `user_id`
(cash_in/out: the agent or the customer per product rule — use the same
principal the limits service anchors to) and the correct `transaction_type`,
and call `attempt_immediate` post-commit. Add one end-to-end test per service
mirroring Step 1.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/payments/service.py backend/app/modules/money_operations backend/app/modules/airtime backend/tests/rewards/test_outbox_internal.py
git commit -m "feat(rewards): money paths trigger rewards + inline earned_points (both mode)"
```

---

## Task 9: Mode-gate `process_external_event` to `rewards` tenants

**Files:**
- Modify: `backend/app/modules/events/service.py`
- Test: `backend/tests/rewards/test_mode_gating.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_mode_gating.py`:
```python
@pytest.mark.asyncio
async def test_external_event_accepted_for_rewards_tenant(session, rewards_tenant, registered_source_factory, raw_event_factory):
    from app.modules.events.service import process_external_event
    src = await registered_source_factory(tenant_id=rewards_tenant.id)
    raw = raw_event_factory(source_key=src.source_key)
    resp = await process_external_event(session, raw)
    assert resp.outcome in ("processed", "duplicate")


@pytest.mark.asyncio
async def test_external_event_rejected_for_both_tenant(session, both_tenant, registered_source_factory, raw_event_factory):
    from app.modules.events.service import process_external_event
    src = await registered_source_factory(tenant_id=both_tenant.id)
    raw = raw_event_factory(source_key=src.source_key)
    resp = await process_external_event(session, raw)
    assert resp.outcome == "rejected" and "mode" in (resp.rejection_reason or "")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_mode_gating.py -k external_event -v`
Expected: `test_external_event_rejected_for_both_tenant` FAILS (currently processed).

- [ ] **Step 3: Implement the reject guard**

In `process_external_event`, right after the tenant-scope check (before dedup/normalise):
```python
    from app.shared.tenant_mode import external_events_allowed
    if not await external_events_allowed(session, source.tenant_id):
        await _log_rejected(session, raw, source, reason="wrong_mode")
        await session.commit()
        return IngestResponse(outcome="rejected", event_id=raw.event_id, rejection_reason="wrong_mode")
```
(Match `_log_rejected`'s existing signature — grep `def _log_rejected`.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_mode_gating.py -k external_event -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/events/service.py backend/tests/rewards/test_mode_gating.py
git commit -m "feat(rewards): external events issue rewards only for rewards-mode tenants"
```

---

## Task 10: `GET /me/rewards` (catalog + progress + recent)

**Files:**
- Modify: `backend/app/modules/identity/router.py`, `backend/app/modules/identity/schemas.py`
- Create: `backend/app/modules/rewards/read_service.py` (query + progress projection)
- Test: `backend/tests/rewards/test_me_rewards.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/rewards/test_me_rewards.py`:
```python
import pytest


@pytest.mark.asyncio
async def test_me_rewards_disabled_for_wallet_tenant(client, wallet_user_headers):
    resp = await client.get("/api/v1/identity/me/rewards", headers=wallet_user_headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_me_rewards_shows_progress_for_both_tenant(client, both_user_headers, milestone_rule_3_p2p, do_one_p2p):
    resp = await client.get("/api/v1/identity/me/rewards", headers=both_user_headers)
    body = resp.json()
    assert body["enabled"] is True
    cat = next(c for c in body["catalog"] if c["rule_id"] == str(milestone_rule_3_p2p.id))
    assert cat["progress"] == {"current": 1, "target": 3, "label": "P2P transfers"}
    assert cat["status"] == "in_progress"


@pytest.mark.asyncio
async def test_me_rewards_requires_auth(client):
    assert (await client.get("/api/v1/identity/me/rewards")).status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_me_rewards.py -v`
Expected: FAIL — 404 (route absent).

- [ ] **Step 3: Implement read service + progress projection**

Create `backend/app/modules/rewards/read_service.py`:
```python
"""Read-side projection of rewards for the mobile app (GET /me/rewards)."""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models.rewards import RewardEvent
from app.shared.models.rules import Rule, UserRuleProgress
from app.shared.tenant_mode import business_type_of
from app.shared.models.tenants import BUSINESS_TYPE_WALLET

# transaction_type → human label for progress lines
_LABELS = {"p2p": "P2P transfers", "cash_in": "cash-ins", "cash_out": "cash-outs", "airtime": "airtime top-ups"}


def _project(rule: Rule, progress: UserRuleProgress | None) -> dict:
    """Map a rule + the user's progress to {current, target, label, status}."""
    label = _LABELS.get(rule.transaction_type, rule.transaction_type)
    if rule.rule_type == "milestone":
        current = progress.current_count if progress else 0
        target = rule.target_count or 0
    elif rule.rule_type == "streak":
        current = progress.current_streak if progress else 0
        target = rule.streak_length or 0
    else:  # first_time / value_based / campaign / composite → binary-ish
        current = 1 if (progress and progress.trigger_count) else 0
        target = 1
    status = "earned" if progress and progress.status == "completed" else ("in_progress" if current else "locked")
    return {"current": current, "target": target, "label": label, "status": status}


async def list_my_rewards(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> dict:
    if await business_type_of(session, tenant_id) == BUSINESS_TYPE_WALLET:
        return {"enabled": False, "catalog": [], "recent": []}

    rules = (await session.execute(
        select(Rule).where(Rule.tenant_id == tenant_id, Rule.status == "active")
    )).scalars().all()
    progress_rows = (await session.execute(
        select(UserRuleProgress).where(UserRuleProgress.user_id == user_id)
    )).scalars().all()
    by_rule = {p.rule_id: p for p in progress_rows}

    catalog = []
    for rule in rules:
        if rule.segment_id is not None:
            from app.modules.segments.service import user_is_in_segment
            if not await user_is_in_segment(session, user_id=user_id, segment_id=rule.segment_id):
                continue
        proj = _project(rule, by_rule.get(rule.id))
        catalog.append({
            "rule_id": rule.id, "name": rule.name, "description": rule.description,
            "reward_type": rule.reward_type, "reward_value": rule.reward_value,
            "currency": getattr(rule, "reward_currency", None),
            "status": proj.pop("status"), "progress": proj,
        })

    recent = (await session.execute(
        select(RewardEvent).where(RewardEvent.user_id == user_id)
        .order_by(RewardEvent.created_at.desc()).limit(20)
    )).scalars().all()
    recent_out = [{
        "reward_event_id": r.id, "rule_name": getattr(r, "rule_name", None),
        "reward_type": r.reward_type, "value": r.reward_value, "currency": r.currency,
        "earned_at": r.created_at, "seen": r.seen_at is not None,
    } for r in recent]
    return {"enabled": True, "catalog": catalog, "recent": recent_out}
```
(Confirm the exact `Rule` / `UserRuleProgress` / `RewardEvent` column names against `app/shared/models/rules.py` and `rewards.py`; adjust `target_count`, `streak_length`, `reward_currency`, `rule_name` to the real names — grep before finalizing.)

Add schemas to `identity/schemas.py` (`ProgressOut`, `RewardCatalogItemOut`, `RecentRewardOut`, `RewardsOut`) and the route to `identity/router.py`:
```python
@router.get("/me/rewards", response_model=RewardsOut)
async def get_me_rewards(
    user: UserPrincipal = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> RewardsOut:
    """Return the signed-in user's available rewards + progress + recent earns."""
    payload = await list_my_rewards(session, tenant_id=user.tenant_id, user_id=user.id)
    return RewardsOut.model_validate(payload)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_me_rewards.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/rewards/read_service.py backend/app/modules/identity/router.py backend/app/modules/identity/schemas.py backend/tests/rewards/test_me_rewards.py
git commit -m "feat(rewards): GET /me/rewards catalog + progress + recent"
```

---

## Task 11: `POST /me/rewards/seen` (one-shot celebration)

**Files:**
- Modify: `backend/app/modules/identity/router.py`, `backend/app/modules/rewards/read_service.py`, `identity/schemas.py`
- Test: `backend/tests/rewards/test_me_rewards.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_mark_rewards_seen_flips_flag(client, both_user_headers, earned_reward_event):
    ids = [str(earned_reward_event.id)]
    resp = await client.post("/api/v1/identity/me/rewards/seen", headers=both_user_headers, json={"reward_event_ids": ids})
    assert resp.status_code == 200
    body = (await client.get("/api/v1/identity/me/rewards", headers=both_user_headers)).json()
    assert next(r for r in body["recent"] if r["reward_event_id"] in ids)["seen"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/rewards/test_me_rewards.py::test_mark_rewards_seen_flips_flag -v`
Expected: FAIL — 404.

- [ ] **Step 3: Implement**

In `read_service.py`:
```python
from datetime import datetime, timezone
from sqlalchemy import update


async def mark_rewards_seen(session: AsyncSession, *, tenant_id: UUID, user_id: UUID, reward_event_ids: list[UUID]) -> int:
    """Set seen_at on the caller's own reward_events. Tenant/user-scoped. Idempotent."""
    if not reward_event_ids:
        return 0
    result = await session.execute(
        update(RewardEvent)
        .where(RewardEvent.user_id == user_id, RewardEvent.id.in_(reward_event_ids), RewardEvent.seen_at.is_(None))
        .values(seen_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return result.rowcount or 0
```
Route in `identity/router.py` (+ `MarkSeenIn` schema `{reward_event_ids: list[UUID]}`):
```python
@router.post("/me/rewards/seen")
async def post_me_rewards_seen(
    body: MarkSeenIn,
    user: UserPrincipal = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    n = await mark_rewards_seen(session, tenant_id=user.tenant_id, user_id=user.id, reward_event_ids=body.reward_event_ids)
    return {"marked": n}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/rewards/test_me_rewards.py::test_mark_rewards_seen_flips_flag -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/rewards/read_service.py backend/app/modules/identity/router.py backend/app/modules/identity/schemas.py backend/tests/rewards/test_me_rewards.py
git commit -m "feat(rewards): POST /me/rewards/seen one-shot celebration flag"
```

---

## Task 12: Reversal hook — skipped test recording intent

**Files:**
- Test: `backend/tests/rewards/test_outbox_internal.py`

- [ ] **Step 1: Add a skipped test that documents the designed-not-built hook**

```python
@pytest.mark.skip(reason="reversal claw-back is a designed-but-unbuilt hook; reversals don't exist yet (spec 2026-08-03 §4)")
@pytest.mark.asyncio
async def test_reversal_claws_back_reward():
    # When reversals land: a reversal txn emits a reward_outbox row; the handler
    # looks up the original reward_events (via transaction_id), posts an
    # append-only claw-back to system_points_issuance, and decrements
    # user_rule_progress. reward_outbox.transaction_id is the hook.
    ...
```

- [ ] **Step 2: Run to confirm it is collected and skipped**

Run: `cd backend && python -m pytest tests/rewards/test_outbox_internal.py::test_reversal_claws_back_reward -v`
Expected: SKIPPED (with reason).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/rewards/test_outbox_internal.py
git commit -m "test(rewards): record reversal claw-back hook (skipped, designed-not-built)"
```

---

## Task 13: Mobile — rewards API client

**Files:**
- Create: `mobile/lib/api/rewards.ts`

- [ ] **Step 1: Implement the client (mirror `mobile/lib/api/limits.ts`)**

```typescript
/** Rewards API client — catalog + progress and the one-shot "seen" flag. */
import { apiGet, apiPost } from '@/lib/api/client';

export interface RewardProgress { current: number; target: number; label: string; }
export interface RewardCatalogItem {
  rule_id: string; name: string; description: string | null;
  reward_type: string; reward_value: string; currency: string | null;
  status: 'locked' | 'in_progress' | 'earned'; progress: RewardProgress;
}
export interface RecentReward {
  reward_event_id: string; rule_name: string | null; reward_type: string;
  value: string; currency: string | null; earned_at: string; seen: boolean;
}
export interface RewardsResponse { enabled: boolean; catalog: RewardCatalogItem[]; recent: RecentReward[]; }

/** GET the signed-in user's rewards (catalog + progress + recent). */
export async function getRewards(): Promise<RewardsResponse> {
  return apiGet<RewardsResponse>('/api/v1/identity/me/rewards');
}

/** Mark earned rewards as seen so the celebration fires once. */
export async function markRewardsSeen(rewardEventIds: string[]): Promise<void> {
  await apiPost('/api/v1/identity/me/rewards/seen', { reward_event_ids: rewardEventIds });
}
```
(Confirm the real helper names in `mobile/lib/api/client.ts` — use whatever `limits.ts` imports.)

- [ ] **Step 2: Typecheck**

Run: `cd mobile && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add mobile/lib/api/rewards.ts
git commit -m "feat(mobile): rewards API client"
```

---

## Task 14: Mobile — Rewards screen + tile route

**Files:**
- Create: `mobile/app/rewards/index.tsx`
- Modify: `mobile/app/home.tsx` (Rewards tile route)

- [ ] **Step 1: Build the rewards screen**

Create `mobile/app/rewards/index.tsx` with a `useQuery(['rewards'], getRewards)`; if
`!enabled` show an empty state; else render `catalog` as clay cards each with a
progress bar (`progress.current / progress.target`, label, reward value) and a
`recent` list. Reuse `useColors()` + clay primitives and the `ActivityRow`
pattern. (Match existing screens like `mobile/app/limits/index.tsx`.)

- [ ] **Step 2: Point the home tile at the screen**

In `mobile/app/home.tsx`, change the `redemption`/Rewards `SERVICE_TILE` entry
`route` from `() => '/home'` to `() => '/rewards'`.

- [ ] **Step 3: Typecheck**

Run: `cd mobile && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add mobile/app/rewards/index.tsx mobile/app/home.tsx
git commit -m "feat(mobile): rewards screen + wire Rewards home tile"
```

---

## Task 15: Mobile — celebration graphic on unseen reward

**Files:**
- Create: `mobile/components/rewards/RewardCelebration.tsx`
- Modify: `mobile/app/home.tsx`

- [ ] **Step 1: Build the celebration component**

Create `mobile/components/rewards/RewardCelebration.tsx` — a modal/overlay that,
given a `RecentReward`, shows the gift graphic + "You earned {value} points!"
with a short entrance animation (reuse the app's animation approach). Props:
`{ reward: RecentReward; onDismiss: () => void }`.

- [ ] **Step 2: Trigger from home on unseen rewards**

In `mobile/app/home.tsx`, after the rewards query resolves, compute
`unseen = recent.filter(r => !r.seen)`. If non-empty, render
`<RewardCelebration reward={unseen[0]} onDismiss={...} />`; on dismiss call
`markRewardsSeen(unseen.map(r => r.reward_event_id))` and invalidate the
`['rewards']` query. Gate the whole block on `enabled`.

- [ ] **Step 3: Typecheck**

Run: `cd mobile && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add mobile/components/rewards/RewardCelebration.tsx mobile/app/home.tsx
git commit -m "feat(mobile): one-shot reward celebration graphic"
```

---

## Final verification

- [ ] Backend targeted suites green:

Run: `cd backend && python -m pytest tests/rewards tests/events -v`
Expected: all PASS (reversal test SKIPPED).

- [ ] Migration gate:

Run: `cd backend && python scripts/check_migrations.py`
Expected: no pending model/migration drift.

- [ ] Mobile typecheck:

Run: `cd mobile && npx tsc --noEmit`
Expected: exit 0.

- [ ] Offer (do NOT auto-run per project rule) a full backend suite + a build to the user.

---

## Self-review notes (author)

- **Spec coverage:** matrix (Tasks 1,4,9,10) · outbox+immediate+recon (4,6,7) · loop avoidance (4) · idempotency (6) · reversal hook (2,12) · mobile catalog/progress/celebration (13,14,15) · seen flag (2,11). All spec sections mapped.
- **Signature confirmations required before coding** (grep, don't guess): the built `Transaction` var name in `post_transaction`; `_log_rejected` signature; `Rule` columns (`target_count`, `streak_length`, `reward_currency`, `status` value `active`), `UserRuleProgress` columns (`current_count`, `current_streak`, `trigger_count`, `status`/`completed`), `RewardEvent` columns (`reward_value`, `currency`, `rule_name?`); the app's `async_session_factory` import path; Celery app + `beat_schedule` location; `mobile/lib/api/client.ts` helper names.
- **Frontend tests deferred** per `.claude/rules/coding-guidelines.md` §4 (mobile) — typecheck only.
