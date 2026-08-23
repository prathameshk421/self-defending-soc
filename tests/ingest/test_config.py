import pytest

from ingest.config import DEFAULT_INVENTORY, load_config
from ingest.errors import ConfigInvalid

MINIMAL = {
    "INGEST_BOOTSTRAP": "kafka:9092",
    "INGEST_REGISTRY_URL": "http://karapace:8081",
}


def test_minimal_env_with_defaults():
    config = load_config(MINIMAL)
    assert config.bootstrap == "kafka:9092"
    assert config.group_id == "ingest-normalizer"
    assert config.lab_id == "default"
    assert config.max_payload_bytes == 262144
    assert config.inventory_path == DEFAULT_INVENTORY
    assert config.sasl_username is None


def test_overrides_applied():
    config = load_config(
        {
            **MINIMAL,
            "INGEST_GROUP_ID": "ingest-replay",
            "INGEST_SASL_USERNAME": "ingest",
            "INGEST_SASL_PASSWORD": "pw",
            "INGEST_LAB_ID": "lab-2",
            "INGEST_MAX_PAYLOAD_BYTES": "1024",
        }
    )
    assert config.group_id == "ingest-replay"
    assert config.sasl_username == "ingest"
    assert config.lab_id == "lab-2"
    assert config.max_payload_bytes == 1024


def test_missing_bootstrap_fails_closed():
    with pytest.raises(ConfigInvalid, match="INGEST_BOOTSTRAP"):
        load_config({"INGEST_REGISTRY_URL": "http://karapace:8081"})


def test_missing_registry_fails_closed():
    with pytest.raises(ConfigInvalid, match="INGEST_REGISTRY_URL"):
        load_config({"INGEST_BOOTSTRAP": "kafka:9092"})


def test_blank_required_value_fails_closed():
    with pytest.raises(ConfigInvalid):
        load_config({**MINIMAL, "INGEST_BOOTSTRAP": "   "})


def test_non_integer_max_payload_fails_closed():
    with pytest.raises(ConfigInvalid):
        load_config({**MINIMAL, "INGEST_MAX_PAYLOAD_BYTES": "lots"})


def test_negative_max_payload_fails_closed():
    with pytest.raises(ConfigInvalid):
        load_config({**MINIMAL, "INGEST_MAX_PAYLOAD_BYTES": "-1"})
