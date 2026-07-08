"""create rules, rewards, and event-ingestion tables (PRD §6.8, §6.9, §6.11)

Phase C foundation tables:
  - rules, rule_conditions, user_rule_progress
  - reward_events
  - external_event_sources, event_ingestion_log

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- rules -------------------------------------------------------------
    op.create_table(
        "rules",
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
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rule_type", sa.String(length=30), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=True),
        sa.Column("count_threshold", sa.Integer(), nullable=True),
        sa.Column("streak_units", sa.Integer(), nullable=True),
        sa.Column("streak_unit_window", sa.String(length=20), nullable=True),
        sa.Column("min_amount", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("time_window", sa.String(length=30), nullable=True),
        sa.Column("reward_type", sa.String(length=20), nullable=False),
        sa.Column("reward_value", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("stop_after_n_triggers", sa.Integer(), nullable=True),
        sa.Column(
            "resets_after_trigger",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("campaign_start_date", sa.Date(), nullable=True),
        sa.Column("campaign_end_date", sa.Date(), nullable=True),
        sa.Column("composite_operator", sa.String(length=5), nullable=True),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "rule_type IN ("
            "'milestone', 'streak', 'first_time', 'value_based', "
            "'composite', 'campaign', 'referral'"
            ")",
            name="ck_rules_type",
        ),
        sa.CheckConstraint(
            "reward_type IN ('points', 'cashback')",
            name="ck_rules_reward_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_rules_status",
        ),
        sa.CheckConstraint(
            "time_window IS NULL OR time_window IN ('lifetime', 'calendar_month', 'rolling_7d')",
            name="ck_rules_time_window",
        ),
        sa.CheckConstraint(
            "composite_operator IS NULL OR composite_operator IN ('AND', 'OR')",
            name="ck_rules_composite_operator",
        ),
    )
    op.create_index("ix_rules_tenant_id", "rules", ["tenant_id"])

    # -- rule_conditions (composite sub-conditions; schema only Phase C) ---
    op.create_table(
        "rule_conditions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rules.id"),
            nullable=False,
        ),
        sa.Column("transaction_type", sa.String(length=50), nullable=False),
        sa.Column("count_threshold", sa.Integer(), nullable=False),
        sa.Column("min_amount", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index("ix_rule_conditions_rule_id", "rule_conditions", ["rule_id"])

    # -- user_rule_progress ------------------------------------------------
    op.create_table(
        "user_rule_progress",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rules.id"),
            nullable=False,
        ),
        sa.Column(
            "current_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "current_streak",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "trigger_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_triggered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "last_qualifying_event_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("window_start", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "rule_id", name="uq_user_rule_progress"),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'deactivated')",
            name="ck_user_rule_progress_status",
        ),
    )
    op.create_index("ix_user_rule_progress_user_id", "user_rule_progress", ["user_id"])

    # -- reward_events -----------------------------------------------------
    op.create_table(
        "reward_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rules.id"),
            nullable=False,
        ),
        sa.Column("triggering_event_id", sa.String(length=255), nullable=False),
        sa.Column("reward_type", sa.String(length=20), nullable=False),
        sa.Column("reward_value", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column(
            "multiplier_applied",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="1.00",
        ),
        sa.Column(
            "ledger_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_entries.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Idempotency guarantee — see PRD NFR-0110.
    op.create_index(
        "idx_reward_events_idempotency",
        "reward_events",
        ["user_id", "rule_id", "triggering_event_id"],
        unique=True,
    )

    # -- external_event_sources --------------------------------------------
    op.create_table(
        "external_event_sources",
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
            "source_key",
            sa.String(length=100),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "field_mapping",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("shared_secret", sa.Text(), nullable=True),
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
            name="ck_external_event_sources_status",
        ),
    )
    op.create_index(
        "ix_external_event_sources_tenant_id",
        "external_event_sources",
        ["tenant_id"],
    )

    # -- event_ingestion_log -----------------------------------------------
    op.create_table(
        "event_ingestion_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("source_key", sa.String(length=100), nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source_key",
            "external_event_id",
            name="uq_event_ingestion_log_dedup",
        ),
        sa.CheckConstraint(
            "status IN ('PROCESSED', 'DUPLICATE', 'FAILED', 'REJECTED')",
            name="ck_event_ingestion_log_status",
        ),
    )
    op.create_index(
        "idx_event_ingestion_log_dedup_lookup",
        "event_ingestion_log",
        ["source_key", "external_event_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_event_ingestion_log_dedup_lookup", table_name="event_ingestion_log")
    op.drop_table("event_ingestion_log")

    op.drop_index(
        "ix_external_event_sources_tenant_id",
        table_name="external_event_sources",
    )
    op.drop_table("external_event_sources")

    op.drop_index("idx_reward_events_idempotency", table_name="reward_events")
    op.drop_table("reward_events")

    op.drop_index("ix_user_rule_progress_user_id", table_name="user_rule_progress")
    op.drop_table("user_rule_progress")

    op.drop_index("ix_rule_conditions_rule_id", table_name="rule_conditions")
    op.drop_table("rule_conditions")

    op.drop_index("ix_rules_tenant_id", table_name="rules")
    op.drop_table("rules")
