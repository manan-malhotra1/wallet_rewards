"""Create the services catalog table (Phase 2 of the Tenant Management refactor).

Each row is one transaction_type the tenant has switched on. The `code`
column is the persistent identifier stored in downstream tables
(limit_configs, pricing_configs, rules, transactions); `display_name` is
the human-facing label shown in the admin UI and partner integrations.

Seeds every existing tenant with the three baseline services in use as
of Phase 1 (p2p, airtime_recharge, redemption). Phase 4 will append
'fund' and 'withdraw' once those services land.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, display_name, description) — the Phase-2 baseline catalog.
# Order matches the user-facing checkout flow priority.
_BASELINE_SERVICES: list[tuple[str, str, str]] = [
    (
        "p2p",
        "Peer-to-Peer",
        "Send funds from one wallet to another within the platform.",
    ),
    (
        "airtime_recharge",
        "Airtime Recharge",
        "Top up a mobile number via a registered airtime merchant.",
    ),
    (
        "redemption",
        "Redemption",
        "Redeem reward points with a registered redemption provider.",
    ),
]


def upgrade() -> None:
    """Create the services table + seed each existing tenant's baseline rows."""
    op.create_table(
        "services",
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
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
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
            name="ck_services_status",
        ),
    )
    op.create_index("ix_services_tenant", "services", ["tenant_id"])

    # Partial UNIQUE: only enforce uniqueness on the live (non-deleted)
    # rows so soft-deleted entries don't block re-adding the same code.
    op.create_index(
        "uq_services_tenant_code_alive",
        "services",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Seed every existing tenant with the three baseline services.
    # Done inline (rather than at app boot) so a fresh `alembic upgrade head`
    # leaves the platform usable end-to-end with no extra commands.
    bind = op.get_bind()
    tenant_ids = (
        bind.execute(sa.text("SELECT id FROM tenants WHERE deleted_at IS NULL")).scalars().all()
    )

    for tenant_id in tenant_ids:
        for code, display_name, description in _BASELINE_SERVICES:
            bind.execute(
                sa.text(
                    "INSERT INTO services "
                    "(tenant_id, code, display_name, description) "
                    "VALUES (:tenant_id, :code, :display_name, :description) "
                    "ON CONFLICT DO NOTHING"
                ).bindparams(
                    tenant_id=tenant_id,
                    code=code,
                    display_name=display_name,
                    description=description,
                )
            )


def downgrade() -> None:
    """Drop the services table outright (no foreign keys reference it yet)."""
    op.drop_index("uq_services_tenant_code_alive", table_name="services")
    op.drop_index("ix_services_tenant", table_name="services")
    op.drop_table("services")
