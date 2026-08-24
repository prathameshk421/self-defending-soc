#!/bin/bash
# One-shot topic + ACL bootstrap. Runs as the admin superuser.
set -euo pipefail

BIN=/opt/kafka/bin
BOOTSTRAP=kafka:9092
CONF=/tmp/admin.properties

printf 'security.protocol=SASL_PLAINTEXT\nsasl.mechanism=PLAIN\nsasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required username="admin" password="%s";\n' "$KAFKA_ADMIN_PASSWORD" > "$CONF"

create_topic() {
  local name=$1 partitions=$2 retention_ms=$3
  "$BIN/kafka-topics.sh" --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" \
    --create --if-not-exists --topic "$name" --partitions "$partitions" \
    --replication-factor 1 --config "retention.ms=$retention_ms"
}

# Topic budget: raw 48h, events 7d, unmapped/dlq 72h.
create_topic soc.raw.v1 3 172800000
"$BIN/kafka-configs.sh" --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" \
  --alter --entity-type topics --entity-name soc.raw.v1 \
  --add-config retention.bytes=1073741824,retention.ms=172800000
create_topic soc.events.v1 3 604800000
create_topic soc.ingest.unmapped.v1 1 259200000
create_topic soc.ingest.dlq.v1 1 259200000

acl() {
  "$BIN/kafka-acls.sh" --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" --add "$@"
}

# vector: write raw only.
acl --allow-principal User:vector --operation Write --operation Describe --topic soc.raw.v1

# ingest: read raw; write events/unmapped/dlq; consumer group access.
acl --allow-principal User:ingest --operation Read --operation Describe --topic soc.raw.v1
acl --allow-principal User:ingest --operation Write --operation Describe --topic soc.events.v1
acl --allow-principal User:ingest --operation Write --operation Describe --topic soc.ingest.unmapped.v1
acl --allow-principal User:ingest --operation Write --operation Describe --topic soc.ingest.dlq.v1
acl --allow-principal User:ingest --operation Read --group ingest-normalizer

# karapace: its own state topic and group only.
acl --allow-principal User:karapace --operation All --topic _schemas
acl --allow-principal User:karapace --operation All --group karapace-registry
acl --allow-principal User:karapace --operation Describe --operation Create --cluster

echo "kafka-init: topics and ACLs applied"
