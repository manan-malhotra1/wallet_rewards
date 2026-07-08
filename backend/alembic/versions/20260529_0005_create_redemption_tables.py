"""create redemption_providers and redemptions tables (PRD §6.10)

Phase D foundation. Includes a FK from redemption_providers to the provider's
provider_redemption_wallet account (not in PRD's literal schema but the
natural relationship — see Phase D threat model §1).

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- redemption_providers ---------------------------------------------
    op.create_table(
        "redemption_providers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "redemption_wallet_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("status_check_url", sa.String(length=500), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "retry_interval_secs",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
        sa.Column(
            "escalate_after_mins",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_redemption_providers_status",
        ),
    )
    op.create_index(
        "ix_redemption_providers_tenant_id",
        "redemption_providers",
        ["tenant_id"],
    )

    # -- redemptions -------------------------------------------------------
    op.create_table(
        "redemptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("redemption_providers.id"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column("points_amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ("
            "'PENDING', 'PROCESSING', 'COMPLETED', "
            "'FAILED', 'REVERSED', 'MANUAL_REVIEW'"
            ")",
            name="ck_redemptions_status",
        ),
    )
    op.create_index("ix_redemptions_tenant_id", "redemptions", ["tenant_id"])
    op.create_index("ix_redemptions_user_id", "redemptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_redemptions_user_id", table_name="redemptions")
    op.drop_index("ix_redemptions_tenant_id", table_name="redemptions")
    op.drop_table("redemptions")

    op.drop_index("ix_redemption_providers_tenant_id", table_name="redemption_providers")
    op.drop_table("redemption_providers")
