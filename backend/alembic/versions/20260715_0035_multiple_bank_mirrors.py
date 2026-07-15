"""Allow multiple named bank-mirror (operator_adjustment) accounts per scope.

Epic 26: a tenant may run several `operator_adjustment` cash-float mirrors per
(tenant, currency), each distinguished by `name`, and the operator picks which
one is the counter-leg on each withdraw / adjust. This adds the `name` column,
relaxes `uq_accounts_system_scoped` so it no longer forces a single
operator_adjustment (other system accounts stay single-instance), adds
`uq_accounts_bank_mirror` (unique by name), and names the existing seeded mirror
"Primary".
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add `name`, relax the system-scoped index, add the bank-mirror index."""
    op.add_column("accounts", sa.Column("name", sa.String(length=100), nullable=True))

    # Relax the single-instance rule so it no longer covers operator_adjustment.
    op.drop_index("uq_accounts_system_scoped", table_name="accounts")
    op.create_index(
        "uq_accounts_system_scoped",
        "accounts",
        ["tenant_id", "account_type", "currency"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL AND account_type <> 'operator_adjustment'"),
    )

    # Bank mirrors: several per (tenant, currency), unique by name.
    op.create_index(
        "uq_accounts_bank_mirror",
        "accounts",
        ["tenant_id", "currency", "name"],
        unique=True,
        postgresql_where=sa.text("account_type = 'operator_adjustment' AND user_id IS NULL"),
    )

    # Name the pre-existing single mirror so it satisfies the new unique index.
    op.execute(
        "UPDATE accounts SET name = 'Primary' "
        "WHERE account_type = 'operator_adjustment' AND name IS NULL"
    )


def downgrade() -> None:
    """Restore the strict system-scoped index and drop the bank-mirror bits.

    Reversible only when at most one operator_adjustment exists per
    (tenant, currency) — the restored `uq_accounts_system_scoped` predicate
    forbids more. Callers must consolidate mirrors before downgrading.
    """
    op.drop_index("uq_accounts_bank_mirror", table_name="accounts")
    op.drop_index("uq_accounts_system_scoped", table_name="accounts")
    op.create_index(
        "uq_accounts_system_scoped",
        "accounts",
        ["tenant_id", "account_type", "currency"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.drop_column("accounts", "name")
