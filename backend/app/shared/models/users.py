"""User, UserIdentifier, UserProfile models — PRD §6.2.

OtpRequest and AuthAttempt are scaffolded but not used in Phase A (full
authentication flow is deferred to Phase 2). They are defined here so the
schema is created once and we don't need a separate migration later.

PRD references:
  - Pay-PRD-0010 to 0100 (Identity & User Management module)
  - NFR-0170, NFR-0240 (credentials/PII handling — never logged)
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class User(Base):
    """A natural person registered on the platform.

    A user is scoped to a tenant. The same person can exist as separate users
    across tenants (Phase 1 does not link cross-tenant identities — see PRD §6.16).

    The `pin_hash` field is bcrypt; the plain PIN is never stored or logged
    (NFR-0170). In Phase A this field is unused — full PIN flow lands in Phase 2.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'closed')",
            name="ck_users_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    # bcrypt hash; never the plain PIN. NULL until user sets PIN (Phase 2).
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    identifiers: Mapped[list["UserIdentifier"]] = relationship(
        back_populates="user", cascade="all"
    )
    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all"
    )


class UserIdentifier(Base):
    """Any external identifier that maps to a canonical user_id.

    Multiple identifier types per user are allowed (phone, email, account, card)
    but each `(tenant_id, identifier_type, identifier_value)` tuple is unique
    (Pay-PRD-0070).
    """

    __tablename__ = "user_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "identifier_type",
            "identifier_value",
            name="uq_user_identifiers_value_per_tenant",
        ),
        CheckConstraint(
            "identifier_type IN ('phone', 'email', 'account_number', 'card_number')",
            name="ck_user_identifiers_type",
        ),
        Index(
            "ix_user_identifiers_lookup",
            "tenant_id",
            "identifier_type",
            "identifier_value",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    identifier_type: Mapped[str] = mapped_column(String(30), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(255), nullable=False)
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = created_at_col()

    user: Mapped[User] = relationship(back_populates="identifiers")


class UserProfile(Base):
    """Per-user profile data (PII).

    Separate from `users` so that the high-traffic users table stays narrow
    and so that profile-level PII can be masked/redacted independently.
    """

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "kyc_status IN ('unverified', 'pending', 'verified', 'rejected')",
            name="ck_user_profiles_kyc_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_of_birth: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    kyc_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="unverified"
    )
    updated_at: Mapped[datetime] = updated_at_col()

    user: Mapped[User] = relationship(back_populates="profile")


class OtpRequest(Base):
    """One-time password requests (Phase 2 — scaffolded only in Phase A).

    Stored as bcrypt hash, never plaintext (NFR-0170). Single-use; `used_at`
    is set after successful verification.
    """

    __tablename__ = "otp_requests"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('registration', 'pin_reset', 'login')",
            name="ck_otp_requests_purpose",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    otp_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()


class AuthAttempt(Base):
    """Audit trail of PIN and OTP attempts (Phase 2 — scaffolded only in Phase A).

    Used to enforce lockout (NFR-0190) and forensic review.
    """

    __tablename__ = "auth_attempts"
    __table_args__ = (
        CheckConstraint(
            "attempt_type IN ('pin', 'otp')",
            name="ck_auth_attempts_type",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    attempt_type: Mapped[str] = mapped_column(String(20), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
