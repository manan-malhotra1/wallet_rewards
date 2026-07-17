"""Pytest fixtures for backend tests.

Runs against a separate `wallet_platform_test` database. Each test starts
with a TRUNCATE-cleaned schema (fast and reliable) and commits normally.

The FastAPI `get_async_session` dependency is overridden to use the test
database engine. Test fixtures and endpoint requests use separate sessions
both pointing at the same test DB — so a fixture-committed row is visible
to the endpoint and vice versa.

Why not use SAVEPOINT-based rollback: asyncpg only allows one operation
per connection at a time. Sharing a session between a fixture and an
endpoint coroutine triggers `another operation in progress`. The
TRUNCATE-between-tests pattern avoids that entirely.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jose import jwt as jose_jwt
from jose.utils import long_to_base64
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.auth.keycloak import keycloak_client

# Stable test key id — used by every signed test JWT.
TEST_KID = "test-key-1"

from app.config import settings
from app.database import get_async_session
from app.main import app
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Base,
    Role,
    RolePermission,
    Tenant,
    User,
    UserIdentifier,
    UserRole,
)

# -----------------------------------------------------------------------------
# Engine + schema lifecycle
# -----------------------------------------------------------------------------

TEST_DATABASE_URL = settings.DATABASE_URL.replace("/wallet_platform", "/wallet_platform_test")

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    future=True,
    # NullPool: every operation gets a brand-new asyncpg connection. Avoids
    # "another operation in progress" errors caused by pool-recycled
    # connections shared across coroutines / event loops in pytest-asyncio.
    poolclass=NullPool,
)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_schema() -> AsyncIterator[None]:
    """Create the schema once per test session, drop at the end."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()


