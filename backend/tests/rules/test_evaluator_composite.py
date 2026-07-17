"""Tests for the composite rule type — Epic 10 / WAL-75 (Pay-PRD-0619).

A composite rule combines its `rule_conditions` with `composite_operator`
(AND / OR). Each sub-condition is satisfied when the user's count of
qualifying COMPLETED transactions of that transaction_type (each >=
min_amount when set) reaches its count_threshold, counted within the current
window (`user_rule_progress.window_start`).

The engine is driven via the public events/external HTTP path so the
candidate query (subquery on rule_conditions) + dispatcher + async evaluator
are exercised end-to-end. Qualifying transactions are seeded directly on the
`transactions` table — the durable, source-agnostic record the evaluator
counts.

Note on structure: the admin JWT the fixture mints is short-lived, so each
test performs its admin-authenticated calls promptly and batches direct-DB
seeding into as few commits as possible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    TXN_STATUS_COMPLETED,
    Account,
    BonusMultiplier,
    RewardEvent,
    Rule,
    Segment,
    Tenant,
    Transaction,
    User,
)


async def _register_source(client: AsyncClient, tenant: Tenant, key: str) -> None:
    """Register the dev event source so ingest calls work (admin-only)."""
    resp = await client.post(
        "/api/v1/events/sources",
        json={"tenant_id": str(tenant.id), "name": f"src-{key}", "source_key": key},
    )
    assert resp.status_code == 201, resp.text


async def _create_composite_rule(
    client: AsyncClient,
    tenant: Tenant,
    *,
    operator: str,
    conditions: list[dict],
    reward_value: str = "100",
    resets_after_trigger: bool = True,
    stop_after_n_triggers: int | None = None,
) -> str:
    """Create a composite rule via the API; return its id (admin-only)."""
    body: dict = {
        "tenant_id": str(tenant.id),
        "name": f"composite-{uuid4().hex[:6]}",
        "rule_type": "composite",
        "composite_operator": operator,
        "conditions": conditions,
        "reward_type": "points",
        "reward_value": reward_value,
        "resets_after_trigger": resets_after_trigger,
    }
    if stop_after_n_triggers is not None:
        body["stop_after_n_triggers"] = stop_after_n_triggers
    resp = await client.post("/api/v1/rules", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _txn(
    tenant: Tenant,
    user: User,
    *,
    txn_type: str,
    amount: str,
    when: datetime | None = None,
) -> Transaction:
    """Build one COMPLETED transaction the composite evaluator will count."""
    txn = Transaction(
        tenant_id=tenant.id,
        idempotency_key=uuid4().hex,
        transaction_type=txn_type,
        status=TXN_STATUS_COMPLETED,
        initiated_by=user.id,
        amount=Decimal(amount),
        currency="ZAR",
    )
    if when is not None:
        txn.created_at = when
    return txn


async def _seed(
    session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    txns: list[Transaction],
    with_points_accounts: bool = True,
) -> None:
    """Seed points accounts + qualifying transactions in a SINGLE commit.

    Batching keeps the number of (slow) commits down so the short-lived admin
    token stays valid across the test's authenticated calls.
    """
    if with_points_accounts:
        session.add(
            Account(
                tenant_id=tenant.id,
                account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
                currency="PTS",
            )
        )
        session.add(
            Account(
                tenant_id=tenant.id,
                user_id=user.id,
                account_type="points_account",
                currency="PTS",
            )
        )
    for txn in txns:
        session.add(txn)
    await session.commit()


def _event(
    *,
    tenant: Tenant,
    user: User,
    source_key: str,
    txn_type: str,
    when: datetime | None = None,
    event_id: str | None = None,
) -> dict:
    """Build a RawExternalEvent body that triggers composite re-evaluation.

    The event's own amount is irrelevant to composite counting (the rule
    counts `transactions`, not the driving event) but must be > 0 to satisfy
    the RawExternalEvent schema.
    """
    return {
        "event_id": event_id or uuid4().hex,
        "source_key": source_key,
        "tenant_id": str(tenant.id),
        "user_id": str(user.id),
        "transaction_type": txn_type,
        "amount": "1",
        "currency": "ZAR",
        "timestamp": (when or datetime.now(UTC)).isoformat(),
    }


async def _ingest(client: AsyncClient, body: dict) -> dict:
    """Send one event; return the parsed response body."""
    resp = await client.post("/api/v1/events/external", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _reward_count(session: AsyncSession, rule_id: str, user: User) -> int:
    """Count reward_events issued for a rule/user (idempotency assertions)."""
    return int(
        (
            await session.execute(
                select(func.count(RewardEvent.id)).where(
                    RewardEvent.rule_id == rule_id,
                    RewardEvent.user_id == user.id,
                )
            )
        ).scalar_one()
    )


_TWO_CONDS = [
    {"transaction_type": "fund", "count_threshold": 1},
    {"transaction_type": "send", "count_threshold": 1},
]


# -----------------------------------------------------------------------------
# AND
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_and_fires_when_all_conditions_met(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """AND(fund>=1, send>=1): both satisfied → fires."""
    await _register_source(async_client, test_tenant, "cmp-and-1")
    await _create_composite_rule(
        async_client, test_tenant, operator="AND", conditions=_TWO_CONDS
    )
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="100"),
            _txn(test_tenant, test_user, txn_type="send", amount="100"),
        ],
    )
    body = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-and-1", txn_type="fund"),
    )
    assert len(body["rules_fired"]) == 1


@pytest.mark.asyncio
async def test_composite_and_does_not_fire_when_one_condition_below(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """AND(fund>=1, send>=1): only fund satisfied → does not fire."""
    await _register_source(async_client, test_tenant, "cmp-and-2")
    await _create_composite_rule(
        async_client, test_tenant, operator="AND", conditions=_TWO_CONDS
    )
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[_txn(test_tenant, test_user, txn_type="fund", amount="100")],
    )
    body = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-and-2", txn_type="fund"),
    )
    assert body["rules_fired"] == []


@pytest.mark.asyncio
async def test_composite_condition_respects_min_amount_and_count(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """AND(fund>=2 @>=100): a below-min fund does not count toward the threshold."""
    await _register_source(async_client, test_tenant, "cmp-min")
    await _create_composite_rule(
        async_client,
        test_tenant,
        operator="AND",
        conditions=[
            {"transaction_type": "fund", "count_threshold": 2, "min_amount": "100"},
            {"transaction_type": "send", "count_threshold": 1},
        ],
    )
    # One qualifying fund (>=100), one below-min fund (ignored), one send.
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="150"),
            _txn(test_tenant, test_user, txn_type="fund", amount="50"),
            _txn(test_tenant, test_user, txn_type="send", amount="10"),
        ],
    )
    first = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-min", txn_type="fund"),
    )
    assert first["rules_fired"] == []  # only 1 qualifying fund, need 2

    # Add a second qualifying fund → now AND is satisfied.
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[_txn(test_tenant, test_user, txn_type="fund", amount="200")],
        with_points_accounts=False,
    )
    second = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-min", txn_type="fund"),
    )
    assert len(second["rules_fired"]) == 1


# -----------------------------------------------------------------------------
# OR
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_or_fires_when_any_condition_met(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """OR(fund>=1, send>=1): only fund satisfied → fires."""
    await _register_source(async_client, test_tenant, "cmp-or-1")
    await _create_composite_rule(
        async_client, test_tenant, operator="OR", conditions=_TWO_CONDS
    )
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[_txn(test_tenant, test_user, txn_type="fund", amount="100")],
    )
    body = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-or-1", txn_type="fund"),
    )
    assert len(body["rules_fired"]) == 1


@pytest.mark.asyncio
async def test_composite_or_does_not_fire_when_none_met(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """OR(fund>=2, send>=2): neither threshold reached → does not fire."""
    await _register_source(async_client, test_tenant, "cmp-or-2")
    await _create_composite_rule(
        async_client,
        test_tenant,
        operator="OR",
        conditions=[
            {"transaction_type": "fund", "count_threshold": 2},
            {"transaction_type": "send", "count_threshold": 2},
        ],
    )
    # One of each — below both thresholds.
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="100"),
            _txn(test_tenant, test_user, txn_type="send", amount="100"),
        ],
    )
    body = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-or-2", txn_type="fund"),
    )
    assert body["rules_fired"] == []


# -----------------------------------------------------------------------------
# Idempotency, reset, stop-after-N
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_idempotent_re_evaluation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Replaying the SAME event_id must not fire (or credit) twice."""
    await _register_source(async_client, test_tenant, "cmp-idem")
    rule_id = await _create_composite_rule(
        async_client, test_tenant, operator="AND", conditions=_TWO_CONDS
    )
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="100"),
            _txn(test_tenant, test_user, txn_type="send", amount="100"),
        ],
    )
    ev = _event(
        tenant=test_tenant,
        user=test_user,
        source_key="cmp-idem",
        txn_type="fund",
        event_id="fixed-composite-event",
    )
    first = await _ingest(async_client, ev)
    second = await _ingest(async_client, ev)  # same event_id → replay

    assert len(first["rules_fired"]) == 1
    assert second["outcome"] == "duplicate"
    assert await _reward_count(db_session, rule_id, test_user) == 1


