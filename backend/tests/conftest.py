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

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings
from app.database import get_async_session
from app.main import app
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Base,
    Tenant,
    User,
    UserIdentifier,
)

# -----------------------------------------------------------------------------
# Engine + schema lifecycle
# -----------------------------------------------------------------------------

TEST_DATABASE_URL = settings.DATABASE_URL.replace(
    "/wallet_platform", "/wallet_platform_test"
)

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    future=True,
    # NullPool: every operation gets a brand-new asyncpg connection. Avoids
    # "another operation in progress" errors caused by pool-recycled
    # connections shared across coroutines / event loops in pytest-asyncio.
    poolclass=NullPool,
)
TestSessionLocal = async_sessionmaker(
    test_engine, expire_on_commit=False, class_=AsyncSession
)


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
        table_names = [
            t.name for t in Base.metadata.sorted_tables if t.name != "alembic_version"
        ]
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
    """A fresh wallet-mode tenant in ZAR per test."""
    tenant = Tenant(
        name=f"test-tenant-{uuid4().hex[:8]}",
        deployment_mode="wallet",
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
        deployment_mode="wallet",
        base_currency="USD",
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """A simple active user with one phone identifier."""
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
    await db_session.commit()
    await db_session.refresh(user, attribute_names=["identifiers"])
    return user


@pytest_asyncio.fixture
async def system_points_account(
    db_session: AsyncSession, test_tenant: Tenant
) -> Account:
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
async def user_wallet(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> Account:
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
async def user_points(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> Account:
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
