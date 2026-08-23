"""Remap allowlisted journald JSON objects into syslog.log lines.

Copied onto the guest by cloud-init. Tests load this file via SourceFileLoader
as lab_endpoint_journal_map. Ingest and Estate must not import it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

IDENTIFIERS = frozenset(
    {
        "kernel",
        "sudo",
        "sshd",
        "systemd-logind",
        "systemd-udevd",
        "CRON",
    }
)
UNITS = frozenset(
    {
        "ssh.service",
        "cron.service",
        "systemd-logind.service",
        "systemd-udevd.service",
    }
)
MESSAGE_MAX_BYTES = 16384


def _parse_int(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _message(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(x, int) for x in value):
        return bytes(value).decode("utf-8", errors="replace")
    return None


def _truncate(message: str) -> str:
    raw = message.encode("utf-8")
    if len(raw) <= MESSAGE_MAX_BYTES:
        return message
    cut = raw[:MESSAGE_MAX_BYTES].decode("utf-8", errors="ignore")
    return cut + "..."


def keep_journal_record(obj: dict) -> dict | None:
    """Return syslog-shape dict or None if dropped."""
    if not isinstance(obj, dict):
        return None
    priority = _parse_int(obj.get("PRIORITY"))
    if priority is None or priority < 0 or priority > 6:
        return None
    message = _message(obj.get("MESSAGE"))
    if message is None:
        return None
    ident = obj.get("SYSLOG_IDENTIFIER")
    unit = obj.get("_SYSTEMD_UNIT")
    ident_ok = isinstance(ident, str) and ident in IDENTIFIERS
    unit_ok = isinstance(unit, str) and unit in UNITS
    if not ident_ok and not unit_ok:
        return None
    ts_raw = _parse_int(obj.get("__REALTIME_TIMESTAMP"))
    if ts_raw is None:
        return None
    timestamp = datetime.fromtimestamp(
        ts_raw / 1_000_000, tz=timezone.utc
    ).isoformat(timespec="microseconds")
    out = {
        "timestamp": timestamp,
        "source": "journal",
        "priority": priority,
        "identifier": ident if isinstance(ident, str) else "unknown",
        "message": _truncate(message),
    }
    if isinstance(unit, str):
        out["unit"] = unit
    pid = _parse_int(obj.get("_PID"))
    if pid is not None:
        out["pid"] = pid
    return out


def format_syslog_line(mapped: dict) -> str:
    """One JSON object, no extra keys, newline-terminated."""
    return json.dumps(mapped, ensure_ascii=False, separators=(",", ":")) + "\n"
