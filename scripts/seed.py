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

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.auth.secret_box import decrypt_secret, encrypt_secret  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.modules.payments.service import fund  # noqa: E402
from app.modules.redemption.schemas import ProviderRegistrationRequest  # noqa: E402
from app.modules.redemption.service import register_provider  # noqa: E402
from app.modules.treasury.service import BANK_MIRROR_PRIMARY_NAME  # noqa: E402
from app.shared.models import (  # noqa: E402
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ACCOUNT_TYPE_TAX_COMMISSION,
    ACCOUNT_TYPE_TAX_SERVICE,
    MERCHANT_CATEGORY_AIRTIME,
    MERCHANT_MODE_SIMULATOR,
    USER_TYPE_AGENT,
    USER_TYPE_MERCHANT,
    Account,
    ApiKey,
    CommissionConfig,
    ExternalEventSource,
    Instrument,
    LimitConfig,
    MerchantProfile,
    PricingConfig,
    RedemptionProvider,
    Role,
    RolePermission,
    Rule,
    Service,
    StepUpPolicy,
    TaxConfig,
    Tenant,
    Transaction,
    User,
    UserIdentifier,
    UserProfile,
    UserRole,
)

TENANT_NAME = "Sasai-ZA"
TENANT_CURRENCY = "ZAR"

