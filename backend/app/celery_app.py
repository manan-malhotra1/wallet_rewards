"""Celery application + beat schedule for background/periodic work.

First periodic job is the reward-outbox reconciliation sweep (rewards.recon_sweep),
which drains any reward_outbox rows the post-commit immediate attempt missed.
Second is the dynamic segment membership refresh (segments.recompute_all —
segmentation spec §4), which recomputes every tenant's criteria-based
segments on an hourly default. The broker/result backend is Redis
(settings.REDIS_URL). Task modules are imported via `include` so
`@shared_task`s register on worker start.

Run: `celery -A app.celery_app worker` and `celery -A app.celery_app beat`.
"""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "sasai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    # Modules holding @shared_task definitions — imported on worker startup so
    # the tasks are registered against this app.
    include=["app.modules.rewards.outbox", "app.modules.segments.tasks"],
)

# Periodic schedule (Celery beat). Keys are human-readable schedule names.
celery_app.conf.beat_schedule = {
    # Reconciliation safety net: catch reward_outbox rows the immediate
    # post-commit attempt missed (crash / transient error). Idempotent core,
    # so overlapping with the immediate path can never double-issue.
    "rewards-recon-sweep": {
        "task": "rewards.recon_sweep",
        "schedule": 60.0,
    },
    # Dynamic segment membership refresh (segmentation spec §4). Weekly default;
    # override via SEGMENT_RECOMPUTE_INTERVAL_SECS.
    "segments-recompute": {
        "task": "segments.recompute_all",
        "schedule": float(settings.SEGMENT_RECOMPUTE_INTERVAL_SECS),
    },
}
celery_app.conf.timezone = "UTC"
