#!/usr/bin/env python3
"""Seed local dev database with a tenant, 2 users, and all required accounts.

Idempotent — safe to re-run. Creates:

  Tenant         : Sasai-ZA (wallet mode, ZAR)
  Users          : Alice (+27 82 555 0001) and Bob (+27 82 555 0002)
                   Each user gets 1 financial_wallet (ZAR) + 1 points_account (PTS)
  System accounts: 1 system_points_issuance (PTS) — the master reward source
                   1 provider_redemption_wallet (PTS) — sample redemption partner

The system_points_issuance account is the DEBIT side of every reward issuance.
Per docs/06-data-architecture.md addendum, its balance trends negative as more
points are issued — that negative number equals total points outstanding.

Usage:
    cd backend && source .venv/bin/activate
    python ../scripts/seed.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running this script from anywhere — add backend/ to sys.path so
# `import app` works.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from decimal import Decimal  # noqa: E402

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.modules.payments.service import top_up  # noqa: E402
from app.modules.redemption.schemas import ProviderRegistrationRequest  # noqa: E402
from app.modules.redemption.service import register_provider  # noqa: E402
from app.shared.models import (  # noqa: E402
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_PROVIDER_REDEMPTION,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    ExternalEventSource,
    RedemptionProvider,
    Rule,
    Tenant,
    Transaction,
    User,
    UserIdentifier,
    UserProfile,
)

TENANT_NAME = "Sasai-ZA"
TENANT_CURRENCY = "ZAR"

USERS_TO_SEED = [
    {
        "phone": "+27 82 555 0001",
        "first_name": "Alice",
        "last_name": "Mokoena",
        "opening_balance_zar": Decimal("1000"),
    },
    {
        "phone": "+27 82 555 0002",
        "first_name": "Bob",
        "last_name": "Nkomo",
        "opening_balance_zar": Decimal("500"),
    },
]


async def _get_or_create_tenant(session: AsyncSession) -> Tenant:
    """Return the Sasai-ZA tenant, creating it on first run."""
    result = await session.execute(select(Tenant).where(Tenant.name == TENANT_NAME))
    tenant = result.scalar_one_or_none()
    if tenant is not None:
        return tenant

    tenant = Tenant(
        name=TENANT_NAME,
        deployment_mode="wallet",
        base_currency=TENANT_CURRENCY,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    print(f"  + Created tenant: {tenant.name} ({tenant.id})")
    return tenant


async def _get_or_create_user(
    session: AsyncSession,
    tenant: Tenant,
    phone: str,
    first_name: str,
    last_name: str,
) -> User:
    """Return the user identified by `phone` in this tenant, creating it on first run."""
    result = await session.execute(
        select(UserIdentifier).where(
            UserIdentifier.tenant_id == tenant.id,
            UserIdentifier.identifier_type == "phone",
            UserIdentifier.identifier_value == phone,
        )
    )
    identifier = result.scalar_one_or_none()
    if identifier is not None:
        user_result = await session.execute(
            select(User).where(User.id == identifier.user_id)
        )
        return user_result.scalar_one()

    user = User(tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=tenant.id,
            identifier_type="phone",
            identifier_value=phone,
            verified=True,
        )
    )
    session.add(
        UserProfile(
            user_id=user.id,
            first_name=first_name,
            last_name=last_name,
        )
    )
    await session.commit()
    await session.refresh(user)
    print(f"  + Created user: {first_name} {last_name} ({phone}) -> {user.id}")
    return user


async def _get_or_create_account(
    session: AsyncSession,
    tenant: Tenant,
    *,
    user: User | None,
    account_type: str,
    currency: str,
    label: str,
) -> Account:
    """Idempotently create one account for a (tenant, user, type, currency) tuple.

    A `user=None` call creates a SYSTEM-owned account (one per tenant per type).
    """
    query = select(Account).where(
        Account.tenant_id == tenant.id,
        Account.account_type == account_type,
        Account.currency == currency,
    )
    if user is not None:
        query = query.where(Account.user_id == user.id)
    else:
        query = query.where(Account.user_id.is_(None))

    # Use `.first()` (not `scalar_one_or_none()`) so an already-duplicated DB
    # state doesn't crash the seed. Older builds had no unique constraint
    # on (tenant_id, user_id, account_type, currency), so prior runs could
    # silently create duplicates. Picking the first row keeps the seed
    # idempotent on legacy DBs; the new UniqueConstraint (migration 0009)
    # prevents drift going forward.
    result = await session.execute(query.order_by(Account.created_at.asc()))
    account = result.scalars().first()
    if account is not None:
        return account

    account = Account(
        tenant_id=tenant.id,
        user_id=user.id if user is not None else None,
        account_type=account_type,
        currency=currency,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    print(f"  + Created account: {label} ({account_type}/{currency}) -> {account.id}")
    return account


async def _get_or_create_redemption_provider(
    session: AsyncSession, tenant: Tenant, *, name: str
) -> RedemptionProvider:
    """Idempotently register a sample redemption provider.

    Re-uses the existing row if one with the same (tenant, name) exists.
    Otherwise calls the service which auto-creates the wallet.
    """
    result = await session.execute(
        select(RedemptionProvider).where(
            RedemptionProvider.tenant_id == tenant.id,
            RedemptionProvider.name == name,
        )
    )
    provider = result.scalar_one_or_none()
    if provider is not None:
        return provider
    provider = await register_provider(
        session,
        ProviderRegistrationRequest(tenant_id=tenant.id, name=name),
    )
    print(
        f"  + Created redemption provider: {name} -> {provider.id} "
        f"(wallet: {provider.redemption_wallet_account_id})"
    )
    return provider


async def _get_or_create_event_source(
    session: AsyncSession,
    tenant: Tenant,
    *,
    name: str,
    source_key: str,
) -> ExternalEventSource:
    """Idempotently register a sample external event source."""
    result = await session.execute(
        select(ExternalEventSource).where(
            ExternalEventSource.source_key == source_key
        )
    )
    source = result.scalar_one_or_none()
    if source is not None:
        return source
    source = ExternalEventSource(
        tenant_id=tenant.id,
        name=name,
        source_key=source_key,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    print(f"  + Created event source: {name} ({source_key}) -> {source.id}")
    return source


async def _get_or_create_rule(
    session: AsyncSession,
    tenant: Tenant,
    *,
    name: str,
    rule_type: str,
    transaction_type: str,
    reward_value: Decimal,
    count_threshold: int | None = None,
) -> Rule:
    """Idempotently create a reward rule (matched by tenant + name)."""
    result = await session.execute(
        select(Rule).where(Rule.tenant_id == tenant.id, Rule.name == name)
    )
    rule = result.scalar_one_or_none()
    if rule is not None:
        return rule
    rule = Rule(
        tenant_id=tenant.id,
        name=name,
        rule_type=rule_type,
        transaction_type=transaction_type,
        reward_type="points",
        reward_value=reward_value,
        count_threshold=count_threshold,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    extras = f", threshold={count_threshold}" if count_threshold else ""
    print(
        f"  + Created rule: {name} ({rule_type}/{transaction_type}{extras}, "
        f"reward={reward_value} pts) -> {rule.id}"
    )
    return rule


async def seed() -> None:
    """Populate the local dev database with the canonical test data."""
    print("Seeding local development database...")
    print()

    async with SessionLocal() as session:
        tenant = await _get_or_create_tenant(session)

        # System-owned accounts for the tenant.
        await _get_or_create_account(
            session,
            tenant,
            user=None,
            account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            currency="PTS",
            label="System Points Issuance (master)",
        )
        await _get_or_create_account(
            session,
            tenant,
            user=None,
            account_type=ACCOUNT_TYPE_PROVIDER_REDEMPTION,
            currency="PTS",
            label="Provider Redemption Wallet (sample)",
        )

        # Users + their wallets + opening balances.
        for spec in USERS_TO_SEED:
            user = await _get_or_create_user(
                session,
                tenant,
                phone=spec["phone"],
                first_name=spec["first_name"],
                last_name=spec["last_name"],
            )
            await _get_or_create_account(
                session,
                tenant,
                user=user,
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                label=f"{spec['first_name']} wallet",
            )
            await _get_or_create_account(
                session,
                tenant,
                user=user,
                account_type=ACCOUNT_TYPE_POINTS,
                currency="PTS",
                label=f"{spec['first_name']} points",
            )

            # Opening balance — idempotent via per-user idempotency_key.
            # The top_up service lazily creates the system_cash_inflow account.
            opening = spec["opening_balance_zar"]
            key = f"seed-opening-{spec['phone']}"
            existing = (await session.execute(
                select(Transaction).where(
                    Transaction.tenant_id == tenant.id,
                    Transaction.idempotency_key == key,
                )
            )).scalar_one_or_none()
            if existing is None:
                await top_up(
                    session,
                    tenant_id=tenant.id,
                    user_id=user.id,
                    amount=opening,
                    currency="ZAR",
                    idempotency_key=key,
                )
                print(
                    f"  + Top-up: {spec['first_name']} <- R {opening} ZAR (opening balance)"
                )

        # Phase D — sample redemption provider (auto-creates its wallet).
        await _get_or_create_redemption_provider(
            session,
            tenant,
            name="Mukuru Voucher (sample)",
        )

        # Phase C — sample external source + reward rules.
        await _get_or_create_event_source(
            session,
            tenant,
            name="Sasai Bank Receipts (sample)",
            source_key="sasai-bank",
        )
        await _get_or_create_rule(
            session,
            tenant,
            name="First top-up bonus",
            rule_type="first_time",
            transaction_type="top_up",
            reward_value=Decimal("100"),
        )
        await _get_or_create_rule(
            session,
            tenant,
            name="3 P2P milestone",
            rule_type="milestone",
            transaction_type="p2p",
            reward_value=Decimal("50"),
            count_threshold=3,
        )

    print()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
