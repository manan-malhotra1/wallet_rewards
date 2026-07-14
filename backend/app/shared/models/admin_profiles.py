"""AdminProfile — a display-name cache for Keycloak-authenticated admins.

Admins live in Keycloak, not the platform DB; requests only ever carry the
Keycloak `sub` (a UUID string). To render human names in admin surfaces (e.g.
the config-request maker/checker screen) WITHOUT exposing bare IDs, we record a
row here whenever an admin performs an auditable action, keyed by `sub`.

Not tenant-scoped: Keycloak realm admins are cross-tenant operators, so this
table intentionally has no `tenant_id` (it is infra identity, not domain data).
"""

import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class AdminProfile(Base):
    """The last-seen display identity for one Keycloak admin (`sub`)."""

    __tablename__ = "admin_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Keycloak `sub` — the stable admin identifier every JWT carries.
    keycloak_sub: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # `name` claim if present, else the username — what the UI shows.
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
