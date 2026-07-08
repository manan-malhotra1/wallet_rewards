"""add user_type to limit_configs/wallet_limit_configs/pricing_configs (type-aware)

Epics 15 (type-aware limits) + 16 (type-aware pricing). Adds a nullable
`user_type` to all three config tables: NULL means "default — applies to every
user type"; a row with a specific type wins over the NULL default at
enforcement (resolved in the services with ORDER BY user_type NULLS LAST).

Uniqueness must treat NULL as a real value so two NULL-type rows for the same
other dimensions collide — PG 15+ `UNIQUE ... NULLS NOT DISTINCT` (local PG is
16). Each scope constraint is dropped and recreated with `user_type` appended.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-07
"""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_USER_TYPE_CHECK = "user_type IN ('consumer', 'agent', 'super_agent', 'merchant', 'head_merchant')"


def _add_type_scope(table: str, unique_name: str, unique_cols: list[str]) -> None:
    """Add nullable user_type + CHECK, and rebuild the scope UNIQUE with it."""
    op.add_column(table, sa.Column("user_type", sa.String(length=20), nullable=True))
    op.create_check_constraint(f"ck_{table}_user_type", table, _USER_TYPE_CHECK)
    op.drop_constraint(unique_name, table, type_="unique")
    cols = ", ".join(unique_cols)
    # NULLS NOT DISTINCT so a second NULL-type row for the same other dims
    # collides. op.create_unique_constraint has no portable flag for this, so
    # the constraint is added via explicit DDL.
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {unique_name} UNIQUE NULLS NOT DISTINCT ({cols})"
    )


def upgrade() -> None:
    """Add user_type + type-aware scope UNIQUE to the three config tables."""
    _add_type_scope(
        "limit_configs",
        "uq_limit_configs_scope",
        ["tenant_id", "transaction_type", "account_type", "currency", "user_type"],
    )
    _add_type_scope(
        "wallet_limit_configs",
        "uq_wallet_limit_configs_scope",
        ["tenant_id", "currency", "user_type"],
    )
    _add_type_scope(
        "pricing_configs",
        "uq_pricing_configs_scope",
        ["tenant_id", "transaction_type", "account_type", "currency", "user_type"],
    )


def _drop_type_scope(table: str, unique_name: str, unique_cols: list[str]) -> None:
    """Reverse _add_type_scope — restore the original type-agnostic UNIQUE."""
    op.drop_constraint(unique_name, table, type_="unique")
    op.create_unique_constraint(unique_name, table, unique_cols)
    op.drop_constraint(f"ck_{table}_user_type", table, type_="check")
    op.drop_column(table, "user_type")


def downgrade() -> None:
    """Drop user_type and restore the original scope UNIQUE constraints."""
    _drop_type_scope(
        "pricing_configs",
        "uq_pricing_configs_scope",
        ["tenant_id", "transaction_type", "account_type", "currency"],
    )
    _drop_type_scope(
        "wallet_limit_configs",
        "uq_wallet_limit_configs_scope",
        ["tenant_id", "currency"],
    )
    _drop_type_scope(
        "limit_configs",
        "uq_limit_configs_scope",
        ["tenant_id", "transaction_type", "account_type", "currency"],
    )
