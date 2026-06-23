"""Create the instruments catalog table and widen currency columns to VARCHAR(10).

Phase 3 of the Tenant Management refactor. Brings two changes:

  1. New `instruments` table — per-tenant catalog of value units. ZAR
     (symbol "R") and PTS (symbol "Rewards") are the Phase-1 baseline;
     tenants can add more (10-char codes) via the admin UI.

  2. Widens every currency column from CHAR(3) to VARCHAR(10) so 4+
     character codes (USDC, AIRTIME, etc.) are storable. The columns
     touched are:

       accounts.currency
       ledger_entries.currency
       transactions.currency
       limit_configs.currency
       pricing_configs.currency
       step_up_policies.currency
       reward_budgets.currency
       tenants.base_currency

The airtime_recharges table is scaffolded as an ORM model but has no
migration yet — its currency column will be created at VARCHAR(10) when
the airtime migration lands, so it's omitted from this widen list.

The baseline instruments are seeded for every existing tenant so the
admin UI dropdowns stop being empty after upgrade.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-20

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columns to widen: (table, column).
_CURRENCY_COLUMNS: list[tuple[str, str]] = [
    ("accounts", "currency"),
    ("ledger_entries", "currency"),
    ("transactions", "currency"),
    ("limit_configs", "currency"),
    ("pricing_configs", "currency"),
    ("step_up_policies", "currency"),
    ("reward_budgets", "currency"),
    ("tenants", "base_currency"),
]

# Baseline instruments seeded per tenant. (code, symbol, display_name,
# description, account_type).
_BASELINE_INSTRUMENTS: list[tuple[str, str, str, str, str]] = [
    (
        "ZAR",
        "R",
        "South African Rand",
        "Fiat wallet currency.",
        "financial_wallet",
    ),
    (
        "PTS",
        "Rewards",
        "Rewards Points",
        "Loyalty points credited by the rules engine.",
        "points_account",
    ),
]


def upgrade() -> None:
    """Widen currency columns + create the instruments table + seed baselines."""
    # 1. Widen every currency column. PG accepts CHAR(3) → VARCHAR(10)
    #    as a non-rewriting catalog change since the new type is a
    #    superset; values are preserved.
    for table, column in _CURRENCY_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(length=10),
            existing_type=sa.CHAR(length=3),
            existing_nullable=False,
        )

    # 2. Create the instruments table.
    op.create_table(
        "instruments",
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
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("account_type", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
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
        sa.Column(
            "deleted_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_instruments_status",
        ),
    )
    op.create_index("ix_instruments_tenant", "instruments", ["tenant_id"])
    op.create_index(
        "uq_instruments_tenant_code_alive",
        "instruments",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # 3. Seed every existing tenant with the baseline instruments.
    bind = op.get_bind()
    tenant_ids = bind.execute(
        sa.text("SELECT id FROM tenants WHERE deleted_at IS NULL")
    ).scalars().all()

    for tenant_id in tenant_ids:
        for code, symbol, display_name, description, account_type in _BASELINE_INSTRUMENTS:
            bind.execute(
                sa.text(
                    "INSERT INTO instruments "
                    "(tenant_id, code, symbol, display_name, description, account_type) "
                    "VALUES (:tenant_id, :code, :symbol, :display_name, :description, :account_type) "
                    "ON CONFLICT DO NOTHING"
                ).bindparams(
                    tenant_id=tenant_id,
                    code=code,
                    symbol=symbol,
                    display_name=display_name,
                    description=description,
                    account_type=account_type,
                )
            )


def downgrade() -> None:
    """Drop the instruments table and shrink currency back to CHAR(3).

    NOTE: this downgrade refuses to run if any column holds a value
    longer than 3 chars — narrowing would truncate and silently corrupt
    ledger / transaction history.
    """
    bind = op.get_bind()
    for table, column in _CURRENCY_COLUMNS:
        long_count = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {table} WHERE LENGTH({column}) > 3"
            )
        ).scalar()
        if long_count:
            raise RuntimeError(
                f"Cannot downgrade: {long_count} rows in {table}.{column} "
                "have currency codes longer than 3 chars."
            )

    op.drop_index("uq_instruments_tenant_code_alive", table_name="instruments")
    op.drop_index("ix_instruments_tenant", table_name="instruments")
    op.drop_table("instruments")

    for table, column in _CURRENCY_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.CHAR(length=3),
            existing_type=sa.String(length=10),
            existing_nullable=False,
        )
