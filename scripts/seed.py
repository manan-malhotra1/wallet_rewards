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
from typing import NotRequired, TypedDict  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.auth.principals import AdminPrincipal  # noqa: E402
from app.auth.secret_box import decrypt_secret, encrypt_secret  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.modules.accounts.service import derive_balance  # noqa: E402
from app.modules.payments.service import fund  # noqa: E402
from app.modules.redemption.schemas import ProviderRegistrationRequest  # noqa: E402
from app.modules.redemption.service import register_provider  # noqa: E402
from app.modules.step_up.schemas import STEP_UP_TRANSACTION_TYPES  # noqa: E402
from app.modules.tenants.service import provision_tenant_defaults  # noqa: E402
from app.modules.treasury.service import (  # noqa: E402
    BANK_MIRROR_PRIMARY_NAME,
    adjust_system_wallet,
)
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
    LimitConfig,
    MerchantProfile,
    PricingConfig,
    RedemptionProvider,
    Role,
    RolePermission,
    Rule,
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

# Default per-tenant brand anchors for the seeded tenant. These two colours seed
# the admin UI's derived theme palette; the logo URL is left null so the UI falls
# back to its default mark. Applied only when the tenant has no brand set yet —
# a tenant with a custom brand is never overwritten (see _get_or_create_tenant).
DEFAULT_BRAND_ACCENT_COLOR = "#243B8F"  # Blueberry
DEFAULT_BRAND_LIGHT_COLOR = "#FFF0C9"  # Cream Soda

# The merchant_cashin funding merchant (bound to the dev API key below).
CASHIN_MERCHANT_PHONE = "+27825557001"

class UserSeedSpec(TypedDict):
    """One seeded end-user. `user_type` omitted = the model default (consumer)."""

    phone: str
    first_name: str
    last_name: str
    opening_balance_zar: Decimal
    user_type: NotRequired[str]


USERS_TO_SEED: list[UserSeedSpec] = [
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
    # An agent (user_type='agent') with a HEALTHY funded e-float (its
    # financial_wallet), so cash-in — an agent funding a customer's wallet for a
    # commission — can be exercised repeatedly end-to-end from the mobile app /
    # simulator without the float running dry. The large opening is topped up on
    # already-seeded DBs by _topup_agent_efloat (see the users loop below).
    {
        "phone": "+27825558001",
        "first_name": "Grace",
        "last_name": "Dube",
        "opening_balance_zar": Decimal("500000"),
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
        # Backfill the default brand for a pre-existing tenant that predates the
        # branding fields, but NEVER overwrite a tenant that already carries a
        # custom brand. Only fill in colours that are still null; the logo URL
        # stays as-is (default is null anyway). Keeps re-runs idempotent.
        if tenant.brand_accent_color is None:
            tenant.brand_accent_color = DEFAULT_BRAND_ACCENT_COLOR
        if tenant.brand_light_color is None:
            tenant.brand_light_color = DEFAULT_BRAND_LIGHT_COLOR
        await session.commit()
        return tenant

    tenant = Tenant(
        name=TENANT_NAME,
        business_type="both",
        base_currency=TENANT_CURRENCY,
        brand_accent_color=DEFAULT_BRAND_ACCENT_COLOR,
        brand_light_color=DEFAULT_BRAND_LIGHT_COLOR,
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
    # Get-or-create pricing and limit INDEPENDENTLY, each with `.limit(1).first()`
    # (not `scalar_one_or_none()`): an operator may clear one via the UI while the
    # other survives, or the DB may already hold duplicate rows — `scalar_one_or_none`
    # raises MultipleResultsFound on those and aborts the whole seed. Mirrors
    # `_get_or_create_cashin_charges`.
    async def _has(model: type, *conds: object) -> bool:
        row = (await session.execute(select(model).where(*conds).limit(1))).scalars().first()
        return row is not None

    added: list[str] = []
    if not await _has(
        PricingConfig,
        PricingConfig.tenant_id == tenant.id,
        PricingConfig.transaction_type == "merchant_cashin",
        PricingConfig.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
        PricingConfig.currency == "ZAR",
        PricingConfig.user_type.is_(None),
    ):
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type="merchant_cashin",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                fixed_fee=Decimal("0"),  # explicit zero fee (not an implicit default)
            )
        )
        added.append("R0 fee")
    if not await _has(
        LimitConfig,
        LimitConfig.tenant_id == tenant.id,
        LimitConfig.transaction_type == "merchant_cashin",
        LimitConfig.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
        LimitConfig.currency == "ZAR",
        LimitConfig.user_type.is_(None),
    ):
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
        added.append("R1-R50000 limit")
    if added:
        await session.commit()
        print(f"  + Merchant cash-in charges: {', '.join(added)} (default)")


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
        added.append("R5-R5000 limit")
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
        print("  + Cash-out charges (subscriber): R0 fee, R5-R5000 limit")


async def _get_or_create_change_pin_charges(session: AsyncSession, tenant: Tenant) -> None:
    """Fail-closed config so change-PIN works out of the box (invariant #12).

    Change-PIN is a charged self-service operation, so it needs BOTH a pricing
    AND a limit config to resolve for the acting user or the gate rejects it.
    A zero fee is seeded EXPLICITLY (invariant #12 forbids a silent zero-fee
    fall-through). The limit config is left cap-free — its only job is to satisfy
    the fail-closed gate; change-PIN has no principal to bound, and the resolved
    FEE (zero here) is what `check_limits` measures. Both rows are at the
    NULL-user_type default so any user type resolves them. Idempotent.
    """
    exists = (
        await session.execute(
            select(PricingConfig).where(
                PricingConfig.tenant_id == tenant.id,
                PricingConfig.transaction_type == "change_pin",
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
                transaction_type="change_pin",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                fixed_fee=Decimal("0"),  # explicit zero fee (not an implicit default)
            )
        )
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type="change_pin",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                # No caps — an explicitly-configured limitless row that satisfies
                # the fail-closed gate without bounding the (zero) fee.
            )
        )
        await session.commit()
        print("  + Change-PIN charges: R0 fee, limitless (gate-only) limit")


