"""base/derived service kinds + denormalised base_transaction_type

Adds `services.kind` ('base' | 'derived') and `services.base_service_code`,
with paired CHECK constraints so the base/derived distinction never has to be
inferred from a NULL (spec §4). Also adds `transactions.base_transaction_type`
so API clients can group by flow without knowing every derived code that will
ever exist (spec §12.1) — denormalised rather than joined so history stays
correct even if a derived service is later deleted.

Backfills every existing services row to kind='base' (they are all platform
flows today) and every transactions row's base_transaction_type to its own
transaction_type (no derived services exist yet, so each IS its own base).

GUARD: refuses to run if any live services row carries a code the platform
does not implement. Such a row is pre-existing dead config, and silently
converting it to a "base service" would make the registry lie. Delete or
rename the offending rows first — the error lists them.

Revision ID: 0056
Revises: 0055
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.shared.services_registry import BASE_SERVICE_CODES

revision: str = "0056"
down_revision: str | Sequence[str] | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the kind/base columns, backfill, and constrain."""
    bind = op.get_bind()

    # Guard: dead config must be resolved by a human, not guessed at here.
    codes = ", ".join(f"'{c}'" for c in sorted(BASE_SERVICE_CODES))
    unknown = bind.execute(
        sa.text(
            f"SELECT tenant_id, code FROM services "
            f"WHERE deleted_at IS NULL AND code NOT IN ({codes})"
        )
    ).fetchall()
    if unknown:
        listed = "; ".join(f"tenant={row[0]} code={row[1]}" for row in unknown)
        raise RuntimeError(
            "Cannot migrate: services rows exist with codes the platform does "
            f"not implement ({listed}). These are dead config — delete them or "
            "rename them to an implemented code, then re-run."
        )

    op.add_column(
        "services",
        sa.Column("kind", sa.String(10), nullable=False, server_default="base"),
    )
    op.add_column("services", sa.Column("base_service_code", sa.String(50), nullable=True))
    op.create_check_constraint(
        "ck_services_kind", "services", "kind IN ('base', 'derived')"
    )
    # The pairing is what makes NULL meaningless rather than meaningful.
    op.create_check_constraint(
        "ck_services_kind_base_pairing",
        "services",
        "(kind = 'base' AND base_service_code IS NULL) "
        "OR (kind = 'derived' AND base_service_code IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_services_base_not_self",
        "services",
        "base_service_code IS NULL OR base_service_code <> code",
    )

    # Every existing transaction is its own base (no derived services yet).
    op.add_column(
        "transactions", sa.Column("base_transaction_type", sa.String(50), nullable=True)
    )
    op.execute(sa.text("UPDATE transactions SET base_transaction_type = transaction_type"))
    op.alter_column(
        "transactions",
        "base_transaction_type",
        existing_type=sa.String(50),
        nullable=False,
    )


def downgrade() -> None:
    """Soft-delete derived services, then drop the columns.

    Derived rows must go first: without `base_service_code` their codes
    resolve to no implementation, so leaving them live would recreate exactly
    the dead-config state the upgrade guard rejects.
    """
    op.execute(
        sa.text("UPDATE services SET deleted_at = now() WHERE kind = 'derived'")
    )
    op.drop_column("transactions", "base_transaction_type")
    op.drop_constraint("ck_services_base_not_self", "services", type_="check")
    op.drop_constraint("ck_services_kind_base_pairing", "services", type_="check")
    op.drop_constraint("ck_services_kind", "services", type_="check")
    op.drop_column("services", "base_service_code")
    op.drop_column("services", "kind")
