"""Shared fakes and fixtures for ingest tests. No live services, no mocks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

from estate.errors import AmbiguousAlias, NotFound
from ingest.models import TOPIC_RAW, RawRecord
from ingest.ports import DeliveryFailure, ProduceRequest, RawMessage

INVENTORY_PATH = Path(__file__).resolve().parents[2] / "inventory" / "default.yaml"

OBSERVED_AT = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


class FakeResolver:
    """Alias -> asset_id map mirroring Estate.resolve_alias semantics."""

    def __init__(self, aliases: dict[str, str], ambiguous: set[str] = frozenset()):
        self._aliases = aliases
        self._ambiguous = set(ambiguous)

    def resolve_alias(self, lab_id: str, alias: str) -> str:
        if alias in self._ambiguous:
            raise AmbiguousAlias(f"ambiguous alias: {alias}")
        try:
            return self._aliases[alias]
        except KeyError:
            raise NotFound(f"alias not found: {alias}") from None


class FakeProducer:
    def __init__(self) -> None:
        self.produced: list[ProduceRequest] = []
        self.fail_next_flush: list[DeliveryFailure] = []
        self.flush_calls = 0

    def produce(self, topic, key, value, headers=None) -> None:
        self.produced.append(
            ProduceRequest(topic=topic, key=key, value=value, headers=headers or {})
        )

    def flush(self) -> list[DeliveryFailure]:
        self.flush_calls += 1
        failures, self.fail_next_flush = self.fail_next_flush, []
        return failures


class FakeConsumer:
    def __init__(self, messages: list[RawMessage]) -> None:
        self._messages = list(messages)
        self.committed: list[RawMessage] = []

    def poll(self, timeout: float = 1.0) -> Optional[RawMessage]:
        if self._messages:
            return self._messages.pop(0)
        return None

    def commit(self, message: RawMessage) -> None:
        self.committed.append(message)


def make_raw_record(
    source_alias: str = "lab-shop",
    raw: str = "GET /index.html 200",
    lab_id: str = "default",
    source_type: str = "file",
) -> RawRecord:
    return RawRecord(
        lab_id=lab_id,
        source_alias=source_alias,
        source_type=source_type,
        collector="vector",
        raw=raw,
        observed_at=OBSERVED_AT,
    )


def make_raw_message(record: RawRecord, offset: int = 0) -> RawMessage:
    return RawMessage(
        topic=TOPIC_RAW,
        partition=0,
        offset=offset,
        key=record.source_alias,
        value=record.model_dump_json().encode("utf-8"),
    )


@pytest.fixture
def resolver() -> FakeResolver:
    return FakeResolver(
        {"lab-shop": "asset-shop", "lab-idp": "asset-idp"},
        ambiguous={"dup-alias"},
    )
