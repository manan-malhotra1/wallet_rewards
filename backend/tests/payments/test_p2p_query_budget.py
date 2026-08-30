"""Per-request query budget for the P2P money path.

A single transfer walks a long chain of gates — service resolution, role,
access policy, pricing, limits, step-up, then the ledger post — and each gate
historically re-read the same rows the previous one had already fetched.
Measured against the running stack, one transfer issued 48 statements, of which
roughly 20 were repeat reads (`users.user_type` alone ran 7 times).

These tests pin the repeats at their reduced count so the chain cannot silently
regrow. They assert on *repeat* reads rather than a single total, so adding a
genuinely new gate does not fail the suite for the wrong reason.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.service import fund, p2p_transfer
from app.shared.models import Tenant
from tests.conftest import test_engine
from tests.payments.test_p2p import _make_user_with_wallet, _seed_p2p_config


@contextlib.contextmanager
def capture_sql() -> Iterator[list[str]]:
    """Record every SQL statement the test engine executes inside the block."""
    seen: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _record)


def _count(statements: list[str], fragment: str) -> int:
    """How many captured statements contain `fragment`."""
    return sum(1 for s in statements if fragment in s)


async def _setup(session: AsyncSession, tenant: Tenant):
    """Seed p2p config, a funded sender and a recipient. Returns the sender."""
    await _seed_p2p_config(session, tenant.id)
    sender, _wallet = await _make_user_with_wallet(
        session, tenant, phone="+27820000101", with_points=True
    )
    await _make_user_with_wallet(session, tenant, phone="+27820000102")
    await fund(
        session,
        tenant_id=tenant.id,
        user_id=sender.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key="budget-fund-1",
    )
    return sender


async def _run_transfer(session: AsyncSession, tenant: Tenant, sender, key: str) -> list[str]:
    """Run one transfer, returning the SQL it issued."""
    with capture_sql() as statements:
        await p2p_transfer(
            session,
            tenant_id=tenant.id,
            sender_user_id=sender.id,
            recipient_identifier_type="phone",
            recipient_identifier_value="+27820000102",
            amount=Decimal("25"),
            currency="ZAR",
            idempotency_key=key,
        )
    return statements


async def _transfer(session: AsyncSession, tenant: Tenant) -> list[str]:
    """Run one full P2P transfer from a cold start, returning the SQL it issued."""
    sender = await _setup(session, tenant)
    return await _run_transfer(session, tenant, sender, "budget-p2p-1")


@pytest.mark.asyncio
async def test_transfer_resolves_the_sender_user_type_once(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify user_type is read once per request, not re-read by every gate

    Service resolution, permissions, pricing and each limit window all key off
    the sender's user_type. Re-reading it per gate also risks two gates seeing
    different types if an admin retypes the user mid-request.
    """
    statements = await _transfer(db_session, test_tenant)

    assert _count(statements, "SELECT users.user_type") <= 1, (
        "sender user_type should be resolved once and reused; got "
        f"{_count(statements, 'SELECT users.user_type')} reads"
    )


@pytest.mark.asyncio
async def test_transfer_reads_wallet_limit_config_once(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the daily/weekly/monthly windows share one config read"""
    statements = await _transfer(db_session, test_tenant)

    assert _count(statements, "FROM wallet_limit_configs") <= 1, (
        "the rolling windows should share one wallet_limit_configs read; got "
        f"{_count(statements, 'FROM wallet_limit_configs')}"
    )


@pytest.mark.asyncio
async def test_a_settled_account_needs_no_ledger_aggregate_to_read_its_balance(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a transfer between known accounts never scans ledger history

    A transfer derives three balances: the advisory overdraft check on the
    sender, the recipient's max_balance, and the authoritative re-check under the
    account write lock. Each used to aggregate the account's whole history — six
    statements per transfer, the authoritative one while holding the lock — so
    the cost grew forever on a shared account.

    The FIRST transfer against a brand-new account still aggregates once per
    account, to seed its snapshot; migration 0071 does that for every account
    that already exists, so in a live system this is the steady state, not the
    exception. Asserting on the second transfer is what models production.
    """
    sender = await _setup(db_session, test_tenant)
    await _run_transfer(db_session, test_tenant, sender, "budget-warm")

    statements = await _run_transfer(db_session, test_tenant, sender, "budget-measured")

    ledger_aggregates = [s for s in statements if "coalesce(sum(" in s and "ledger_entries" in s]
    assert ledger_aggregates == [], (
        "balance reads should hit the snapshot, not aggregate ledger_entries:\n"
        + "\n".join(ledger_aggregates)
    )
