"""Split the single `taxes` wallet into service-charge + commission tax collectors.

Epic 25: tax on a service fee vs tax on an agent commission now settle into two
distinct system accounts (`tax_service_collected`, `tax_commission_collected`)
so the two tax bases are distinguishable. Existing `taxes` accounts (which held
the combined figure) are folded into the service-charge collector, then `taxes`
is dropped from the account-type CHECK.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

# The full allowed set AFTER the split (mirrors ACCOUNT_TYPES in accounts.py).
_ALLOWED_AFTER = [
    "financial_wallet",
    "points_account",
    "system_points_issuance",
    "provider_redemption_wallet",
    "system_cash_inflow",
    "system_fee_collected",
    "operator_adjustment",
    "airtime_merchant_holding",
    "commission",
    "tax_service_collected",
    "tax_commission_collected",
]
_ALLOWED_BEFORE = [
    *[t for t in _ALLOWED_AFTER if not t.startswith("tax_")],
    "taxes",
]


def _recreate_check(types: list[str]) -> None:
    types_sql = ", ".join(f"'{t}'" for t in types)
    op.create_check_constraint("ck_accounts_type", "accounts", f"account_type IN ({types_sql})")


def upgrade() -> None:
    """Fold legacy `taxes` accounts into the service collector; swap the CHECK.

    Drop the CHECK FIRST so the UPDATE to the new value is legal, then recreate
    it with the final set. `taxes` historically held fee-tax + commission-tax
    combined; that balance goes to the service-charge collector (primary base).
    """
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.execute(
        "UPDATE accounts SET account_type = 'tax_service_collected' WHERE account_type = 'taxes'"
    )
    _recreate_check(_ALLOWED_AFTER)


def downgrade() -> None:
    """Rename the two tax collectors back toward `taxes`.

    Limitation: if BOTH collectors exist for the same (tenant, currency), they
    cannot be merged into a single `taxes` row — `uq_accounts_system_scoped`
    forbids two, and the ledger is append-only so entries can't be re-pointed.
    This downgrade therefore only restores cleanly when at most one collector
    has data per scope (e.g. a tenant that never ran a commission-taxed charge).
    """
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.execute(
        "UPDATE accounts SET account_type = 'taxes' "
        "WHERE account_type IN ('tax_service_collected', 'tax_commission_collected')"
    )
    _recreate_check(_ALLOWED_BEFORE)
