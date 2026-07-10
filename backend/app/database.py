"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# isolation_level is pinned to READ COMMITTED (PostgreSQL's default) on purpose:
# the money-path `SELECT ... FOR UPDATE` locks depend on it. Under REPEATABLE READ
# or SERIALIZABLE a locked-but-never-UPDATEd account row would not force a fresh
# balance read, silently reopening the double-spend race (Epic 18 H-01). Pinning it
# here means a future global isolation change can't quietly break that guarantee.
engine = create_async_engine(
    settings.DATABASE_URL, echo=False, future=True, isolation_level="READ COMMITTED"
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Yields an async session, rolls back on exception."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
