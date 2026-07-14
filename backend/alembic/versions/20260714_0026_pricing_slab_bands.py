"""add amount slab bands + fee_inclusive to pricing_configs (Pricing v2 Epic 19)

Slab fees (Story 19.2): a `pricing_configs` row now carries an optional band
`[amount_from, amount_to)`. Both NULL = applies to all amounts (back-compat with
the pre-slab single-row configs). Several bands can coexist for one scope, so
`amount_from` joins the `uq_pricing_configs_scope` UNIQUE (NULLS NOT DISTINCT so
two NULL-band rows for the same scope still collide).

Also adds the `fee_inclusive` axis-1 flag (default false = exclusive) consumed
by the Epic 20 charge assembler.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_SCOPE_WITH_BAND = "tenant_id, transaction_type, account_type, currency, user_type, amount_from"
_SCOPE_NO_BAND = "tenant_id, transaction_type, account_type, currency, user_type"


def upgrade() -> None:
    """Add band columns + fee_inclusive; fold amount_from into the scope UNIQUE."""
    op.add_column("pricing_configs", sa.Column("amount_from", sa.Numeric(20, 6), nullable=True))
    op.add_column("pricing_configs", sa.Column("amount_to", sa.Numeric(20, 6), nullable=True))
    op.add_column(
        "pricing_configs",
        sa.Column("fee_inclusive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_check_constraint(
        "ck_pricing_configs_amount_band",
        "pricing_configs",
        "amount_from IS NULL OR amount_to IS NULL OR amount_to > amount_from",
    )
    op.drop_constraint("uq_pricing_configs_scope", "pricing_configs", type_="unique")
    # NULLS NOT DISTINCT — no portable flag on create_unique_constraint, so DDL.
    op.execute(
        "ALTER TABLE pricing_configs ADD CONSTRAINT uq_pricing_configs_scope "
        f"UNIQUE NULLS NOT DISTINCT ({_SCOPE_WITH_BAND})"
    )


def downgrade() -> None:
    """Restore the pre-slab scope UNIQUE and drop the new columns."""
    op.drop_constraint("uq_pricing_configs_scope", "pricing_configs", type_="unique")
    op.execute(
        "ALTER TABLE pricing_configs ADD CONSTRAINT uq_pricing_configs_scope "
        f"UNIQUE NULLS NOT DISTINCT ({_SCOPE_NO_BAND})"
    )
    op.drop_constraint("ck_pricing_configs_amount_band", "pricing_configs", type_="check")
    op.drop_column("pricing_configs", "fee_inclusive")
    op.drop_column("pricing_configs", "amount_to")
    op.drop_column("pricing_configs", "amount_from")
