#!/usr/bin/env bash
# Idempotent Kafka topic creation. Safe to re-run.
# Topics must match constants in backend/app/config.py:Topics.

set -euo pipefail

KAFKA_CONTAINER="${KAFKA_CONTAINER:-infra-kafka-1}"
BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:29092}"
PARTITIONS="${KAFKA_PARTITIONS:-3}"
REPLICATION="${KAFKA_REPLICATION:-1}"

TOPICS=(
  "wallet.transactions.completed"
  "wallet.events.external"
  "wallet.events.normalised"
  "wallet.rewards.issued"
  "wallet.engagement.outbound"
  "wallet.reconciliation.pending"
)

echo "Creating Kafka topics on $BOOTSTRAP (partitions=$PARTITIONS, replication=$REPLICATION)..."

for topic in "${TOPICS[@]}"; do
  docker exec "$KAFKA_CONTAINER" kafka-topics \
    --bootstrap-server "$BOOTSTRAP" \
    --create \
    --if-not-exists \
    --topic "$topic" \
    --partitions "$PARTITIONS" \
    --replication-factor "$REPLICATION" \
    && echo "  ✓ $topic"
done

echo ""
echo "Listing all topics:"
docker exec "$KAFKA_CONTAINER" kafka-topics \
  --bootstrap-server "$BOOTSTRAP" \
  --list
