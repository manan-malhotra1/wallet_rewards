"""User-type catalog — categories and types (configurable user types, 2026-08-23).

Replaces the five hardcoded constants in `users.py`. Modelled on the services
catalog: `code` is the persistent identifier that `users.user_type` and every
config table store as a plain string, with NO foreign key. That loose coupling
is deliberate — it keeps the money-path config lookups matching on strings
exactly as before — and it is why types are retired, never deleted (spec §11).

Categories are fixed and system-seeded. Retail and Business carry a two-level
type hierarchy; Consumers is flat. Depth is capped by one rule enforced in the
service: a type named as a parent must itself have a NULL `parent_type_code`.
"""

import uuid
from typing import Final

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# `Final` (with no explicit annotation) narrows these to their literal types, so
# they can be used as defaults for a `Literal["active", "retired"]` field without
# widening it back to `str`. The status set is closed — `ck_user_types_status`
# says so at the database — and the schema layer relies on that.
USER_TYPE_STATUS_ACTIVE: Final = "active"
USER_TYPE_STATUS_RETIRED: Final = "retired"

CATEGORY_CONSUMER = "consumer"
CATEGORY_RETAIL = "retail"
CATEGORY_BUSINESS = "business"


class UserTypeCategory(Base):
    """A fixed super-group of user types — Consumers, Retail or Business.

    No *config* resolves against a category (spec D1) — pricing, limits and
    commissions all key off the type `code`. Capability does: Retail means
    "can take a cash-out" (`cashout/service.py`) and Business means "can carry a
    merchant-bound API key" (`api_keys/service.py`). That is what the three
    categories mean, so a tenant's own type inherits the capability from the
    category it was filed under rather than from a separate flag.

    `supports_hierarchy` is false for Consumers, so every type in that category
    must have a NULL parent.
    """

    __tablename__ = "user_type_categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    supports_hierarchy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at = created_at_col()


class UserTypeDef(Base):
    """One user type, either platform-wide (system) or tenant-scoped.

    Named `UserTypeDef` rather than `UserType` because `UserType` is already a
    Pydantic Literal alias in `identity/schemas.py`.

    `tenant_id IS NULL` marks a system type: visible to every tenant and
    immutable. A tenant-created type is visible only to that tenant.

    `parent_type_code` alone expresses the hierarchy tier — NULL means a
    top-level type, set means a child hanging under that parent. There is no
    separate tier column because it would be derivable from this one and
    therefore able to disagree with it.
    """

    __tablename__ = "user_types"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{USER_TYPE_STATUS_ACTIVE}', '{USER_TYPE_STATUS_RETIRED}')",
            name="ck_user_types_status",
        ),
        CheckConstraint(
            "parent_type_code IS NULL OR parent_type_code <> code",
            name="ck_user_types_no_self_parent",
        ),
        Index(
            "uq_user_types_system_code",
            "code",
            unique=True,
            postgresql_where=mapped_column("tenant_id").is_(None),
        ),
        Index(
            "uq_user_types_tenant_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=mapped_column("tenant_id").isnot(None),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # NULL = system type, visible to every tenant.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    # String(20), not 30: this value is copied verbatim into `users.user_type`
    # and into the `user_type` column of every config table, all String(20). A
    # wider column here would let a 21-character code be created and then fail
    # as a raw DataError the first time it was assigned to a user.
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    category_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("user_type_categories.code"), nullable=False, index=True
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=USER_TYPE_STATUS_ACTIVE
    )
    # Holds another row's `code`, so it matches `code`'s width exactly.
    parent_type_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at = created_at_col()
    updated_at = updated_at_col()
