"""ReferralCode and Referral models — Epic 10 / WAL-77 (Pay-PRD-0622).

Referral attribution is by code at signup: every user gets a unique referral
code (`referral_codes`), and a new user may supply a referrer's code at
create-time, which creates a `referrals` row linking referred -> referrer.
The referral rule type then rewards one or both sides.

A referral is genuine only when a code was supplied — organic signup writes no
`referrals` row and fires no reward.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Referral lifecycle — keep in sync with the CHECK constraint below.
REFERRAL_STATUS_PENDING = "pending"
REFERRAL_STATUS_REWARDED = "rewarded"
REFERRAL_STATUS_VOID = "void"

REFERRAL_STATUSES = (
    REFERRAL_STATUS_PENDING,
    REFERRAL_STATUS_REWARDED,
    REFERRAL_STATUS_VOID,
)

# Referral rule trigger — when the reward fires (Pay-PRD-0622).
REFERRAL_TRIGGER_SIGNUP = "signup"
REFERRAL_TRIGGER_NTH_TRANSACTION = "nth_transaction"

REFERRAL_TRIGGERS = (
    REFERRAL_TRIGGER_SIGNUP,
    REFERRAL_TRIGGER_NTH_TRANSACTION,
)


class ReferralCode(Base):
    """A user's own unique referral code — one per user, per tenant.

    A new user may quote this code at signup to attribute themselves to the
    owning user (the referrer). The code is short and human-shareable; it is
    unique within the tenant.
    """

    __tablename__ = "referral_codes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_referral_codes_code_per_tenant"),
        UniqueConstraint("tenant_id", "user_id", name="uq_referral_codes_user_per_tenant"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Referral(Base):
    """A single referred -> referrer link, created when a code is quoted at signup.

    A user is referred at most once (unique on `referred_user_id`). The
    `referrer_rewarded_at` / `referee_rewarded_at` stamps record which side has
    already been paid so re-evaluation never double-pays; the `reward_events`
    unique index is the structural backstop (NFR-0110).
    """

    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "referred_user_id", name="uq_referrals_referred_per_tenant"),
        CheckConstraint(
            "status IN ('pending', 'rewarded', 'void')",
            name="ck_referrals_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    referred_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    referrer_rewarded_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    referee_rewarded_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
