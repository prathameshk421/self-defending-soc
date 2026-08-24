"""Transport-agnostic ports for the pipeline.

The pipeline depends only on these Protocols; confluent-kafka types never
leak past kafka_adapter, so unit tests run with hand-rolled fakes and CI
needs no live Kafka.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class RawMessage:
    topic: str
    partition: int
    offset: int
    key: Optional[str]
    value: bytes


@dataclass(frozen=True)
class DeliveryFailure:
    topic: str
    key: Optional[str]
    error: str


@dataclass(frozen=True)
class ProduceRequest:
    topic: str
    key: Optional[str]
    value: bytes
    headers: dict[str, str] = field(default_factory=dict)


class Producer(Protocol):
    def produce(
        self,
        topic: str,
        key: Optional[str],
        value: bytes,
        headers: Optional[dict[str, str]] = None,
    ) -> None: ...

    def flush(self) -> list[DeliveryFailure]:
        """Block until all queued messages resolve; return delivery failures."""
        ...


class Consumer(Protocol):
    def poll(self, timeout: float = 1.0) -> Optional[RawMessage]: ...

    def commit(self, messages: list[RawMessage]) -> None:
        """Commit max(offset)+1 for each distinct (topic, partition)."""
        ...


class AliasResolver(Protocol):
    def resolve_alias(self, lab_id: str, alias: str) -> str: ...
