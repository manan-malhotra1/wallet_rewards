#!/usr/bin/env python3
"""Publish a sample event to the `wallet.events.external` Kafka topic.

Used to drive the rewards pipeline end-to-end manually. The published event
matches the standard NormalisedEvent schema (Pay-PRD-0480 / Pay-PRD-0490).

Usage:
    python scripts/publish_event.py \\
        --tenant-name Sasai-ZA \\
        --user-phone "+27 82 555 0001" \\
        --source-key sasai-bank \\
        --transaction-type top_up \\
        --amount 500

Defaults exercise the seed-loaded first-time top-up rule (100 points reward).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# Allow running this script from anywhere — add backend/ to sys.path.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from confluent_kafka import Producer  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import Topics, settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.shared.models import Tenant, User, UserIdentifier  # noqa: E402


async def _resolve_user_id(tenant_name: str, phone: str) -> tuple[str, str]:
    """Look up (tenant_id, user_id) for the (tenant_name, phone) pair."""
    async with SessionLocal() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.name == tenant_name)
        )).scalar_one_or_none()
        if tenant is None:
            sys.exit(f"Tenant '{tenant_name}' not found. Run scripts/seed.py first.")

        identifier = (await session.execute(
            select(UserIdentifier).where(
                UserIdentifier.tenant_id == tenant.id,
                UserIdentifier.identifier_type == "phone",
                UserIdentifier.identifier_value == phone,
            )
        )).scalar_one_or_none()
        if identifier is None:
            sys.exit(
                f"User with phone {phone!r} not found in tenant '{tenant_name}'."
            )
        user = (await session.execute(
            select(User).where(User.id == identifier.user_id)
        )).scalar_one()
        return str(tenant.id), str(user.id)


def _delivery_report(err, msg) -> None:
    """confluent-kafka producer delivery callback."""
    if err is not None:
        print(f"  ! delivery failed: {err}")
    else:
        print(
            f"  ✓ delivered to {msg.topic()} partition {msg.partition()} "
            f"offset {msg.offset()}"
        )


def main() -> None:
    """Build the event JSON and publish it to wallet.events.external."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-name", default="Sasai-ZA")
    parser.add_argument("--user-phone", default="+27 82 555 0001")
    parser.add_argument("--source-key", default="sasai-bank")
    parser.add_argument("--transaction-type", default="top_up")
    parser.add_argument("--amount", default="500")
    parser.add_argument("--currency", default="ZAR")
    parser.add_argument(
        "--event-id",
        default=None,
        help="Override the event_id (otherwise a fresh UUID is used).",
    )
    args = parser.parse_args()

    tenant_id, user_id = asyncio.run(
        _resolve_user_id(args.tenant_name, args.user_phone)
    )

    event = {
        "event_id": args.event_id or uuid4().hex,
        "source_key": args.source_key,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "transaction_type": args.transaction_type,
        "amount": str(Decimal(args.amount)),
        "currency": args.currency,
        "merchant_id": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw": {"source": "publish_event.py"},
    }

    print("Publishing event:")
    print(json.dumps(event, indent=2))
    print()

    producer = Producer({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
    # Partition key = user_id per the platform convention (preserves per-user order).
    producer.produce(
        Topics.EVENTS_EXTERNAL,
        key=user_id,
        value=json.dumps(event),
        callback=_delivery_report,
    )
    producer.flush(timeout=10)


if __name__ == "__main__":
    main()
