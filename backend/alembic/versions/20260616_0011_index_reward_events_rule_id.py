"""index reward_events.rule_id for performance aggregation

Adds a standalone B-tree index on `reward_events(rule_id)`. The only
existing index on this table is the composite UNIQUE on
`(user_id, rule_id, triggering_event_id)` for idempotency — because
`rule_id` is not its leftmost column, queries that filter solely by
`rule_id` (e.g. the new `GET /api/v1/rules/{rule_id}/performance`
endpoint, which runs SELECT COUNT/SUM/MIN/MAX over the table) cannot
use it and degrade to a sequential scan.

At current scale a seq-scan is fine; once `reward_events` grows to
millions of rows the performance endpoint would slow noticeably.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-16

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the standalone rule_id index."""
    op.create_index(
        "ix_reward_events_rule_id",
        "reward_events",
        ["rule_id"],
    )


def downgrade() -> None:
    """Drop the index — reverts to the pre-0011 schema."""
    op.drop_index("ix_reward_events_rule_id", table_name="reward_events")