@pytest.mark.asyncio
async def test_composite_reset_opens_new_window_and_fires_again(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """resets_after_trigger=True: after firing, only later txns count; refires."""
    await _register_source(async_client, test_tenant, "cmp-reset")
    rule_id = await _create_composite_rule(
        async_client,
        test_tenant,
        operator="AND",
        conditions=_TWO_CONDS,
        resets_after_trigger=True,
    )
    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="100", when=t0),
            _txn(test_tenant, test_user, txn_type="send", amount="100", when=t0),
        ],
    )
    first = await _ingest(
        async_client,
        _event(
            tenant=test_tenant,
            user=test_user,
            source_key="cmp-reset",
            txn_type="fund",
            when=t0 + timedelta(minutes=1),
        ),
    )
    assert len(first["rules_fired"]) == 1

    # New qualifying txns AFTER the reset window origin.
    t1 = t0 + timedelta(hours=1)
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="100", when=t1),
            _txn(test_tenant, test_user, txn_type="send", amount="100", when=t1),
        ],
        with_points_accounts=False,
    )
    second = await _ingest(
        async_client,
        _event(
            tenant=test_tenant,
            user=test_user,
            source_key="cmp-reset",
            txn_type="fund",
            when=t1 + timedelta(minutes=1),
        ),
    )
    assert len(second["rules_fired"]) == 1
    assert await _reward_count(db_session, rule_id, test_user) == 2


