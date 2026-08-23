"""Envelope models for the ingest pipeline.

RawRecord is what Vector produces onto soc.raw.v1. Event is what the
normalizer produces onto soc.events.v1. Both are frozen and reject unknown
fields so payload content can never smuggle extra envelope metadata.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel

EVENT_SCHEMA_VERSION = 1

# Fixed namespace for deterministic event ids. Reprocessing the same raw
# record must yield the same event_id so downstream consumers can dedup
# under at-least-once delivery.
EVENT_ID_NAMESPACE = uuid.UUID("6f1f9f76-7c2a-4a3e-9a55-0f4de11f4f2a")

TOPIC_RAW = "soc.raw.v1"
TOPIC_EVENTS = "soc.events.v1"
TOPIC_UNMAPPED = "soc.ingest.unmapped.v1"
TOPIC_DLQ = "soc.ingest.dlq.v1"


class RawRecord(BaseModel):
    """Provenance-locked raw envelope built by Vector.

    source_alias comes from static Vector source configuration (file path or
    authenticated HTTP listener), never from record content.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    lab_id: str
    source_alias: str
    source_type: Literal["file", "webhook"]
    collector: str
    raw: str
    observed_at: AwareDatetime


class Event(BaseModel):
    """Normalized, asset-mapped, redacted event."""

    model_config = {"frozen": True, "extra": "forbid"}

    event_id: str
    lab_id: str
    asset_id: str
    source_alias: str
    source_type: str
    occurred_at: Optional[AwareDatetime] = None
    received_at: AwareDatetime
    payload: str
    schema_version: int = EVENT_SCHEMA_VERSION


def deterministic_event_id(
    lab_id: str, source_alias: str, observed_at: datetime, raw: str
) -> str:
    """UUIDv5 over a content hash: identical raw records map to identical ids."""
    digest = hashlib.sha256(
        "|".join((lab_id, source_alias, observed_at.isoformat(), raw)).encode("utf-8")
    ).hexdigest()
    return str(uuid.uuid5(EVENT_ID_NAMESPACE, digest))
