"""Rename tenants.deployment_mode → business_type (wallet|rewards|both) and add keycloak_realm.

Phase 1 of the Tenant Management refactor: tenants now declare a *business type*
(what services are enabled) separately from any historical 'deployment mode'.
The old enum's two values map cleanly into the new three-value enum:

  old 'wallet'       (= full platform: wallet + rewards) → new 'both'
  old 'rewards_only' (= rewards engine only)             → new 'rewards'
  new 'wallet'       (= wallet without rewards) is new — no existing rows.

Also adds tenants.keycloak_realm so the admin UI can surface the realm tag
(read-only). Backfilled from the KEYCLOAK_REALM env var (single-realm Phase 1).

Revision ID: 0016
Revises: 0015
Created: 2026-06-20
"""
from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa

# Alembic identifiers
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename column, swap CHECK constraint, backfill values, add realm column."""
    # 1. Drop the old CHECK so we can backfill freely.
    op.drop_constraint("ck_tenants_deployment_mode", "tenants", type_="check")

    # 2. Rename the column. SQLAlchemy ORM will reference it as business_type
    #    starting in the same migration window.
    op.alter_column("tenants", "deployment_mode", new_column_name="business_type")

    # 3. Backfill: old 'wallet' (full stack) → 'both'; old 'rewards_only' → 'rewards'.
    #    Done as raw UPDATE because the values are well-known constants and we
    #    need this to land in the same transaction as the constraint swap.
    op.execute(
        "UPDATE tenants SET business_type = 'both' WHERE business_type = 'wallet'"
    )
    op.execute(
        "UPDATE tenants SET business_type = 'rewards' WHERE business_type = 'rewards_only'"
    )

    # 4. Re-apply CHECK with the new three-value enum.
    op.create_check_constraint(
        "ck_tenants_business_type",
        "tenants",
        "business_type IN ('wallet', 'rewards', 'both')",
    )

    # 5. Add keycloak_realm (nullable, then backfilled from env).
    op.add_column(
        "tenants",
        sa.Column("keycloak_realm", sa.String(length=100), nullable=True),
    )

    # Backfill realm from the single-realm env var. Empty string left as NULL.
    default_realm = os.environ.get("KEYCLOAK_REALM", "").strip()
    if default_realm:
        op.execute(
            sa.text("UPDATE tenants SET keycloak_realm = :realm").bindparams(
                realm=default_realm
            )
        )


def downgrade() -> None:
    """Reverse the rename + drop realm column.

    Note: any rows with business_type='wallet' (the new "wallet-only" value)
    cannot round-trip — old enum had no such value. This downgrade refuses
    to run if any such rows exist, rather than silently corrupting data.
    """
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT COUNT(*) FROM tenants WHERE business_type = 'wallet'")
    ).scalar()
    if count:
        raise RuntimeError(
            f"Cannot downgrade: {count} tenant(s) have business_type='wallet' "
            "which has no equivalent in the old deployment_mode enum."
        )

    op.drop_column("tenants", "keycloak_realm")

    op.drop_constraint("ck_tenants_business_type", "tenants", type_="check")
    op.execute(
        "UPDATE tenants SET business_type = 'rewards_only' WHERE business_type = 'rewards'"
    )
    op.execute(
        "UPDATE tenants SET business_type = 'wallet' WHERE business_type = 'both'"
    )
    op.alter_column("tenants", "business_type", new_column_name="deployment_mode")
    op.create_check_constraint(
        "ck_tenants_deployment_mode",
        "tenants",
        "deployment_mode IN ('wallet', 'rewards_only')",
    )
