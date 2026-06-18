"""Segments module — static user cohorts (Epic 10 / WAL-79)."""
from app.modules.segments.router import router
from app.modules.segments.service import (
    add_user_to_segment,
    create_segment,
    list_segments_for_tenant,
    user_is_in_segment,
)

__all__ = [
    "router",
    "add_user_to_segment",
    "create_segment",
    "list_segments_for_tenant",
    "user_is_in_segment",
]
