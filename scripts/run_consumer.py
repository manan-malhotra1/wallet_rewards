#!/usr/bin/env python3
"""Long-running Kafka consumer for `wallet.events.external`.

Wraps `events.service.process_external_event` — the same code path used by
the test HTTP endpoint. Each Kafka message is deserialised, processed, and
the outcome is printed. Ctrl-C to stop.

Usage:
    python scripts/run_consumer.py

In another terminal, publish events with:
    python scripts/publish_event.py
"""
from __future__ import annotations

import asyncio
import json
import signal
import sys
from pathlib import Path

# Allow running from anywhere.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from confluent_kafka import Consumer  # noqa: E402

from app.config import Topics, settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.modules.events.schemas import RawExternalEvent  # noqa: E402
from app.modules.events.service import process_external_event  # noqa: E402

CONSUMER_GROUP = "wallet-platform.events.external"
_stop = False


def _handle_sigint(signum, frame) -> None:
    """Allow Ctrl-C to break out of the poll loop cleanly."""
    global _stop
    _stop = True


async def _process_message(raw_bytes: bytes) -> None:
    """Deserialise + run the events pipeline on one Kafka message.

    Each message gets its own DB session so errors on one event do not
    poison the next.
    """
    try:
        payload = json.loads(raw_bytes.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"  ! malformed message — skipping: {exc}")
        return

    try:
        event = RawExternalEvent.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 — Pydantic + others
        print(f"  ! schema validation failed: {exc}")
        return

    async with SessionLocal() as session:
        try:
            result = await process_external_event(session, event)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! processing failed: {exc}")
            return

    fired = ", ".join(
        f"{f.rule_name}(+{f.reward_value} {f.reward_type})"
        for f in result.rules_fired
    )
    suffix = f" — fired: {fired}" if result.rules_fired else ""
    print(f"  · {result.outcome} {event.event_id[:8]}…{suffix}")


def main() -> None:
    """Subscribe to wallet.events.external and process messages in a loop."""
    signal.signal(signal.SIGINT, _handle_sigint)

    consumer = Consumer({
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([Topics.EVENTS_EXTERNAL])
    print(
        f"Listening on '{Topics.EVENTS_EXTERNAL}' "
        f"(group: {CONSUMER_GROUP}). Ctrl-C to stop."
    )

    loop = asyncio.new_event_loop()
    try:
        while not _stop:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"  ! consumer error: {msg.error()}")
                continue
            loop.run_until_complete(_process_message(msg.value()))
    finally:
        consumer.close()
        loop.close()
        print("Consumer stopped.")


if __name__ == "__main__":
    main()
