from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ingest.models import EVENT_SCHEMA_VERSION, Event, RawRecord

AWARE = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


def _record(**overrides):
    fields = dict(
        lab_id="default",
        source_alias="lab-shop",
        source_type="file",
        collector="vector",
        raw="a line",
        observed_at=AWARE,
    )
    fields.update(overrides)
    return RawRecord(**fields)


def test_raw_record_valid():
    record = _record()
    assert record.source_alias == "lab-shop"


def test_raw_record_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        _record(observed_at=datetime(2026, 8, 23, 12, 0, 0))


def test_raw_record_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        RawRecord(
            lab_id="default",
            source_alias="lab-shop",
            source_type="file",
            collector="vector",
            raw="x",
            observed_at=AWARE,
            asset_id="smuggled",
        )


def test_raw_record_rejects_unknown_source_type():
    with pytest.raises(ValidationError):
        _record(source_type="carrier_pigeon")


def test_raw_record_is_frozen():
    record = _record()
    with pytest.raises(ValidationError):
        record.source_alias = "lab-idp"


def test_event_defaults_schema_version():
    event = Event(
        event_id="e-1",
        lab_id="default",
        asset_id="asset-shop",
        source_alias="lab-shop",
        source_type="file",
        received_at=AWARE,
        payload="a line",
    )
    assert event.schema_version == EVENT_SCHEMA_VERSION
    assert event.occurred_at is None