@pytest.mark.asyncio
async def test_composite_no_reset_is_one_shot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """resets_after_trigger=False: fires once, never again while satisfied."""
    await _register_source(async_client, test_tenant, "cmp-noreset")
    rule_id = await _create_composite_rule(
        async_client,
        test_tenant,
        operator="AND",
        conditions=_TWO_CONDS,
        resets_after_trigger=False,
    )
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="100"),
            _txn(test_tenant, test_user, txn_type="send", amount="100"),
        ],
    )
    first = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-noreset", txn_type="fund"),
    )
    second = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-noreset", txn_type="fund"),
    )
    assert len(first["rules_fired"]) == 1
    assert second["rules_fired"] == []
    assert await _reward_count(db_session, rule_id, test_user) == 1


@pytest.mark.asyncio
async def test_composite_stop_after_n_triggers(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """stop_after_n_triggers=1: rule deactivates for the user after one fire."""
    await _register_source(async_client, test_tenant, "cmp-stop")
    rule_id = await _create_composite_rule(
        async_client,
        test_tenant,
        operator="OR",
        conditions=_TWO_CONDS,
        resets_after_trigger=True,
        stop_after_n_triggers=1,
    )
    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[_txn(test_tenant, test_user, txn_type="fund", amount="100", when=t0)],
    )
    first = await _ingest(
        async_client,
        _event(
            tenant=test_tenant,
            user=test_user,
            source_key="cmp-stop",
            txn_type="fund",
            when=t0 + timedelta(minutes=1),
        ),
    )
    # Even with fresh activity, the rule is completed for this user.
    t1 = t0 + timedelta(hours=1)
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[_txn(test_tenant, test_user, txn_type="fund", amount="100", when=t1)],
        with_points_accounts=False,
    )
    second = await _ingest(
        async_client,
        _event(
            tenant=test_tenant,
            user=test_user,
            source_key="cmp-stop",
            txn_type="fund",
            when=t1 + timedelta(minutes=1),
        ),
    )
    assert len(first["rules_fired"]) == 1
    assert second["rules_fired"] == []
    assert await _reward_count(db_session, rule_id, test_user) == 1


# -----------------------------------------------------------------------------
# Segment binding + bonus multiplier
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_segment_bound_skips_non_member(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """A segment-bound composite does not fire for a user outside the segment."""
    await _register_source(async_client, test_tenant, "cmp-seg")
    rule_id = await _create_composite_rule(
        async_client, test_tenant, operator="AND", conditions=_TWO_CONDS
    )
    # Bind the rule to a segment the user is NOT a member of, and seed the
    # accounts + satisfying transactions — all in one commit.
    segment = Segment(tenant_id=test_tenant.id, name=f"seg-{uuid4().hex[:6]}")
    db_session.add(segment)
    await db_session.flush()
    rule = (await db_session.execute(select(Rule).where(Rule.id == rule_id))).scalar_one()
    rule.segment_id = segment.id
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="100"),
            _txn(test_tenant, test_user, txn_type="send", amount="100"),
        ],
    )
    body = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-seg", txn_type="fund"),
    )
    assert body["rules_fired"] == []


@pytest.mark.asyncio
async def test_composite_bonus_multiplier_scales_payout(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """An active bonus multiplier scales the composite's issued reward_value."""
    await _register_source(async_client, test_tenant, "cmp-mult")
    rule_id = await _create_composite_rule(
        async_client,
        test_tenant,
        operator="AND",
        conditions=_TWO_CONDS,
        reward_value="100",
    )
    # Tenant-wide, rule-agnostic 2x multiplier active now + accounts + txns,
    # all in a single commit.
    now = datetime.now(UTC)
    db_session.add(
        BonusMultiplier(
            tenant_id=test_tenant.id,
            rule_id=None,
            segment_id=None,
            multiplier=Decimal("2.00"),
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=1),
        )
    )
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", amount="100"),
            _txn(test_tenant, test_user, txn_type="send", amount="100"),
        ],
    )
    body = await _ingest(
        async_client,
        _event(tenant=test_tenant, user=test_user, source_key="cmp-mult", txn_type="fund"),
    )
    assert len(body["rules_fired"]) == 1

    reward = (
        await db_session.execute(
            select(RewardEvent).where(
                RewardEvent.rule_id == rule_id, RewardEvent.user_id == test_user.id
            )
        )
    ).scalar_one()
    assert Decimal(str(reward.reward_value)) == Decimal("200.000000")
    assert Decimal(str(reward.multiplier_applied)) == Decimal("2.00")
