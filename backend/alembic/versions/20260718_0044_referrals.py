"""create referral_codes + referrals, add referral config columns to rules

Epic 10 / WAL-77 (Pay-PRD-0622). `referral_codes` holds each user's unique,
shareable code; `referrals` links a referred user to their referrer when a code
is quoted at signup. Three nullable columns on `rules` carry the referral rule's
trigger config (referral_trigger, referral_trigger_n) and the optional referee
reward amount (referee_reward_value).

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the two referral tables and add the rules referral columns."""
    op.create_table(
        "referral_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_referral_codes_code_per_tenant"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_referral_codes_user_per_tenant"),
    )
    op.create_index("ix_referral_codes_tenant_id", "referral_codes", ["tenant_id"], unique=False)

    op.create_table(
        "referrals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("referrer_user_id", sa.UUID(), nullable=False),
        sa.Column("referred_user_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("referrer_rewarded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("referee_rewarded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('pending', 'rewarded', 'void')", name="ck_referrals_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "referred_user_id", name="uq_referrals_referred_per_tenant"
        ),
    )
    op.create_index("ix_referrals_tenant_id", "referrals", ["tenant_id"], unique=False)
    op.create_index(
        "ix_referrals_referrer_user_id", "referrals", ["referrer_user_id"], unique=False
    )
    op.create_index(
        "ix_referrals_referred_user_id", "referrals", ["referred_user_id"], unique=False
    )

    # Referral rule config columns on `rules`.
    op.add_column("rules", sa.Column("referral_trigger", sa.String(length=20), nullable=True))
    op.add_column("rules", sa.Column("referral_trigger_n", sa.Integer(), nullable=True))
    op.add_column(
        "rules",
        sa.Column("referee_reward_value", sa.Numeric(precision=20, scale=6), nullable=True),
    )
    op.create_check_constraint(
        "ck_rules_referral_trigger",
        "rules",
        "referral_trigger IS NULL OR referral_trigger IN ('signup', 'nth_transaction')",
    )


def downgrade() -> None:
    """Drop the referral columns and both referral tables."""
    op.drop_constraint("ck_rules_referral_trigger", "rules", type_="check")
    op.drop_column("rules", "referee_reward_value")
    op.drop_column("rules", "referral_trigger_n")
    op.drop_column("rules", "referral_trigger")

    op.drop_index("ix_referrals_referred_user_id", table_name="referrals")
    op.drop_index("ix_referrals_referrer_user_id", table_name="referrals")
    op.drop_index("ix_referrals_tenant_id", table_name="referrals")
    op.drop_table("referrals")

    op.drop_index("ix_referral_codes_tenant_id", table_name="referral_codes")
    op.drop_table("referral_codes")
