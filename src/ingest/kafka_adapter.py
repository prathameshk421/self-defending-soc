"""confluent-kafka adapters implementing the ingest ports.

This module is the only place confluent-kafka is imported, and it is only
imported on the CLI `run`/`emit` paths. Everything else — and the whole test
suite — depends on the Protocols in ingest.ports.
"""

from __future__ import annotations

from typing import Optional

from ingest.config import IngestConfig
from ingest.errors import IngestError
from ingest.models import TOPIC_RAW
from ingest.ports import DeliveryFailure, RawMessage

try:
    import confluent_kafka
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise IngestError(
        "confluent-kafka is not installed; install the [kafka] extra: "
        "pip install 'self-defending-soc[kafka]'"
    ) from exc


def _common_config(config: IngestConfig) -> dict[str, object]:
    kafka_config: dict[str, object] = {"bootstrap.servers": config.bootstrap}
    if config.sasl_username and config.sasl_password:
        kafka_config.update(
            {
                "security.protocol": "SASL_PLAINTEXT",
                "sasl.mechanism": "PLAIN",
                "sasl.username": config.sasl_username,
                "sasl.password": config.sasl_password,
            }
        )
    return kafka_config


class KafkaProducerAdapter:
    def __init__(self, config: IngestConfig) -> None:
        self._producer = confluent_kafka.Producer(
            {
                **_common_config(config),
                "enable.idempotence": True,
                "acks": "all",
            }
        )
        self._failures: list[DeliveryFailure] = []

    def _on_delivery(self, err, msg) -> None:
        if err is not None:
            self._failures.append(
                DeliveryFailure(
                    topic=msg.topic(),
                    key=msg.key().decode("utf-8") if msg.key() else None,
                    error=str(err),
                )
            )

    def produce(
        self,
        topic: str,
        key: Optional[str],
        value: bytes,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self._producer.produce(
            topic,
            key=key.encode("utf-8") if key else None,
            value=value,
            headers=list((headers or {}).items()),
            on_delivery=self._on_delivery,
        )

    def flush(self) -> list[DeliveryFailure]:
        self._producer.flush()
        failures, self._failures = self._failures, []
        return failures


class KafkaConsumerAdapter:
    def __init__(self, config: IngestConfig, *, topic: str = TOPIC_RAW) -> None:
        self._consumer = confluent_kafka.Consumer(
            {
                **_common_config(config),
                "group.id": config.group_id,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
        self._consumer.subscribe([topic])

    def poll(self, timeout: float = 1.0) -> Optional[RawMessage]:
        message = self._consumer.poll(timeout)
        if message is None or message.error() is not None:
            return None
        key = message.key()
        return RawMessage(
            topic=message.topic(),
            partition=message.partition(),
            offset=message.offset(),
            key=key.decode("utf-8") if key else None,
            value=message.value() or b"",
        )

    def commit(self, message: RawMessage) -> None:
        self._consumer.commit(
            offsets=[
                confluent_kafka.TopicPartition(
                    message.topic, message.partition, message.offset + 1
                )
            ],
            asynchronous=False,
        )
