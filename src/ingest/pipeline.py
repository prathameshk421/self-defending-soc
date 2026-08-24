"""Consume soc.raw.v1, normalize, produce to the variant topics.

At-least-once: offsets are committed only after every produced message in the
batch is confirmed delivered. A record that fails normalization — including
one that makes the normalizer itself raise — is routed to the DLQ and counts
as handled; the pipeline never crash-loops on a poison pill. Duplicates from
redelivery are dedupable downstream via the deterministic event_id.
"""

from __future__ import annotations

from dataclasses import dataclass

from ingest.models import (
    EVENT_SCHEMA_VERSION,
    TOPIC_DLQ,
    TOPIC_EVENTS,
    TOPIC_UNMAPPED,
)
from ingest.normalizer import Invalid, Normalized, Unmapped, normalize
from ingest.ports import AliasResolver, Consumer, Producer, RawMessage


@dataclass(frozen=True)
class BatchResult:
    consumed: int
    events: int
    unmapped: int
    dlq: int
    committed: bool
    failures: int


class Pipeline:
    def __init__(
        self,
        consumer: Consumer,
        producer: Producer,
        resolver: AliasResolver,
        *,
        max_payload_bytes: int,
        batch_size: int = 100,
    ) -> None:
        self._consumer = consumer
        self._producer = producer
        self._resolver = resolver
        self._max_payload_bytes = max_payload_bytes
        self._batch_size = batch_size

    def _process_one(self, message: RawMessage) -> tuple[str, int]:
        """Normalize and produce one record. Returns (variant, 1)."""
        try:
            result = normalize(
                message.value, self._resolver, max_payload_bytes=self._max_payload_bytes
            )
        except Exception as exc:  # poison pill: route, never crash the loop
            result = Invalid(raw="", reason=f"normalizer error: {exc}")

        if isinstance(result, Normalized):
            self._producer.produce(
                TOPIC_EVENTS,
                key=result.event.asset_id,
                value=result.event.model_dump_json().encode("utf-8"),
                headers={"schema_version": str(EVENT_SCHEMA_VERSION)},
            )
            return ("events", 1)
        if isinstance(result, Unmapped):
            self._producer.produce(
                TOPIC_UNMAPPED,
                key=result.record.source_alias,
                value=result.record.model_dump_json().encode("utf-8"),
                headers={"reason": result.reason},
            )
            return ("unmapped", 1)
        self._producer.produce(
            TOPIC_DLQ,
            key=message.key,
            value=result.raw.encode("utf-8"),
            headers={"reason": result.reason},
        )
        return ("dlq", 1)

    def run_once(self) -> BatchResult:
        """Poll one bounded batch, process it, flush, then commit or retry."""
        batch: list[RawMessage] = []
        while len(batch) < self._batch_size:
            message = self._consumer.poll()
            if message is None:
                break
            batch.append(message)

        counts = {"events": 0, "unmapped": 0, "dlq": 0}
        for message in batch:
            variant, n = self._process_one(message)
            counts[variant] += n

        committed = False
        failures: list = []
        if batch:
            failures = self._producer.flush()
            if not failures:
                self._consumer.commit(batch)
                committed = True

        return BatchResult(
            consumed=len(batch),
            events=counts["events"],
            unmapped=counts["unmapped"],
            dlq=counts["dlq"],
            committed=committed,
            failures=len(failures),
        )

    def run_forever(self) -> None:  # pragma: no cover - thin loop over run_once
        while True:
            self.run_once()