# System principal used as the audit actor for seed-time treasury operations.
_SEED_ADMIN = AdminPrincipal(id="seed-script", username="seed", roles=frozenset())


async def _prefund_operator_float(session: AsyncSession, tenant: Tenant) -> None:
    """Top the operator cash float up from the bank mirror before any user fund.

    The cash float (`system_cash_inflow`) carries a no-overdraft floor at the
    ledger choke point (invariant #11): every seeded user fund DEBITs it, so it
    must first hold at least the sum of all opening balances. We inject that sum
    plus generous headroom (airtime / demo funding) via `adjust_system_wallet`
    (DEBIT operator_adjustment / CREDIT float). Idempotent: a deterministic
    idempotency_key means a re-seed never double-injects. Requires the ZAR float
    and the "Primary" bank mirror to already exist (seeded just above).
    """
    total_openings = Decimal("0")
    for spec in USERS_TO_SEED:
        total_openings += Decimal(str(spec["opening_balance_zar"]))
    amount = total_openings + Decimal("1000000")  # headroom for other seeded funding

    float_account = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
                Account.currency == "ZAR",
                Account.user_id.is_(None),
            )
        )
    ).scalar_one()
    mirror = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.currency == "ZAR",
                Account.user_id.is_(None),
                Account.name == BANK_MIRROR_PRIMARY_NAME,
            )
        )
    ).scalar_one()

    key = "seed-float-topup"
    existing = (
        await session.execute(
            select(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    await adjust_system_wallet(
        session,
        tenant_id=tenant.id,
        account_id=float_account.id,
        amount=amount,
        bank_mirror_account_id=mirror.id,
        reason="Seed: pre-fund operator cash float from the bank.",
        admin=_SEED_ADMIN,
        idempotency_key=key,
    )
    print(f"  + Float top-up: R {amount} ZAR injected from bank mirror")


async def _topup_agent_efloat(
    session: AsyncSession,
    tenant: Tenant,
    user: User,
    account: Account,
    *,
    phone: str,
    target: Decimal,
) -> None:
    """Ensure an agent's e-float (financial_wallet) holds at least `target` ZAR.

    On a FRESH DB the opening-balance fund already lands the agent at `target`,
    so this is a no-op. On an ALREADY-seeded DB whose agent was funded at an
    older (smaller) opening balance, that opening fund's idempotency key is
    already spent — a plain re-seed can never raise the balance — so this tops
    up the shortfall through the same `fund` path.

    Guarded two ways so re-runs never double-fund: a distinct idempotency key
    (checked first, mirroring the opening-balance guard) AND a delta check that
    skips when the agent already holds >= target.

    Args:
        account: The agent's ZAR financial_wallet (its e-float).
        phone: Used only to build the deterministic idempotency key.
        target: Desired e-float balance in ZAR.

    Side effects:
        Appends ledger entries via `fund` (DEBITs the operator cash float).
    """
    key = f"seed-agent-efloat-{phone}"
    existing = (
        await session.execute(
            select(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    balance, _ = await derive_balance(session, account.id)
    delta = target - balance
    if delta <= 0:  # fresh DB already funded to target via the opening balance
        return

    await fund(
        session,
        tenant_id=tenant.id,
        user_id=user.id,
        amount=delta,
        currency="ZAR",
        idempotency_key=key,
    )
    print(f"  + Agent e-float top-up: {user.id} +R {delta} ZAR (-> R {target} target)")


async def seed() -> None:
    """Populate the local dev database with the canonical test data."""
    print("Seeding local development database...")
    print()

    async with SessionLocal() as session:
        tenant = await _get_or_create_tenant(session)

        # Baseline instruments + services — the ONE provisioning path, shared
        # with the POST /api/v1/tenants create-tenant endpoint. Idempotent.
        # The fiat instrument's code is the tenant's OWN base_currency (ZAR
        # here for the seeded tenant); PTS is always added.
        await provision_tenant_defaults(session, tenant)

        # Default end-user role so seeded users can actually transact.
        standard_role = await _get_or_create_standard_user_role(session, tenant)

        # Step-up PIN policies — make the prompt path discoverable in dev.
        # enforce_step_up is FAIL-CLOSED: a guarded money path with NO policy
        # requires a PIN for any amount, so we seed an EXPLICIT policy for EVERY
        # guarded transaction type ("explicit config, never implicit" — invariant
        # #12). Iterating STEP_UP_TRANSACTION_TYPES (the schema's own set) means
        # the seed can NEVER provision a policy the config schema would reject —
        # add a type there and it's seeded here automatically. Currency + default
        # threshold are derived from the type (redemption is points, rest fiat).
        for _txn_type in STEP_UP_TRANSACTION_TYPES:
            _is_points = _txn_type == "redemption"
            await _get_or_create_step_up_policy(
                session,
                tenant,
                transaction_type=_txn_type,
                currency="PTS" if _is_points else "ZAR",
                threshold_amount=Decimal("500") if _is_points else Decimal("200"),
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

        # Pre-fund the operator cash float from the bank BEFORE any user fund.
        # The float (`system_cash_inflow`) now carries a no-overdraft floor at the
        # ledger choke point (invariant #11): every user fund below DEBITs it, so
        # it must be topped up first or the first fund would 409 `insufficient_float`.
        await _prefund_operator_float(session, tenant)

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
            wallet_account = await _get_or_create_account(
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

            # Agents need a HEALTHY e-float so cash-in runs repeatedly. On an
            # already-seeded DB the opening fund above is a spent idempotency key,
            # so top up the shortfall to the spec's target (no-op on fresh DBs).
            if spec.get("user_type") == USER_TYPE_AGENT:
                await _topup_agent_efloat(
                    session,
                    tenant,
                    user,
                    wallet_account,
                    phone=spec["phone"],
                    target=opening,
                )

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
        await _get_or_create_change_pin_charges(session, tenant)

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
