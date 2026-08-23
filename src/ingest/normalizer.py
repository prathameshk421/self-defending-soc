"""Pure normalization: raw bytes -> Normalized | Unmapped | Invalid.

No I/O and no topic knowledge here. Routing an unknown alias is an expected
data path, not an exception, so the result is a tagged union that the
pipeline maps to topics. Redaction happens before any variant is returned so
unmapped/DLQ records are never a secret swamp.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Union

from pydantic import ValidationError

from estate.errors import AmbiguousAlias, NotFound
from ingest.models import Event, RawRecord, deterministic_event_id
from ingest.ports import AliasResolver
from ingest.redact import redact

_MAX_INVALID_SNIPPET = 2048

# Payload keys checked (in order) for a best-effort occurred_at timestamp.
_TIMESTAMP_KEYS = ("@timestamp", "timestamp", "time", "ts")


@dataclass(frozen=True)
class Normalized:
    event: Event


@dataclass(frozen=True)
class Unmapped:
    record: RawRecord  # redacted
    reason: str


@dataclass(frozen=True)
class Invalid:
    raw: str  # redacted, truncated
    reason: str


NormalizeResult = Union[Normalized, Unmapped, Invalid]


def _strip_control_chars(text: str) -> str:
    return "".join(ch for ch in text if ch == "\t" or not (ord(ch) < 32 or ord(ch) == 127))


def _parse_occurred_at(raw: str) -> datetime | None:
    """Best-effort timestamp extraction from a JSON payload. Never fatal."""
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in _TIMESTAMP_KEYS:
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _invalid(text: str, reason: str) -> Invalid:
    redacted = redact(text[:_MAX_INVALID_SNIPPET]).text
    return Invalid(raw=redacted, reason=reason)


def normalize(
    raw_bytes: bytes,
    resolver: AliasResolver,
    *,
    max_payload_bytes: int,
) -> NormalizeResult:
    if len(raw_bytes) > max_payload_bytes:
        return Invalid(
            raw="", reason=f"payload too large: {len(raw_bytes)} > {max_payload_bytes}"
        )

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return Invalid(raw="", reason="payload is not valid UTF-8")

    try:
        record = RawRecord.model_validate_json(text)
    except ValidationError as exc:
        return _invalid(text, f"raw envelope invalid: {exc.error_count()} error(s)")

    # Envelope metadata comes only from the RawRecord (i.e. from static Vector
    # source config). Content of `raw` never influences it.
    clean_raw = _strip_control_chars(record.raw)
    redacted_raw = redact(clean_raw).text
    record = record.model_copy(update={"raw": redacted_raw})

    try:
        asset_id = resolver.resolve_alias(record.lab_id, record.source_alias)
    except NotFound:
        return Unmapped(record=record, reason="alias not found")
    except AmbiguousAlias:
        return Unmapped(record=record, reason="alias ambiguous")

    event = Event(
        # Identity is derived from the pre-redaction content so the id is
        # stable even if the redactor evolves.
        event_id=deterministic_event_id(
            record.lab_id, record.source_alias, record.observed_at, clean_raw
        ),
        lab_id=record.lab_id,
        asset_id=asset_id,
        source_alias=record.source_alias,
        source_type=record.source_type,
        occurred_at=_parse_occurred_at(clean_raw),
        received_at=record.observed_at,
        payload=redacted_raw,
    )
    return Normalized(event=event)
