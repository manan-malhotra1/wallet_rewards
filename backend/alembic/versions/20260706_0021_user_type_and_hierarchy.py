"""add users.user_type + users.parent_user_id (user-types foundation)

Epic 12 (WAL user-types). Makes the five user types a first-class dimension on
`users` and adds a nullable self-referential parent link for the agent/merchant
hierarchy (Decision D4 — store the link now, defer commission/roll-up logic).

The type enum is modelled as VARCHAR + CHECK, not a native PG enum, to match
the repo's database conventions (.claude/rules/database.md) and every other
enum in the schema (status, account_type, business_type). Parent<->child type
compatibility is a cross-row rule and is enforced in the identity service, not
here.

Existing rows backfill to 'consumer' via the column server_default, so no
separate UPDATE is required.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add user_type (VARCHAR+CHECK, default consumer) and parent_user_id self-FK."""
    # user_type — NOT NULL with a server_default so existing rows are backfilled
    # to 'consumer' in the same statement (no separate UPDATE needed).
    op.add_column(
        "users",
        sa.Column(
            "user_type",
            sa.String(length=20),
            nullable=False,
            server_default="consumer",
        ),
    )
    op.create_check_constraint(
        "ck_users_user_type",
        "users",
        "user_type IN ('consumer', 'agent', 'super_agent', 'merchant', 'head_merchant')",
    )
    # Common admin filter: list/segment users of a given type within a tenant.
    op.create_index(
        "ix_users_tenant_user_type",
        "users",
        ["tenant_id", "user_type"],
    )

    # parent_user_id — nullable self-FK. Type compatibility (agent->super_agent,
    # merchant->head_merchant, same tenant) is validated in the service layer.
    op.add_column(
        "users",
        sa.Column(
            "parent_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_parent_user_id",
        "users",
        ["parent_user_id"],
    )


def downgrade() -> None:
    """Reverse the parent_user_id + user_type additions.

    Dropping a column drops its FK + single-column index with it, so we only
    need to drop the composite index and the named CHECK constraint explicitly.
    """
    op.drop_column("users", "parent_user_id")

    op.drop_index("ix_users_tenant_user_type", table_name="users")
    op.drop_constraint("ck_users_user_type", "users", type_="check")
    op.drop_column("users", "user_type")
