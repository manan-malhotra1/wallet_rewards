"""SQLAlchemy Base + common column conventions.

Every domain model uses `uuid_pk()`, `created_at_col()`, `updated_at_col()` to
guarantee project-wide consistency: UUID PKs, TIMESTAMPTZ everywhere.
"""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project-wide declarative base."""


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


def created_at_col() -> Mapped[datetime]:
    return mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
