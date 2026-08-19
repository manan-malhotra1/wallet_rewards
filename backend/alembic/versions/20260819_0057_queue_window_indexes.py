"""Composite queue-window indexes for approvals pagination (Story B7.2).

The B7.1 approvals window query — WHERE tenant_id AND status ORDER BY
created_at DESC, id DESC LIMIT/OFFSET — was only covered by the
(tenant_id, status) indexes, so Postgres sorted the entire matching set on
every page load. Replace each with (tenant_id, status, created_at, id): a
backward index scan serves the uniform-DESC ordering with no sort, and the
(tenant_id, status) prefix keeps serving the /counts grouped query and every
status-filtered lookup the old index served.

Revision ID: 0057
Revises: 0056
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | None = None
depends_on: str | None = None

# (table, old single-purpose index, new window-covering index) per queue.
_QUEUES = [
    ("config_change_requests", "ix_config_change_requests_tenant_status"),
    ("money_operation_requests", "ix_money_operation_requests_tenant_status"),
    ("user_operation_requests", "ix_user_operation_requests_tenant_status"),
]


def upgrade() -> None:
    """Swap each queue's (tenant_id, status) index for the composite window index."""
    for table, old_index in _QUEUES:
        op.drop_index(old_index, table_name=table)
        op.create_index(
            f"{old_index}_created",
            table,
            ["tenant_id", "status", "created_at", "id"],
            unique=False,
        )


def downgrade() -> None:
    """Restore the original (tenant_id, status) indexes."""
    for table, old_index in _QUEUES:
        op.drop_index(f"{old_index}_created", table_name=table)
        op.create_index(old_index, table, ["tenant_id", "status"], unique=False)
