"""Load guest journal_map.py via SourceFileLoader — ingest/estate do not import it."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPER_PATH = REPO_ROOT / "infra" / "endpoint" / "guest" / "journal_map.py"
TS_IN = "1690000000000000"
TS_OUT = "2023-07-22T04:26:40.000000+00:00"


def _load_mapper():
    loader = importlib.machinery.SourceFileLoader(
        "lab_endpoint_journal_map", str(MAPPER_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_mapper_file_exists():
    assert MAPPER_PATH.is_file()


@pytest.fixture(scope="module")
def jm():
    return _load_mapper()


def _base(**overrides):
    rec = {
        "PRIORITY": "6",
        "SYSLOG_IDENTIFIER": "sshd",
        "_SYSTEMD_UNIT": "ssh.service",
        "MESSAGE": "hello",
        "__REALTIME_TIMESTAMP": TS_IN,
        "_PID": "4242",
    }
    rec.update(overrides)
    return rec


def test_keep_priority_string_and_int(jm):
    for pri in ("6", 6):
        out = jm.keep_journal_record(_base(PRIORITY=pri))
        assert out is not None
        assert out["priority"] == 6
        assert out["source"] == "journal"
        assert out["identifier"] == "sshd"
        assert out["unit"] == "ssh.service"
        assert out["pid"] == 4242
        assert out["timestamp"] == TS_OUT


def test_keep_kernel_no_unit(jm):
    rec = _base(SYSLOG_IDENTIFIER="kernel")
    rec.pop("_SYSTEMD_UNIT")
    out = jm.keep_journal_record(rec)
    assert out is not None
    assert out["identifier"] == "kernel"
    assert "unit" not in out


def test_keep_via_unit_only_unknown_identifier(jm):
    rec = _base()
    rec.pop("SYSLOG_IDENTIFIER")
    out = jm.keep_journal_record(rec)
    assert out is not None
    assert out["identifier"] == "unknown"
    assert out["unit"] == "ssh.service"


def test_drop_unrelated_identifier_and_unit(jm):
    assert (
        jm.keep_journal_record(
            _base(SYSLOG_IDENTIFIER="python3", _SYSTEMD_UNIT="unrelated.service")
        )
        is None
    )


def test_drop_priority_7_string_and_int(jm):
    assert jm.keep_journal_record(_base(PRIORITY="7")) is None
    assert jm.keep_journal_record(_base(PRIORITY=7)) is None


def test_drop_missing_and_non_numeric_priority(jm):
    rec = _base()
    rec.pop("PRIORITY")
    assert jm.keep_journal_record(rec) is None
    assert jm.keep_journal_record(_base(PRIORITY="info")) is None


def test_drop_missing_message(jm):
    rec = _base()
    rec.pop("MESSAGE")
    assert jm.keep_journal_record(rec) is None


def test_keep_empty_string_message(jm):
    out = jm.keep_journal_record(_base(MESSAGE=""))
    assert out is not None
    assert out["message"] == ""


def test_message_byte_array(jm):
    out = jm.keep_journal_record(_base(MESSAGE=[115, 115, 104]))
    assert out is not None
    assert out["message"] == "ssh"


def test_coredump_key_not_in_output(jm):
    out = jm.keep_journal_record(_base(COREDUMP="blob"))
    assert out is not None
    assert "COREDUMP" not in out
    assert set(out) <= {
        "timestamp",
        "source",
        "priority",
        "identifier",
        "message",
        "unit",
        "pid",
    }


def test_truncate_long_message(jm):
    long_msg = "x" * 20000
    out = jm.keep_journal_record(_base(MESSAGE=long_msg))
    assert out is not None
    assert out["message"].endswith("...")
    assert len(out["message"].encode("utf-8")) <= 16387


def test_format_syslog_line(jm):
    mapped = jm.keep_journal_record(_base())
    line = jm.format_syslog_line(mapped)
    assert line.endswith("\n")
    assert line.count("\n") == 1
    obj = json.loads(line)
    assert obj == mapped
    assert "\\u" not in line  # ensure_ascii=False for ascii payload
