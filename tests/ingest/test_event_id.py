import uuid
from datetime import datetime, timezone

from ingest.models import deterministic_event_id

TS = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


def test_same_inputs_same_id():
    a = deterministic_event_id("default", "lab-shop", TS, "GET / 200")
    b = deterministic_event_id("default", "lab-shop", TS, "GET / 200")
    assert a == b


def test_distinct_inputs_distinct_ids():
    base = deterministic_event_id("default", "lab-shop", TS, "GET / 200")
    assert base != deterministic_event_id("default", "lab-idp", TS, "GET / 200")
    assert base != deterministic_event_id("default", "lab-shop", TS, "GET / 500")
    assert base != deterministic_event_id(
        "default", "lab-shop", datetime(2026, 8, 23, 12, 0, 1, tzinfo=timezone.utc), "GET / 200"
    )


def test_id_is_valid_uuid():
    value = deterministic_event_id("default", "lab-shop", TS, "GET / 200")
    assert uuid.UUID(value).version == 5
