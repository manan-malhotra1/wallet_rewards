"""Celery application + beat schedule for background/periodic work.

First periodic job is the reward-outbox reconciliation sweep (rewards.recon_sweep),
which drains any reward_outbox rows the post-commit immediate attempt missed. The
broker/result backend is Redis (settings.REDIS_URL). Task modules are imported via
`include` so `@shared_task`s register on worker start.

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
    include=["app.modules.rewards.outbox"],
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
}
celery_app.conf.timezone = "UTC"
