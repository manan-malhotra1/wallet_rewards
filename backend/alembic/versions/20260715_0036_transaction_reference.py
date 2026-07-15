"""Add customer-facing `reference` to transactions + per-tenant sequences.

Every transaction gets a human reference `S_<YYYYMMDDHHMMSS><NNNNNN>` where the
timestamp is the creation instant (UTC) and NNNNNN a per-tenant running number
drawn from a native Postgres sequence `txn_ref_seq_<tenant_hex>` (fast/concurrent;
a rolled-back txn may burn a number — gaps are acceptable by design). References
are unique WITHIN a tenant (each tenant has its own sequence), never globally.

This migration adds the column + a partial unique index, provisions one sequence
per existing tenant, backfills existing rows in (created_at, id) order, and
advances each sequence past the backfilled numbers.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def _tenant_sequence_name(tenant_hex: str) -> str:
    """Return `txn_ref_seq_<hex>` — hex is uuid `[0-9a-f]{32}`, safe to interpolate."""
    return f"txn_ref_seq_{tenant_hex}"


def upgrade() -> None:
    """Add reference + unique index, create sequences, backfill, set sequences."""
    op.add_column("transactions", sa.Column("reference", sa.String(length=40), nullable=True))
    op.create_index(
        "uq_transactions_reference_per_tenant",
        "transactions",
        ["tenant_id", "reference"],
        unique=True,
        postgresql_where=sa.text("reference IS NOT NULL"),
    )

    conn = op.get_bind()
    tenant_ids = conn.execute(sa.text("SELECT id FROM tenants")).scalars().all()
    for tenant_id in tenant_ids:
        tenant_hex = tenant_id.hex if hasattr(tenant_id, "hex") else str(tenant_id).replace("-", "")
        seq_name = _tenant_sequence_name(tenant_hex)
        # Sequences aren't ORM-expressible — raw SQL is the sanctioned exception.
        # Only the validated uuid-hex name is interpolated; never user input.
        op.execute(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"')

        # Backfill this tenant's transactions in stable (created_at, id) order,
        # numbering from 1. The reference mirrors what the app builds at runtime.
        op.execute(
            sa.text(
                """
                WITH numbered AS (
                    SELECT id,
                           row_number() OVER (ORDER BY created_at, id) AS rn
                    FROM transactions
                    WHERE tenant_id = :tenant_id
                )
                UPDATE transactions t
                SET reference = 'S_'
                    || to_char(t.created_at AT TIME ZONE 'UTC', 'YYYYMMDDHH24MISS')
                    || lpad(numbered.rn::text, 6, '0')
                FROM numbered
                WHERE t.id = numbered.id
                """
            ).bindparams(tenant_id=tenant_id)
        )

        # Advance the sequence past the backfilled numbers so new refs continue
        # after them. setval(..., N, true) makes the NEXT nextval() return N+1.
        # When the tenant has zero transactions, seed with setval(..., 1, false)
        # so the first nextval() returns 1.
        count = conn.execute(
            sa.text("SELECT count(*) FROM transactions WHERE tenant_id = :tenant_id").bindparams(
                tenant_id=tenant_id
            )
        ).scalar_one()
        if count > 0:
            op.execute(f"SELECT setval('\"{seq_name}\"', {count}, true)")
        else:
            op.execute(f"SELECT setval('\"{seq_name}\"', 1, false)")


def downgrade() -> None:
    """Drop the index, the column, and every per-tenant sequence."""
    conn = op.get_bind()
    tenant_ids = conn.execute(sa.text("SELECT id FROM tenants")).scalars().all()

    op.drop_index("uq_transactions_reference_per_tenant", table_name="transactions")
    op.drop_column("transactions", "reference")

    for tenant_id in tenant_ids:
        tenant_hex = tenant_id.hex if hasattr(tenant_id, "hex") else str(tenant_id).replace("-", "")
        seq_name = _tenant_sequence_name(tenant_hex)
        op.execute(f'DROP SEQUENCE IF EXISTS "{seq_name}"')
