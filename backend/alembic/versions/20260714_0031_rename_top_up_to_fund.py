"""Rename the `top_up` transaction type to `fund` platform-wide.

Aligns the wallet-funding transaction type with its name in the services
catalog (`fund` — "Admin credits a user's wallet from the operator cash
pool"). Before this, wallet funding was posted as `transaction_type='top_up'`
while the catalog, admin UI, and PRD called it "Fund", so the mobile feed
surfaced a stray "Top Up" label.

Data-only migration (DML, no DDL): `transaction_type` is a free-text
String(50) with no CHECK constraint, so renaming the stored value needs no
schema change. `ledger_entries` are untouched — balances are unaffected;
only the descriptive type label on `transactions` and the config/permission
rows that key off it change.

Covers every table carrying a `transaction_type` column so no environment
is left with a dangling `top_up`. Reversible.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

# Every table with a `transaction_type` column (see information_schema).
_TABLES = (
    "transactions",
    "role_permissions",
    "rules",
    "rule_conditions",
    "limit_configs",
    "pricing_configs",
    "commission_configs",
    "step_up_policies",
)


def _rename(from_value: str, to_value: str) -> None:
    """UPDATE transaction_type from one value to another across all tables."""
    for table in _TABLES:
        # Fixed table identifiers + literal values — no user input interpolated.
        op.execute(
            f"UPDATE {table} SET transaction_type = '{to_value}' "
            f"WHERE transaction_type = '{from_value}'"
        )


def upgrade() -> None:
    """Rename `top_up` -> `fund` in every transaction_type column."""
    _rename("top_up", "fund")


def downgrade() -> None:
    """Restore `fund` -> `top_up`."""
    _rename("fund", "top_up")
