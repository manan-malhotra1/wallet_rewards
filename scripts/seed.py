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
    Role,
    RolePermission,
    Rule,
    Service,
    StepUpPolicy,
    Tenant,
    Transaction,
    User,
    UserIdentifier,
    UserProfile,
    UserRole,
)

TENANT_NAME = "Sasai-ZA"
TENANT_CURRENCY = "ZAR"

USERS_TO_SEED = [
    {
        "phone": "+27825550001",
        "first_name": "Alice",
        "last_name": "Mokoena",
        "opening_balance_zar": Decimal("1000"),
    },
    {
        "phone": "+27825550002",
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
        business_type="both",
        base_currency=TENANT_CURRENCY,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    print(f"  + Created tenant: {tenant.name} ({tenant.id})")
    return tenant


async def _seed_services_catalog(session: AsyncSession, tenant: Tenant) -> None:
    """Idempotently insert the Phase-2 baseline services for the tenant.

    Mirrors the migration 0017 backfill so freshly-created tenants get the
    same catalog entries existing tenants got at upgrade time.
    """
    baseline = [
        ("p2p", "Peer-to-Peer", "Send funds from one wallet to another."),
        (
            "airtime_recharge",
            "Airtime Recharge",
            "Top up a mobile number via a registered airtime merchant.",
        ),
        (
            "redemption",
            "Redemption",
            "Redeem reward points with a registered redemption provider.",
        ),
    ]
    for code, display_name, description in baseline:
        result = await session.execute(
            select(Service).where(
                Service.tenant_id == tenant.id,
                Service.code == code,
                Service.deleted_at.is_(None),
            )
        )
        if result.scalar_one_or_none() is not None:
            continue
        session.add(
            Service(
                tenant_id=tenant.id,
                code=code,
                display_name=display_name,
                description=description,
            )
        )
        print(f"  + Service: {code} ({display_name})")
    await session.commit()


async def _get_or_create_user(
    session: AsyncSession,
    tenant: Tenant,
    phone: str,
    first_name: str,
    last_name: str,
) -> User:
    """Return the user identified by `phone` in this tenant, creating it on first run."""
    from app.auth.hashing import hash_pin

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
        existing = user_result.scalar_one()
        # Backfill dev PIN on already-seeded users so the mobile-simulator
        # can log in against old DBs without a full reset.
        if existing.pin_hash is None:
            existing.pin_hash = hash_pin("1234")
            await session.commit()
            print(f"    ~ Backfilled dev PIN on existing user: {phone}")
        return existing

    # Seeded users get a deterministic dev PIN ("1234") so the
    # mobile-simulator can silently authenticate without an OTP +
    # set-PIN dance every time the DB resets. The PIN is bcrypt-hashed
    # via the same helper the real flow uses.
    from app.auth.hashing import hash_pin

    user = User(tenant_id=tenant.id, pin_hash=hash_pin("1234"))
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


async def _get_or_create_standard_user_role(
    session: AsyncSession, tenant: Tenant
) -> Role:
    """Idempotently create a 'standard_user' role granting p2p + top_up + redemption.

    Without this, the seeded users can't initiate any transaction — the
    payments orchestrator's role check (Pay-PRD-0260 step 1) rejects.
    """
    result = await session.execute(
        select(Role).where(Role.tenant_id == tenant.id, Role.name == "standard_user")
    )
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(
            tenant_id=tenant.id,
            name="standard_user",
            description="Default end-user role — grants p2p, top_up, redemption.",
        )
        session.add(role)
        await session.commit()
        await session.refresh(role)
        print(f"  + Created role: standard_user -> {role.id}")
    # Permissions are idempotent via the unique (role_id, transaction_type) index.
    for txn_type in ("p2p", "top_up", "redemption"):
        exists = (
            await session.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.transaction_type == txn_type,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(RolePermission(role_id=role.id, transaction_type=txn_type))
    await session.commit()
    return role


async def _get_or_create_step_up_policy(
    session: AsyncSession,
    tenant: Tenant,
    *,
    transaction_type: str,
    currency: str,
    threshold_amount: Decimal,
) -> StepUpPolicy:
    """Idempotently create a step-up policy. Surfaces the PIN flow in dev."""
    existing = (
        await session.execute(
            select(StepUpPolicy).where(
                StepUpPolicy.tenant_id == tenant.id,
                StepUpPolicy.transaction_type == transaction_type,
                StepUpPolicy.currency == currency,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    policy = StepUpPolicy(
        tenant_id=tenant.id,
        transaction_type=transaction_type,
        currency=currency,
        threshold_amount=threshold_amount,
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    print(
        f"  + Created step-up policy: {transaction_type} > "
        f"{threshold_amount} {currency} → PIN required"
    )
    return policy


async def _assign_role(session: AsyncSession, user: User, role: Role) -> None:
    """Idempotently link the user to the role."""
    existing = (
        await session.execute(
            select(UserRole).where(
                UserRole.user_id == user.id, UserRole.role_id == role.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()


async def _get_or_create_event_source(
    session: AsyncSession,
    tenant: Tenant,
    *,
    name: str,
    source_key: str,
    shared_secret: str | None = None,
) -> ExternalEventSource:
    """Idempotently register a sample external event source.

    When `shared_secret` is provided, it's set on the row so HMAC-aware
    callers (e.g. the mobile-simulator) can sign requests against it.
    The secret is printed once on creation so the operator can copy it
    into the simulator's `.env.local`.
    """
    result = await session.execute(
        select(ExternalEventSource).where(
            ExternalEventSource.source_key == source_key
        )
    )
    source = result.scalar_one_or_none()
    if source is not None:
        if shared_secret and source.shared_secret != shared_secret:
            # Idempotently rotate the secret if the seed re-runs with a
            # different value (e.g. operator regenerated their env).
            source.shared_secret = shared_secret
            await session.commit()
            await session.refresh(source)
            print(
                f"  ~ Rotated shared_secret on event source: {name} ({source_key})"
            )
        return source
    source = ExternalEventSource(
        tenant_id=tenant.id,
        name=name,
        source_key=source_key,
        shared_secret=shared_secret,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    print(f"  + Created event source: {name} ({source_key}) -> {source.id}")
    if shared_secret:
        print(
            f"    shared_secret={shared_secret}  "
            "# copy into mobile-simulator/.env.local as EVENT_SOURCE_SECRET"
        )
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

        # Services catalog — the dropdown source for Limits / Pricing /
        # Campaigns admin pages. Idempotent.
        await _seed_services_catalog(session, tenant)

        # Default end-user role so seeded users can actually transact.
        standard_role = await _get_or_create_standard_user_role(session, tenant)

        # Step-up PIN policies — make the prompt path discoverable in dev.
        await _get_or_create_step_up_policy(
            session,
            tenant,
            transaction_type="p2p",
            currency="ZAR",
            threshold_amount=Decimal("200"),
        )
        await _get_or_create_step_up_policy(
            session,
            tenant,
            transaction_type="redemption",
            currency="PTS",
            threshold_amount=Decimal("500"),
        )

        # System-owned accounts for the tenant. We create the master
        # system_points_issuance account explicitly; provider_redemption_wallet
        # is NOT created here — `register_provider()` later in this script
        # auto-creates it as part of registering the sample provider
        # (Pay-PRD-0730). Pre-0009 those two paths silently created two
        # wallets; the uq_accounts_system_scoped index now enforces one.
        await _get_or_create_account(
            session,
            tenant,
            user=None,
            account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            currency="PTS",
            label="System Points Issuance (master)",
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
            await _assign_role(session, user, standard_role)
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

        # Phase C — sample external source + reward rules. The shared
        # secret is deterministic in dev so the mobile-simulator's env
        # file doesn't have to be updated after every re-seed.
        await _get_or_create_event_source(
            session,
            tenant,
            name="Sasai Bank Receipts (sample)",
            source_key="sasai-bank",
            shared_secret="dev-simulator-secret-do-not-use-in-prod",
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
