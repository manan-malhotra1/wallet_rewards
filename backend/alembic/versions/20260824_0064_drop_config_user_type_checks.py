"""drop the static user_type CHECKs on the four config tables

Migration 0061 dropped `ck_users_user_type` so a tenant could put a custom type
on a user, but left the identical allowlist CHECKs on `limit_configs`,
`wallet_limit_configs`, `pricing_configs` and `commission_configs` (from 0022
and 0027). The result was a feature that could not be used: an operator could
create a custom type and then not price or cap it, because every config write
carrying that type was refused by the database.

It was refused *misleadingly*. `create_*_config` catches `IntegrityError` and
maps it to a 409 "config already exists", so the CHECK violation reached the
operator as a phantom collision on a scope that was in fact empty.

This is the same trade 0061 already made, extended to the tables that needed it:
a static database allowlist is replaced by service-level validation that can see
runtime data (spec §6, §11). `assert_optional_user_type_valid` is wired into all
eight create/replace paths across `limits`, `pricing` and `commissions`, so the
guarantee survives — it just moved to the only layer that can express it.

Revision ID: 0064
Revises: 0063
Create Date: 2026-08-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The five seeded system types (0061 §4.3) — the exact allowlist the dropped
# CHECKs encoded. Single source of truth for both the recreated constraint and
# the downgrade guard, so the two can never disagree.
_SYSTEM_CODES = ("consumer", "agent", "super_agent", "merchant", "head_merchant")

# (table, constraint) for every config table that pins `user_type`.
_CONSTRAINTS = (
    ("limit_configs", "ck_limit_configs_user_type"),
    ("wallet_limit_configs", "ck_wallet_limit_configs_user_type"),
    ("pricing_configs", "ck_pricing_configs_user_type"),
    ("commission_configs", "ck_commission_configs_user_type"),
)

_ALLOWLIST_SQL = ", ".join(f"'{code}'" for code in _SYSTEM_CODES)


def upgrade() -> None:
    """Drop the four static `user_type` CHECKs from the config tables.

    Side effects:
        Removes `ck_limit_configs_user_type`, `ck_wallet_limit_configs_user_type`,
        `ck_pricing_configs_user_type` and `ck_commission_configs_user_type`.
        After this migration the `user_type` on a config row is validated in the
        service layer only (spec §11) — the database no longer constrains it,
        exactly as 0061 left `users.user_type`.
    """
    for table, constraint in _CONSTRAINTS:
        op.drop_constraint(constraint, table, type_="check")


def downgrade() -> None:
    """Recreate the four CHECKs — aborts if any config uses a custom type.

    Every table is inspected BEFORE any DDL runs. Recreating a CHECK over a
    table that already holds a custom type would fail mid-migration, leaving
    some constraints restored and others not; refusing up front keeps the
    schema in one consistent state either way. Mirrors 0061's downgrade guard.

    Raises:
        RuntimeError: a config row carries a `user_type` outside the five system
            codes. Rescope or delete those rows before downgrading.
    """
    conn = op.get_bind()
    offenders = []
    for table, _ in _CONSTRAINTS:
        # Interpolated, not bound: `table` and the allowlist are module-level
        # literals, never caller input, and identifiers cannot be parameters.
        count = conn.execute(
            sa.text(
                f"SELECT count(*) FROM {table} "
                f"WHERE user_type IS NOT NULL AND user_type NOT IN ({_ALLOWLIST_SQL})"
            )
        ).scalar_one()
        if count:
            offenders.append(f"{table}: {count}")
    if offenders:
        raise RuntimeError(
            "Cannot downgrade: config rows reference non-system user types "
            f"({'; '.join(offenders)}). Rescope or delete those rows first."
        )

    for table, constraint in _CONSTRAINTS:
        op.create_check_constraint(constraint, table, f"user_type IN ({_ALLOWLIST_SQL})")
