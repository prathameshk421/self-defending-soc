"""Vector endpoint sources: structure, not substring search."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR_YAML = REPO_ROOT / "infra" / "vector" / "vector.yaml"

EXISTING_INPUTS = [
    "wrap_lab_shop",
    "wrap_lab_idp",
    "wrap_lab_wallet",
    "wrap_soc_api",
    "wrap_webhooks",
    "wrap_redteam",
]
NEW_REMAPS = [
    ("file_lab_endpoint_syslog", "wrap_lab_endpoint_syslog", "/var/log/lab/lab-endpoint/syslog.log"),
    ("file_lab_endpoint_udev", "wrap_lab_endpoint_udev", "/var/log/lab/lab-endpoint/udev.log"),
    ("file_lab_endpoint_process", "wrap_lab_endpoint_process", "/var/log/lab/lab-endpoint/process.log"),
]


def _cfg() -> dict:
    return yaml.safe_load(VECTOR_YAML.read_text(encoding="utf-8"))


def test_kafka_sink_keeps_existing_and_appends_endpoint_remaps():
    inputs = _cfg()["sinks"]["kafka_raw"]["inputs"]
    for name in EXISTING_INPUTS:
        assert name in inputs
    for _, remap, _ in NEW_REMAPS:
        assert remap in inputs


def test_endpoint_sources_and_remaps():
    cfg = _cfg()
    for source_id, remap_id, include in NEW_REMAPS:
        src = cfg["sources"][source_id]
        assert src["type"] == "file"
        assert src["include"] == [include]
        assert src["max_line_bytes"] == 65536
        assert src["ignore_not_found"] is True
        remap = cfg["transforms"][remap_id]
        assert remap["inputs"] == [source_id]
        text = remap["source"]
        assert '"source_alias": "lab-endpoint"' in text
        assert '"source_type": "file"' in text
        assert '"collector": "vector"' in text
