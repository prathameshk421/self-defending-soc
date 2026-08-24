import json
from pathlib import Path

import pytest

from estate.loader import load_inventory
from estate.query import Estate

from ingest.normalizer import Invalid, Normalized, Unmapped, normalize
from tests.ingest.conftest import INVENTORY_PATH, FakeResolver, make_raw_record

MAX_BYTES = 262144


def _normalize(record, resolver, max_payload_bytes=MAX_BYTES):
    return normalize(
        record.model_dump_json().encode("utf-8"),
        resolver,
        max_payload_bytes=max_payload_bytes,
    )


def test_known_alias_normalized(resolver):
    result = _normalize(make_raw_record(), resolver)
    assert isinstance(result, Normalized)
    assert result.event.asset_id == "asset-shop"
    assert result.event.payload == "GET /index.html 200"
    assert result.event.received_at == make_raw_record().observed_at


def test_unknown_alias_unmapped(resolver):
    result = _normalize(make_raw_record(source_alias="ghost-service"), resolver)
    assert isinstance(result, Unmapped)
    assert result.reason == "alias not found"
    assert result.record.source_alias == "ghost-service"


def test_ambiguous_alias_unmapped(resolver):
    result = _normalize(make_raw_record(source_alias="dup-alias"), resolver)
    assert isinstance(result, Unmapped)
    assert result.reason == "alias ambiguous"


def test_oversized_payload_invalid(resolver):
    record = make_raw_record(raw="x" * 1000)
    result = _normalize(record, resolver, max_payload_bytes=100)
    assert isinstance(result, Invalid)
    assert "too large" in result.reason


def test_non_utf8_invalid(resolver):
    result = normalize(b"\xff\xfe\xfd", resolver, max_payload_bytes=MAX_BYTES)
    assert isinstance(result, Invalid)
    assert "UTF-8" in result.reason


def test_garbage_json_invalid(resolver):
    result = normalize(b"not json at all", resolver, max_payload_bytes=MAX_BYTES)
    assert isinstance(result, Invalid)


def test_control_chars_stripped(resolver):
    record = make_raw_record(raw="line one\x00\x1b[31m evil \rline")
    result = _normalize(record, resolver)
    assert isinstance(result, Normalized)
    assert "\x00" not in result.event.payload
    assert "\x1b" not in result.event.payload
    assert "\r" not in result.event.payload


def test_payload_cannot_spoof_envelope(resolver):
    """A payload claiming to be another asset must not change attribution."""
    spoof = json.dumps({"source_alias": "lab-idp", "asset_id": "asset-idp", "msg": "hi"})
    record = make_raw_record(source_alias="lab-shop", raw=spoof)
    result = _normalize(record, resolver)
    assert isinstance(result, Normalized)
    assert result.event.source_alias == "lab-shop"
    assert result.event.asset_id == "asset-shop"


def test_extra_envelope_field_is_invalid(resolver):
    """A forged raw envelope with extra fields (e.g. asset_id) is rejected."""
    record = make_raw_record()
    payload = json.loads(record.model_dump_json())
    payload["asset_id"] = "asset-idp"
    result = normalize(
        json.dumps(payload).encode("utf-8"), resolver, max_payload_bytes=MAX_BYTES
    )
    assert isinstance(result, Invalid)


def test_occurred_at_parsed_from_json_payload(resolver):
    raw = json.dumps({"timestamp": "2026-08-23T10:30:00+00:00", "msg": "login"})
    result = _normalize(make_raw_record(raw=raw), resolver)
    assert isinstance(result, Normalized)
    assert result.event.occurred_at is not None
    assert result.event.occurred_at.hour == 10


def test_bad_timestamp_not_fatal(resolver):
    raw = json.dumps({"timestamp": "not-a-time", "msg": "login"})
    result = _normalize(make_raw_record(raw=raw), resolver)
    assert isinstance(result, Normalized)
    assert result.event.occurred_at is None


def test_secrets_redacted_in_unmapped(resolver):
    record = make_raw_record(
        source_alias="ghost-service", raw='attempt password="topsecretvalue"'
    )
    result = _normalize(record, resolver)
    assert isinstance(result, Unmapped)
    assert "topsecretvalue" not in result.record.raw


def test_against_real_estate_seed_inventory():
    estate = Estate(load_inventory(INVENTORY_PATH))
    result = _normalize(make_raw_record(source_alias="shop.lab.local"), estate)
    assert isinstance(result, Normalized)
    assert result.event.asset_id == "11111111-1111-4111-8111-111111111102"


ENDPOINT_ID = "11111111-1111-4111-8111-111111111107"
ENDPOINT_DIR = Path(__file__).resolve().parent / "testdata" / "endpoint"


def _estate():
    return Estate(load_inventory(INVENTORY_PATH))


def _lines(name: str):
    return (ENDPOINT_DIR / name).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "name", ["syslog.jsonl", "udev.jsonl", "process.jsonl", "audit.jsonl"]
)
def test_endpoint_goldens_map_to_lab_host(name):
    estate = _estate()
    for line in _lines(name):
        result = _normalize(
            make_raw_record(source_alias="lab-endpoint", raw=line), estate
        )
        assert isinstance(result, Normalized)
        assert result.event.asset_id == ENDPOINT_ID
        assert result.event.source_alias == "lab-endpoint"


def test_endpoint_redacts_bearer_and_ignores_spoof():
    estate = _estate()
    for name in ("syslog.jsonl", "process.jsonl", "audit.jsonl"):
        for line in _lines(name):
            result = _normalize(
                make_raw_record(source_alias="lab-endpoint", raw=line), estate
            )
            assert isinstance(result, Normalized)
            assert "eyJhbGciOi.fake.token" not in result.event.payload
            if "soc-api" in line:
                assert result.event.source_alias == "lab-endpoint"
                assert "[REDACTED]" in result.event.payload or "soc-api" in result.event.payload


def test_unknown_lab_endpoint_shadow_unmapped():
    estate = _estate()
    result = _normalize(
        make_raw_record(source_alias="lab-endpoint-shadow", raw="{}"), estate
    )
    assert isinstance(result, Unmapped)