# The merchant_cashin funding merchant (bound to the dev API key below).
CASHIN_MERCHANT_PHONE = "+27825557001"

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
    # An agent (user_type='agent') with a funded e-float (its financial_wallet),
    # so cash-in — an agent funding a customer's wallet for a commission — can be
    # exercised end-to-end from the mobile-simulator.
    {
        "phone": "+27825558001",
        "first_name": "Grace",
        "last_name": "Dube",
        "opening_balance_zar": Decimal("5000"),
        "user_type": USER_TYPE_AGENT,
    },
    # A funded MERCHANT (user_type='merchant') whose wallet is the funding
    # source for merchant_cashin. The dev API key is bound to this user so the
    # simulator's Partner-APIs panel can call the endpoint. Large opening
    # balance so many demo cash-ins can run before it runs dry.
    {
        "phone": CASHIN_MERCHANT_PHONE,
        "first_name": "Cash-in",
        "last_name": "Merchant",
        "opening_balance_zar": Decimal("100000"),
        "user_type": USER_TYPE_MERCHANT,
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

    # Provision the tenant's transaction-reference sequence so fresh dev DBs
    # match what the 0036 migration creates for existing tenants. Sequences are
    # not ORM-expressible — raw SQL is the sanctioned exception; only the
    # validated uuid-hex name is interpolated, never user input.
    await session.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "txn_ref_seq_{tenant.id.hex}"'))
    await session.commit()

    print(f"  + Created tenant: {tenant.name} ({tenant.id})")
    return tenant


async def _seed_instruments_catalog(session: AsyncSession, tenant: Tenant) -> None:
    """Idempotently insert the Phase-3 baseline instruments for the tenant.

    Mirrors the migration 0018 backfill so freshly-created tenants get the
    ZAR + PTS catalog entries existing tenants got at upgrade time.
    """
    baseline = [
        ("ZAR", "R", "South African Rand", "Fiat wallet currency.", "financial_wallet"),
        (
            "PTS",
            "Rewards",
            "Rewards Points",
            "Loyalty points credited by the rules engine.",
            "points_account",
        ),
    ]
    for code, symbol, display_name, description, account_type in baseline:
        result = await session.execute(
            select(Instrument).where(
                Instrument.tenant_id == tenant.id,
                Instrument.code == code,
                Instrument.deleted_at.is_(None),
            )
        )
        if result.scalar_one_or_none() is not None:
            continue
        session.add(
            Instrument(
                tenant_id=tenant.id,
                code=code,
                symbol=symbol,
                display_name=display_name,
                description=description,
                account_type=account_type,
            )
        )
        print(f"  + Instrument: {code} ({display_name})")
    await session.commit()


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
            "Recharge a mobile number via a registered airtime merchant.",
        ),
        (
            "redemption",
            "Redemption",
            "Redeem reward points with a registered redemption provider.",
        ),
        (
            "fund",
            "Fund",
            "Admin credits a user's wallet from the operator cash pool.",
        ),
        (
            "withdraw",
            "Withdraw",
            "Admin debits a user's wallet and returns funds to the operator cash pool.",
        ),
        (
            "cash_in",
            "Cash In",
            "An agent funds a customer's wallet from the agent's e-float and earns a commission.",
        ),
        (
            "cashout",
            "Cash Out",
            "A subscriber sends money to an agent; the agent earns a commission.",
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
    user_type: str | None = None,
) -> User:
    """Return the user identified by `phone` in this tenant, creating it on first run.

    `user_type` defaults to the model default (consumer) when None; pass e.g.
    `agent` to seed an agent that can cash-in.
    """
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
        user_result = await session.execute(select(User).where(User.id == identifier.user_id))
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

    user_kwargs = {"user_type": user_type} if user_type is not None else {}
    user = User(tenant_id=tenant.id, pin_hash=hash_pin("1234"), **user_kwargs)
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
    name: str | None = None,
) -> Account:
    """Idempotently create one account for a (tenant, user, type, currency) tuple.

    A `user=None` call creates a SYSTEM-owned account (one per tenant per type).

    Args:
        name: Persisted account name — used by bank mirrors (operator_adjustment)
            where several coexist per (tenant, currency) and are matched by name.
            NULL for every other account type.
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
    # Bank mirrors are keyed by name within (tenant, currency); scope the
    # idempotency lookup so re-seeding matches the right mirror.
    if name is not None:
        query = query.where(Account.name == name)

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
        name=name,
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


async def _get_or_create_standard_user_role(session: AsyncSession, tenant: Tenant) -> Role:
    """Idempotently create a 'standard_user' role granting p2p + fund + redemption.

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
            description=(
                "Default end-user role — grants p2p, fund, redemption, airtime_recharge."
            ),
        )
        session.add(role)
        await session.commit()
        await session.refresh(role)
        print(f"  + Created role: standard_user -> {role.id}")
    # Permissions are idempotent via the unique (role_id, transaction_type) index.
    # `cash_in` is granted here so seeded agents can fund customers; in
    # production a dedicated agent role would carry it (Pricing v2 Epic 21).
    for txn_type in ("p2p", "fund", "redemption", "airtime_recharge", "cash_in", "cashout"):
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
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
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
        select(ExternalEventSource).where(ExternalEventSource.source_key == source_key)
    )
    source = result.scalar_one_or_none()
    if source is not None:
        # Compare against the decrypted value so a re-run with the SAME secret
        # is a genuine no-op (ciphertext differs on every encrypt, so we can't
        # compare tokens directly).
        current = (
            decrypt_secret(source.shared_secret_encrypted)
            if source.shared_secret_encrypted
            else None
        )
        if shared_secret and current != shared_secret:
            # Idempotently rotate the secret if the seed re-runs with a
            # different value (e.g. operator regenerated their env).
            source.shared_secret_encrypted = encrypt_secret(shared_secret)
            await session.commit()
            await session.refresh(source)
            print(f"  ~ Rotated shared_secret on event source: {name} ({source_key})")
        return source
    source = ExternalEventSource(
        tenant_id=tenant.id,
        name=name,
        source_key=source_key,
        shared_secret_encrypted=(encrypt_secret(shared_secret) if shared_secret else None),
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


# Dev-only external partner API credential for the mobile-simulator's
# partner-API panel. Never a real secret; the real one is minted per tenant in
# production (api_keys service) and shown to the operator exactly once.
SIM_DEV_API_KEY_ID = "sim-dev-key"
SIM_DEV_API_KEY_SECRET = "dev-external-api-secret-do-not-use-in-prod"


async def _get_or_create_dev_api_key(
    session: AsyncSession, tenant: Tenant, *, merchant_user_id: str | None = None
) -> ApiKey:
    """Idempotently seed the mobile-simulator's dev external-API key.

    The secret is stored Fernet-encrypted via the same `encrypt_secret` path the
    api_keys service uses — never in the clear. Re-running the seed keeps the
    secret consistent (rotating the ciphertext to the canonical dev secret if a
    prior run stored a different one), mirroring the event-source seeding. The
    plaintext secret is a fixed dev constant printed so the simulator can sign
    against it; it is NEVER safe for production.

    When `merchant_user_id` is given, the key is bound to that merchant so the
    simulator can call `merchant-cashin`. fund/withdraw ignore the binding.

    Returns:
        The persisted (or existing) ApiKey row.
    """
    result = await session.execute(select(ApiKey).where(ApiKey.key_id == SIM_DEV_API_KEY_ID))
    api_key = result.scalar_one_or_none()
    if api_key is not None:
        changed = False
        # Rotate the stored ciphertext back to the canonical dev secret if a
        # prior run (or manual edit) diverged, so signing stays predictable.
        if decrypt_secret(api_key.secret_encrypted) != SIM_DEV_API_KEY_SECRET:
            api_key.secret_encrypted = encrypt_secret(SIM_DEV_API_KEY_SECRET)
            changed = True
            print(f"  ~ Rotated secret on dev API key: {SIM_DEV_API_KEY_ID}")
        # Backfill the merchant binding on an already-seeded key.
        if merchant_user_id is not None and str(api_key.merchant_user_id) != merchant_user_id:
            api_key.merchant_user_id = merchant_user_id  # type: ignore[assignment]
            changed = True
            print(f"  ~ Bound dev API key to cash-in merchant: {merchant_user_id}")
        if changed:
            await session.commit()
        return api_key
    api_key = ApiKey(
        tenant_id=tenant.id,
        key_id=SIM_DEV_API_KEY_ID,
        secret_encrypted=encrypt_secret(SIM_DEV_API_KEY_SECRET),
        label="Mobile simulator (dev only)",
        merchant_user_id=merchant_user_id,  # type: ignore[arg-type]
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    print(f"  + Created dev API key: {SIM_DEV_API_KEY_ID} (dev only — not for production)")
    if merchant_user_id is not None:
        print(f"    bound to cash-in merchant: {merchant_user_id}")
    return api_key


async def _get_or_create_merchant_cashin_charges(session: AsyncSession, tenant: Tenant) -> None:
    """Seed a zero-fee merchant_cashin pricing + limit config (invariant #12).

    The fail-closed gate resolves on the MERCHANT's user_type; a `user_type=NULL`
    default satisfies it for the seeded merchant. The zero fee is an EXPLICIT
    configured row (invariant #12 forbids a silent zero-fee fall-through), so
    merchant-cashin works out of the box. Idempotent.
    """
    exists = (
        await session.execute(
            select(PricingConfig).where(
                PricingConfig.tenant_id == tenant.id,
                PricingConfig.transaction_type == "merchant_cashin",
                PricingConfig.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                PricingConfig.currency == "ZAR",
                PricingConfig.user_type.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type="merchant_cashin",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                fixed_fee=Decimal("0"),  # explicit zero fee (not an implicit default)
            )
        )
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type="merchant_cashin",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                min_amount=Decimal("1"),
                max_amount=Decimal("50000"),
            )
        )
        await session.commit()
        print("  + Merchant cash-in charges: R0 fee, R1–R50000 limit (default)")


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


AIRTIME_MERCHANT_PHONE = "+27825559001"
# Dev-only HMAC secret for signing airtime provider callbacks in local testing.
# Never a real secret; the real one is minted per merchant in production.
AIRTIME_CALLBACK_SECRET = "dev-airtime-callback-secret-do-not-use-in-prod"


async def _get_or_create_airtime_merchant(session: AsyncSession, tenant: Tenant) -> User:
    """Idempotently create the default airtime merchant (Epic 17).

    Creates a `user_type='merchant'` user, its `merchant_profiles` row
    (associated with the seeded `airtime_recharge` service via `service_code`,
    simulator mode, dev callback secret), and its `airtime_merchant_holding`
    collection account. A user buying airtime credits this merchant's account.
    """
    result = await session.execute(
        select(UserIdentifier).where(
            UserIdentifier.tenant_id == tenant.id,
            UserIdentifier.identifier_type == "phone",
            UserIdentifier.identifier_value == AIRTIME_MERCHANT_PHONE,
        )
    )
    from app.auth.hashing import hash_pin

    identifier = result.scalar_one_or_none()
    if identifier is not None:
        merchant = (
            await session.execute(select(User).where(User.id == identifier.user_id))
        ).scalar_one()
        # Backfill a dev PIN so the simulator can log in as the merchant to show
        # (read-only) the transactions run against its holding account.
        if merchant.pin_hash is None:
            merchant.pin_hash = hash_pin("1234")
            await session.commit()
    else:
        merchant = User(
            tenant_id=tenant.id, user_type=USER_TYPE_MERCHANT, pin_hash=hash_pin("1234")
        )
        session.add(merchant)
        await session.flush()
        session.add(
            UserIdentifier(
                user_id=merchant.id,
                tenant_id=tenant.id,
                identifier_type="phone",
                identifier_value=AIRTIME_MERCHANT_PHONE,
                verified=True,
            )
        )
        session.add(
            UserProfile(user_id=merchant.id, first_name="Default Airtime", last_name="Merchant")
        )
        await session.commit()
        await session.refresh(merchant)
        print(f"  + Created airtime merchant user -> {merchant.id}")

    # Merchant profile (idempotent on user_id).
    profile = (
        await session.execute(select(MerchantProfile).where(MerchantProfile.user_id == merchant.id))
    ).scalar_one_or_none()
    if profile is None:
        session.add(
            MerchantProfile(
                tenant_id=tenant.id,
                user_id=merchant.id,
                business_name="Default Airtime Merchant",
                category=MERCHANT_CATEGORY_AIRTIME,
                service_code="airtime_recharge",
                mode=MERCHANT_MODE_SIMULATOR,
                callback_secret_encrypted=encrypt_secret(AIRTIME_CALLBACK_SECRET),
            )
        )
        await session.commit()
        print("  + Created merchant profile: Default Airtime Merchant (airtime_recharge/simulator)")
        print(
            f"    callback_secret={AIRTIME_CALLBACK_SECRET}  # dev only — sign callbacks with this"
        )

    # The merchant's collection/holding account (one per tenant/currency).
    await _get_or_create_account(
        session,
        tenant,
        user=merchant,
        account_type=ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
        currency="ZAR",
        label="Airtime merchant holding",
    )
    return merchant


async def _get_or_create_airtime_pricing_and_limits(session: AsyncSession, tenant: Tenant) -> None:
    """Demo airtime fee (R1 flat) + limits (R5-R1000), so the type-aware
    pricing/limits path is exercisable end-to-end. `user_type=NULL` = the
    default that applies to every user type unless a type-specific row overrides.
    """
    pricing = (
        await session.execute(
            select(PricingConfig).where(
                PricingConfig.tenant_id == tenant.id,
                PricingConfig.transaction_type == "airtime_recharge",
                PricingConfig.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                PricingConfig.currency == "ZAR",
                PricingConfig.user_type.is_(None),
            )
        )
    ).scalar_one_or_none()
    if pricing is None:
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type="airtime_recharge",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                fixed_fee=Decimal("1"),
            )
        )
        await session.commit()
        print("  + Pricing: airtime_recharge R1 flat fee (default)")

    limit = (
        await session.execute(
            select(LimitConfig).where(
                LimitConfig.tenant_id == tenant.id,
                LimitConfig.transaction_type == "airtime_recharge",
                LimitConfig.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                LimitConfig.currency == "ZAR",
                LimitConfig.user_type.is_(None),
            )
        )
    ).scalar_one_or_none()
    if limit is None:
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type="airtime_recharge",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                min_amount=Decimal("5"),
                max_amount=Decimal("1000"),
            )
        )
        await session.commit()
        print("  + Limits: airtime_recharge R5-R1000 (default)")