async def _truncate_all_tables() -> None:
    """Wipe every domain table before a test.

    Uses TRUNCATE ... CASCADE so foreign keys don't block. Order doesn't
    matter because CASCADE handles dependents, but we exclude the Alembic
    version table to keep the schema metadata intact.
    """
    async with test_engine.begin() as conn:
        table_names = [t.name for t in Base.metadata.sorted_tables if t.name != "alembic_version"]
        if table_names:
            joined = ", ".join(f'"{name}"' for name in table_names)
            await conn.execute(text(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE"))


# -----------------------------------------------------------------------------
# Per-test sessions
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Per-test session. Cleans the schema BEFORE yielding.

    Test code that uses this session may commit freely — cleanup happens at
    the START of the next test, not at the end of this one. This keeps the
    teardown path simple and reliable.
    """
    await _truncate_all_tables()
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """httpx AsyncClient bound to the FastAPI app, using the test database.

    Each request gets a fresh session via the dep override; this avoids
    asyncpg's `another operation in progress` error caused by sharing a
    single session across coroutines.
    """

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_async_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# Domain fixtures
#
# All fixtures COMMIT after seeding so endpoint sessions can see them.
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_tenant(db_session: AsyncSession) -> Tenant:
    """A fresh tenant with full business-type (wallet + rewards) in ZAR per test."""
    tenant = Tenant(
        name=f"test-tenant-{uuid4().hex[:8]}",
        business_type="both",
        base_currency="ZAR",
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def other_tenant(db_session: AsyncSession) -> Tenant:
    """A second tenant used to verify cross-tenant isolation."""
    tenant = Tenant(
        name=f"other-tenant-{uuid4().hex[:8]}",
        business_type="both",
        base_currency="USD",
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role) -> User:
    """A simple active user with one phone identifier + default role.

    The default role grants p2p + redemption + fund — exercises Phase F.3
    role check without each test having to wire it manually.
    """
    user = User(tenant_id=test_tenant.id)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value=f"+27 82 555 {uuid4().int % 10000:04d}",
            verified=True,
        )
    )
    db_session.add(UserRole(user_id=user.id, role_id=default_user_role.id))
    await db_session.commit()
    await db_session.refresh(user, attribute_names=["identifiers"])
    return user


@pytest_asyncio.fixture
async def default_user_role(db_session: AsyncSession, test_tenant: Tenant) -> Role:
    """Per-tenant default role granting common user transaction types.

    Phase F.3 requires every user to hold an active role permitting a
    transaction_type before initiating it (Pay-PRD-0440 / 0450). Without
    this fixture every P2P / redemption test would 403.
    """
    role = Role(
        tenant_id=test_tenant.id,
        name="standard_user",
        description="Default test role — grants p2p, redemption, fund.",
    )
    db_session.add(role)
    await db_session.flush()
    for txn_type in ("p2p", "redemption", "fund", "airtime_recharge"):
        db_session.add(
            RolePermission(
                role_id=role.id,
                transaction_type=txn_type,
                permitted=True,
            )
        )
    await db_session.commit()
    await db_session.refresh(role)
    return role


@pytest_asyncio.fixture
async def default_user_role_other_tenant(db_session: AsyncSession, other_tenant: Tenant) -> Role:
    """Default role for `other_tenant` — same shape as default_user_role."""
    role = Role(
        tenant_id=other_tenant.id,
        name="standard_user",
        description="Default test role for the other tenant.",
    )
    db_session.add(role)
    await db_session.flush()
    for txn_type in ("p2p", "redemption", "fund", "airtime_recharge"):
        db_session.add(
            RolePermission(
                role_id=role.id,
                transaction_type=txn_type,
                permitted=True,
            )
        )
    await db_session.commit()
    await db_session.refresh(role)
    return role


@pytest_asyncio.fixture
async def system_points_account(db_session: AsyncSession, test_tenant: Tenant) -> Account:
    """The tenant's master system_points_issuance account.

    All reward issuance debits this account.
    """
    account = Account(
        tenant_id=test_tenant.id,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="PTS",
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest_asyncio.fixture
async def user_wallet(db_session: AsyncSession, test_tenant: Tenant, test_user: User) -> Account:
    """A ZAR financial wallet for the test_user."""
    account = Account(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest_asyncio.fixture
async def user_points(db_session: AsyncSession, test_tenant: Tenant, test_user: User) -> Account:
    """A points account for the test_user."""
    account = Account(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        account_type=ACCOUNT_TYPE_POINTS,
        currency="PTS",
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


# -----------------------------------------------------------------------------
# Auth fixtures (Phase F.1) — in-process RSA keypair + JWT factory
# -----------------------------------------------------------------------------
# We generate one RSA keypair per session, seed the global keycloak_client
# cache with the matching JWK, and block any real JWKS HTTP fetch. Tests then
# sign JWTs with the private key and send them through the real verifier.


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    """One RSA-2048 keypair per session (generation is ~200ms; do it once)."""
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    return private_key, private_key.public_key()


@pytest.fixture(scope="session")
def private_key_pem(rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]) -> bytes:
    """PEM-encoded private key for signing test JWTs."""
    private_key, _ = rsa_keypair
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture(scope="session")
def test_jwks(rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]) -> dict:
    """JWKS document derived from the test public key."""
    _, public_key = rsa_keypair
    public_numbers = public_key.public_numbers()
    return {
        "keys": [
            {
                "kid": TEST_KID,
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "n": long_to_base64(public_numbers.n).decode("utf-8"),
                "e": long_to_base64(public_numbers.e).decode("utf-8"),
            }
        ]
    }


@pytest.fixture(autouse=True)
def seed_keycloak_jwks(monkeypatch: pytest.MonkeyPatch, test_jwks: dict) -> None:
    """Autouse: prime the verifier's JWKS cache, block any real HTTP fetch.

    The `_refetch` patch keeps the seeded cache stable even when
    `verify_jwt` decides to refetch on unknown-kid — important so the
    "unknown kid → 401" test doesn't accidentally hit the real Keycloak
    running on localhost:8080.
    """
    keycloak_client._seed_cache_for_tests(test_jwks)

    async def _no_real_refetch() -> None:
        keycloak_client._seed_cache_for_tests(test_jwks)

    monkeypatch.setattr(keycloak_client, "_refetch", _no_real_refetch)


@pytest.fixture
def make_admin_token(private_key_pem: bytes) -> Callable[..., str]:
    """Factory for signed Keycloak-shaped admin JWTs.

    Override defaults to test specific failure modes (expired, wrong issuer,
    wrong kid, missing roles).
    """
    from app.config import settings

    def _build(
        roles: list[str] | None = None,
        sub: str = "00000000-0000-4000-8000-000000000001",
        username: str = "admin-test",
        exp_seconds: int = 900,
        iss_override: str | None = None,
        alg: str = "RS256",
        kid: str | None = TEST_KID,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        issuer = (
            iss_override
            if iss_override is not None
            else f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
        )
        claims: dict[str, Any] = {
            "iss": issuer,
            "sub": sub,
            "preferred_username": username,
            "iat": now,
            "exp": now + exp_seconds,
            "realm_access": {"roles": roles or []},
            "typ": "Bearer",
        }
        if extra_claims:
            claims.update(extra_claims)
        headers = {"kid": kid} if kid is not None else {}
        return jose_jwt.encode(claims, private_key_pem, algorithm=alg, headers=headers)

    return _build


@pytest.fixture
def admin_token(make_admin_token: Callable[..., str]) -> str:
    """A ready-to-use platform-admin token."""
    return make_admin_token(roles=["platform-admin"])


@pytest.fixture
def admin_auth_header(admin_token: str) -> dict[str, str]:
    """Authorization header dict ready for httpx requests."""
    return {"Authorization": f"Bearer {admin_token}"}


# -----------------------------------------------------------------------------
# Per-test Redis client (Phase F.2)
# -----------------------------------------------------------------------------
# OTP rate-limits, lockouts, sessions, and registration_tokens live in Redis.
# The redis-py async client is bound to an event loop at construction time.
# pytest-asyncio uses a fresh loop per test, so we MUST also recreate the
# Redis client per test — otherwise the second test hits
# `RuntimeError: Event loop is closed`.
#
# This fixture monkey-patches the `redis_client` name in every module that
# imported it so all production code paths use the per-test client. It also
# flushes the DB so lockout / rate-limit state doesn't leak between tests.


@pytest_asyncio.fixture(autouse=True)
async def _redis_per_test(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Fresh Redis client per test, flushed at start."""
    import redis.asyncio as redis_lib

    from app import redis_client as redis_module
    from app.auth import lockout as lockout_module
    from app.auth import rate_limit as rate_limit_module
    from app.auth import sessions as sessions_module

    client = redis_lib.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    await client.flushdb()

    # Patch every importer. Without this, the modules still reference the
    # ORIGINAL singleton that was bound to a now-closed loop.
    monkeypatch.setattr(redis_module, "redis_client", client)
    monkeypatch.setattr(sessions_module, "redis_client", client)
    monkeypatch.setattr(lockout_module, "redis_client", client)
    monkeypatch.setattr(rate_limit_module, "redis_client", client)

    try:
        yield
    finally:
        await client.aclose()


# -----------------------------------------------------------------------------
# User session fixtures (Phase F.4)
# -----------------------------------------------------------------------------
# Phase F.2 issues session tokens via /auth/pin. For other test modules, we
# need a quick way to fabricate a session token for an existing user without
# running the full OTP+PIN dance. This helper bypasses the auth flow and
# directly creates a session in Redis — fine for tests that aren't exercising
# the auth flow itself.


async def seed_redemption_service_config(session: AsyncSession, tenant: Tenant) -> None:
    """Seed a zero-fee pricing + wide limit config for redemption (points scope).

    Redemption is gated by the fail-closed service gate (invariant #12): a
    redemption may run only when BOTH a pricing and a limit config resolve for
    the redeeming user's type. Tests that initiate a redemption as SETUP (not to
    exercise the gate itself) call this so the `/initiate` succeeds. Scoped to
    the points_account / PTS with `user_type=NULL` so the default covers every
    user type. Idempotent-safe per test (each test starts with a truncated DB).
    """
    from decimal import Decimal

    from app.shared.models import ACCOUNT_TYPE_POINTS, LimitConfig, PricingConfig

    session.add(
        PricingConfig(
            tenant_id=tenant.id,
            transaction_type="redemption",
            account_type=ACCOUNT_TYPE_POINTS,
            currency="PTS",
            fixed_fee=Decimal("0"),
        )
    )
    session.add(
        LimitConfig(
            tenant_id=tenant.id,
            transaction_type="redemption",
            account_type=ACCOUNT_TYPE_POINTS,
            currency="PTS",
            min_amount=Decimal("1"),
            max_amount=Decimal("1000000"),
        )
    )
    await session.commit()


async def create_session_token_for_user(user_id, tenant_id, channel: str = "mobile") -> str:
    """Test helper — directly create a Redis-backed session for a user.

    Used by P2P / redemption / catalog tests that need to act AS a user
    without running the F.2 OTP+PIN flow per test. Returns the opaque token
    suitable for `Authorization: Bearer <token>`.
    """
    from app.auth.sessions import create_session

    return await create_session(user_id, tenant_id, channel)


@pytest_asyncio.fixture
async def alice_session_token(test_user) -> str:
    """A session token for the default test_user (auto-assigned standard_user role)."""
    return await create_session_token_for_user(test_user.id, test_user.tenant_id)


@pytest_asyncio.fixture
async def alice_auth_header(alice_session_token: str) -> dict[str, str]:
    """Authorization header dict bound to test_user's session."""
    return {"Authorization": f"Bearer {alice_session_token}"}