async def _get_or_create_cashin_charges(session: AsyncSession, tenant: Tenant) -> None:
    """Demo cash-in charges for agents so commission + tax are non-zero.

    Scoped to `user_type='agent'` (the acting party in a cash-in): a R2 fee, a
    R1.50 agent commission, and a 15% tax on both fee and commission. Without a
    commission config the commission would be 0, so this makes the fee /
    commission / tax breakdown visible in the mobile-simulator.
    """
    # Get-or-create each config INDEPENDENTLY. A single guard on the pricing row
    # is not enough: an operator may clear pricing/limits (via the UI) while the
    # commission row survives, and re-seeding would then hit the commission
    # unique index. `.limit(1).first()` also tolerates user-added bands.
    async def _has(model: type, *conds: object) -> bool:
        row = (
            await session.execute(select(model).where(*conds).limit(1))
        ).scalars().first()
        return row is not None

    added: list[str] = []
    if not await _has(
        PricingConfig,
        PricingConfig.tenant_id == tenant.id,
        PricingConfig.transaction_type == "cash_in",
        PricingConfig.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
        PricingConfig.currency == "ZAR",
        PricingConfig.user_type == USER_TYPE_AGENT,
    ):
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type="cash_in",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                user_type=USER_TYPE_AGENT,
                fixed_fee=Decimal("2"),
            )
        )
        added.append("R2 fee")
    if not await _has(
        LimitConfig,
        LimitConfig.tenant_id == tenant.id,
        LimitConfig.transaction_type == "cash_in",
        LimitConfig.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
        LimitConfig.currency == "ZAR",
        LimitConfig.user_type == USER_TYPE_AGENT,
    ):
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type="cash_in",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                user_type=USER_TYPE_AGENT,
                min_amount=Decimal("5"),
                max_amount=Decimal("5000"),
            )
        )
        added.append("R5–R5000 limit")
    if not await _has(
        CommissionConfig,
        CommissionConfig.tenant_id == tenant.id,
        CommissionConfig.transaction_type == "cash_in",
        CommissionConfig.currency == "ZAR",
        CommissionConfig.user_type == USER_TYPE_AGENT,
    ):
        session.add(
            CommissionConfig(
                tenant_id=tenant.id,
                transaction_type="cash_in",
                currency="ZAR",
                user_type=USER_TYPE_AGENT,
                fixed_commission=Decimal("1.50"),
            )
        )
        added.append("R1.50 commission")
    await session.commit()
    if added:
        print(f"  + Cash-in charges (agent): {', '.join(added)}")

    tax = (
        await session.execute(
            select(TaxConfig).where(
                TaxConfig.tenant_id == tenant.id, TaxConfig.currency == "ZAR"
            )
        )
    ).scalar_one_or_none()
    if tax is None:
        session.add(
            TaxConfig(
                tenant_id=tenant.id,
                currency="ZAR",
                fee_tax_pct=Decimal("0.15"),
                commission_tax_pct=Decimal("0.15"),
            )
        )
        await session.commit()
        print("  + Tax: 15% on fees + commissions (ZAR)")


async def _get_or_create_cashout_charges(session: AsyncSession, tenant: Tenant) -> None:
    """Fail-closed config so subscriber cash-out works out of the box (invariant #12).

    Cash-out is subscriber-initiated, so its pricing + limit configs are scoped
    to the acting SUBSCRIBER (left at the NULL-user_type default so any consumer
    resolves them). A zero fee is seeded EXPLICITLY — invariant #12 forbids a
    silent zero-fee fall-through, so the row must exist rather than being an
    implicit default. Idempotent. Commission/tax are optional and reuse the
    tenant's existing (cash-in-seeded) tax config.
    """
    exists = (
        await session.execute(
            select(PricingConfig).where(
                PricingConfig.tenant_id == tenant.id,
                PricingConfig.transaction_type == "cashout",
                PricingConfig.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                PricingConfig.currency == "ZAR",
                PricingConfig.user_type.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type="cashout",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                fixed_fee=Decimal("0"),  # explicit zero fee (not an implicit default)
            )
        )
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type="cashout",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                min_amount=Decimal("5"),
                max_amount=Decimal("5000"),
            )
        )
        await session.commit()
        print("  + Cash-out charges (subscriber): R0 fee, R5–R5000 limit")


async def seed() -> None:
    """Populate the local dev database with the canonical test data."""
    print("Seeding local development database...")
    print()

    async with SessionLocal() as session:
        tenant = await _get_or_create_tenant(session)

        # Instruments catalog — the dropdown source for currency fields
        # on Limits / Pricing. Idempotent.
        await _seed_instruments_catalog(session, tenant)

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

        # System-owned accounts for the tenant. We pre-create every system
        # wallet that platform activity would otherwise materialise lazily, so
        # a freshly-seeded tenant shows the full set on the System Wallets page
        # instead of a partial list that grows as transactions happen.
        #
        # provider_redemption_wallet is NOT created here — `register_provider()`
        # later in this script auto-creates it as part of registering the
        # sample provider (Pay-PRD-0730). Pre-0009 those two paths silently
        # created two wallets; the uq_accounts_system_scoped index now enforces
        # one. The airtime_merchant_holding account is merchant-owned and is
        # created by _get_or_create_airtime_merchant (Epic 17), not here.
        #
        # All financial system wallets use the tenant's base currency (ZAR);
        # the points pool uses PTS.
        system_wallets = [
            (ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE, "PTS", "System Points Issuance (master)"),
            (ACCOUNT_TYPE_SYSTEM_CASH_INFLOW, "ZAR", "Cash float"),
            (ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED, "ZAR", "Fees collected"),
            (ACCOUNT_TYPE_OPERATOR_ADJUSTMENT, "ZAR", "Bank mirror account"),
            (ACCOUNT_TYPE_COMMISSION, "ZAR", "Commission funded wallet"),
            (ACCOUNT_TYPE_TAX_SERVICE, "ZAR", "Tax collected on service charges"),
            (ACCOUNT_TYPE_TAX_COMMISSION, "ZAR", "Tax collected on commissions"),
        ]
        for account_type, currency, label in system_wallets:
            # The seeded bank mirror is the back-compat "Primary" mirror; every
            # other system wallet is unnamed.
            name = (
                BANK_MIRROR_PRIMARY_NAME
                if account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT
                else None
            )
            await _get_or_create_account(
                session,
                tenant,
                user=None,
                account_type=account_type,
                currency=currency,
                label=label,
                name=name,
            )

        # Users + their wallets + opening balances.
        for spec in USERS_TO_SEED:
            user = await _get_or_create_user(
                session,
                tenant,
                phone=spec["phone"],
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                user_type=spec.get("user_type"),
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
            # The fund service lazily creates the system_cash_inflow account.
            opening = spec["opening_balance_zar"]
            key = f"seed-opening-{spec['phone']}"
            existing = (
                await session.execute(
                    select(Transaction).where(
                        Transaction.tenant_id == tenant.id,
                        Transaction.idempotency_key == key,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                await fund(
                    session,
                    tenant_id=tenant.id,
                    user_id=user.id,
                    amount=opening,
                    currency="ZAR",
                    idempotency_key=key,
                )
                print(f"  + Fund: {spec['first_name']} <- R {opening} ZAR (opening balance)")

        # Phase D — sample redemption provider (auto-creates its wallet).
        await _get_or_create_redemption_provider(
            session,
            tenant,
            name="Mukuru Voucher (sample)",
        )

        # Epic 17 — default airtime merchant (user_type=merchant) + its holding
        # account + demo airtime pricing/limits, so the airtime vertical works
        # end-to-end straight after a seed.
        await _get_or_create_airtime_merchant(session, tenant)
        await _get_or_create_airtime_pricing_and_limits(session, tenant)

        # Cash-in charges so an agent cash-in shows a fee + commission + tax.
        await _get_or_create_cashin_charges(session, tenant)

        # Cash-out config so a subscriber cash-out works out of the box.
        await _get_or_create_cashout_charges(session, tenant)

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

        # Merchant cash-in config so merchant-cashin works out of the box.
        await _get_or_create_merchant_cashin_charges(session, tenant)

        # Resolve the funding merchant (seeded above) so the dev API key can be
        # bound to it — that binding is what authorises merchant-cashin.
        cashin_merchant_id = (
            await session.execute(
                select(UserIdentifier.user_id).where(
                    UserIdentifier.tenant_id == tenant.id,
                    UserIdentifier.identifier_type == "phone",
                    UserIdentifier.identifier_value == CASHIN_MERCHANT_PHONE,
                )
            )
        ).scalar_one()

        # Dev external-API key so the mobile-simulator's partner-API panel
        # (fund / withdraw / create-user / merchant-cashin) can authenticate
        # against a fresh DB. Bound to the cash-in merchant above.
        await _get_or_create_dev_api_key(
            session, tenant, merchant_user_id=str(cashin_merchant_id)
        )
        await _get_or_create_rule(
            session,
            tenant,
            name="First fund bonus",
            rule_type="first_time",
            transaction_type="fund",
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
