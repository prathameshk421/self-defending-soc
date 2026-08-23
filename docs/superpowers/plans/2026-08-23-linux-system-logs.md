# Linux lab system logs (journal + USB helper) — implementation plan

> **Status: Council-approved.** A draft was critiqued by five seats (ambiguity, cybersecurity, coding, system design, scalability). The judge required two splices (UTC timestamp `04:26:40`, single newline from `format_syslog_line`); both are in this file. Do not implement from an older draft.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Supersedes:** [`2026-08-23-linux-endpoint-telemetry.md`](2026-08-23-linux-endpoint-telemetry.md). Task 0 banners that file. Do not implement it.

**Goal:** Catalog one Linux lab host (`lab-endpoint`) and feed the existing ingest pipe three guest-authored JSON line files: allowlisted journal remap (`syslog.log`), USB device lines (`udev.log`), USB helper file/exec lines (`process.log`). CI proves mapping with goldens. QEMU + virtual USB is operator-only.

**Architecture:** Estate adds `lab_host`. Vector tails three **file** binds (inode-pinned), remaps each as `RawRecord` `source_type=file`, `source_alias=lab-endpoint`. Ingest does not parse host events. Optional QEMU guest writes only `infra/endpoint/logs` over virtio-9p. Guest `lab-journal-forward` remaps journald through `journal_map.py`. USB `lab-usb-ingest` logs device/file/process and execs a **copy** of stick bytes as root (autorun demo, not USB defense).

**Tech Stack:** Existing Estate, Ingest, Vector, Kafka, pytest. Operator-only: QEMU, pinned Debian 12 cloud image, udev, systemd, VFAT stick image. No Sysmon, auditd, Falco, osquery.

**This plan is Linux only.**

## Global Constraints

- Linux guests and Linux sensors only. Agent docs stay Linux-only.
- Operator workstation is not an asset, not a log source, not a red-team target, not a respond target.
- `ExecutionRealm` stays `{lab}` only.
- Estate stays a catalog. No execute methods in `src/estate/`.
- `RawRecord.source_type` stays `file | webhook`. Host logs are files.
- `LogSource.kind` stays `str`. Inventory uses `file`. No `syslog`/`process`/`device` enum.
- No Event / Karapace schema bump. Payload stays opaque and **untrusted**.
- No Sysmon, auditd, Falco, osquery. OS-wide exec/file is slice C (later).
- Detect is out. Kafka order is not causality.
- Respond/Recover execution are out. Asset is **watch-only**.
- No `in_scope_red_team` / `assert_red_team_target` on this host.
- No `docker.sock`, no host `$HOME` bind, no `network_mode: host`, no privileged SOC service, no guest NIC (`-nic none`).
- No malware samples. USB image is a benign marker that writes `/tmp/lab-usb-ok`.
- Inventory secrets stay `env:` refs.
- Do not implement the USB-only plan in parallel. One host, one log dir, one alias.
- No `or` / `prefer` / `fallback` in this document. One algorithm each.

---

## Log-type roadmap

Application HTTP logs are **not** network telemetry.

| Slice | Name | Signals | Status |
|---|---|---|---|
| A | Application logs | shop access, idp auth, wallet app, soc-api access, two webhooks | Done |
| B | **This plan** | Allowlisted journal remap + USB helper device/file/exec | This file |
| C | Host process/file audit | OS-wide exec/file (auditd or equivalent) | Later |
| D | Network telemetry | Firewall/flow/DNS/pcap; any guest NIC | Later |
| E | Detect / Respond / Red team on the host | Rules, isolation, in-scope USB attacks | Later |

USB is a **story inside B**, not a second asset.

**Named non-goals (not “we’ll see”):** live sshd/sudo-over-network; guest NIC including “just enough for ssh”; `lab-net`; Event `log_source_id` / schema bump; Vector `journald` source; generating Vector from Estate locators; second writer on `process.log`; expanding the journal allowlist; log rotation implemented by a new sensor cron; Detect USB-story rules.

---

## Trust model (locked)

All three files are **guest-authored self-report**. A compromised guest (or `logger -t sshd`) can write whatever it wants onto the 9p share. The journal allowlist is a **volume/noise filter for the honest forwarder**, not authenticity.

- Envelope provenance (Vector hardcoded `lab-endpoint`) still holds.
- Payload `identifier` / `unit` / `action` is **not** proof of origin.
- `process.log` `process_create` means “helper intended to exec,” not “kernel observed a process.”
- Copied stick bytes **do run as root**. This slice is an autorun demo, not USB defense. Layer 7 must disable/gate this helper before in-scope USB attacks. `attach-usb.sh` stays operator-only.

---

## What this builds

```
infra/endpoint/logs/{syslog,udev,process}.log   (host files; gitignored bodies)
        │
        │ compose: three file binds, read-only in Vector
        ▼
Vector  /var/log/lab/lab-endpoint/*.log
source_alias hardcoded "lab-endpoint"
        │
        ▼
Kafka soc.raw.v1 → ingest → Event
asset_id = 11111111-1111-4111-8111-111111111107
```

Operator-only:

```
QEMU Debian 12, -nic none, qcow max 8G
  lab-journal-forward → syslog.log (cursor on guest disk)
  lab-usb-ingest     → udev.log + process.log
  virtio-9p          → infra/endpoint/logs only
  unix monitor       → attach-usb.sh
```

---

## What “done” means

**Merge (CI, Tasks 0–5):** items 1–12. No QEMU.

1. USB-only plan file has a superseded banner (Task 0).
2. Inventory loads `lab-endpoint` as `lab_host`.
3. `resolve_alias("default", "lab-endpoint")` == `11111111-1111-4111-8111-111111111107`.
4. Three log_source ids: `endpoint-syslog`, `endpoint-udev`, `endpoint-process`.
5. Goldens (syslog 5 lines, udev 2, process 2) wrap as `RawRecord` `source_alias=lab-endpoint` and normalize to that UUID.
6. Spoof substrings `"source_alias":"soc-api"` do not change envelope alias.
7. `Authorization: Bearer eyJhbGciOi.fake.token` in syslog `message` and process `command_line` becomes `[REDACTED]`.
8. Vector YAML: three sources, three remaps, existing six sink inputs **kept**, three new remaps **appended**, `max_line_bytes: 65536`, `ignore_not_found: true`.
9. Compose binds the **three files** (not the directory). No `docker.sock` / `privileged` / `network_mode: host`.
10. `journal_map.py` keep/drop/truncate/timestamp tests pass (string **and** int PRIORITY).
11. `lab_host` with empty `log_sources` → `InventoryInvalid` with text `empty log_sources`.
12. `assert_respond_target` on the host UUID raises `RespondForbidden`.

**Operator (Task 6, not a merge gate for 0–5):**

13. `run-vm.sh` boots pinned dated image + sha256, 9p-exports **only** `infra/endpoint/logs`, `-nic none`, overlay ≤ 8G.
14. After boot, honest forwarder may append kernel/udevd lines. It will **miss** pre-start journal (`-n 0` / cursor). That is accepted. Do not add a NIC to make sshd goldens “live.”
15. `build-stick.sh` / `attach-usb.sh` / helper produce udev + process lines.
16. Hand-confirm Events. CI does not.

---

## Locked paths

| Role | Path |
|---|---|
| Host log dir | `infra/endpoint/logs/` |
| Host files (gitignored) | `syslog.log`, `udev.log`, `process.log` (+ `*.log.1`) |
| Vector container | `/var/log/lab/lab-endpoint/{syslog,udev,process}.log` |
| Guest 9p mount | `/var/log/lab-endpoint` |
| Estate locators | `/var/log/lab-endpoint/{syslog,udev,process}.log` |
| Guest cursor (qcow, **not** 9p) | `/var/lib/lab-endpoint/journal.cursor` |
| QEMU monitor | `infra/endpoint/run/monitor.sock` |
| USB image | `infra/endpoint/run/lab-stick.img` |
| Mapper | `infra/endpoint/guest/journal_map.py` |
| Forwarder wrapper | `infra/endpoint/guest/lab-journal-forward` |
| USB helper | `infra/endpoint/guest/lab-usb-ingest` |
| udev rules | `infra/endpoint/guest/99-lab-usb.rules` |
| Forwarder unit | `infra/endpoint/guest/lab-journal-forward.service` |

Estate locators are in-guest paths. Do not generate Vector from Estate.

`.gitignore` in `infra/endpoint/logs/`: `*.log` and `*.log.1`. Commit `.gitkeep` only. `run-vm.sh` and tests `touch` three **regular** empty files if missing (Docker file binds fail or become directories if the host path is absent).

---

## Locked JSON shapes

Writers use key `timestamp` only (RFC3339, `+00:00`, microseconds). `normalize` already reads `@timestamp`/`timestamp`/`time`/`ts`.

One JSON object per line. No pretty-print. No extra keys. Newlines escaped.

### syslog.log (honest forwarder)

Keep lines:

```json
{"timestamp":"2026-08-23T00:00:00.000000+00:00","source":"journal","priority":6,"identifier":"sshd","unit":"ssh.service","message":"Failed password for invalid user x from 10.0.0.1 port 22 ssh2"}
```

| Key | Required | Rule |
|---|---|---|
| `timestamp` | yes | RFC3339 from `__REALTIME_TIMESTAMP` µs since epoch, UTC, `timespec="microseconds"`, offset `+00:00`, no `Z` |
| `source` | yes | `"journal"` |
| `identifier` | yes | `SYSLOG_IDENTIFIER` if `str`, else `"unknown"` |
| `message` | yes | string; see truncate |
| `priority` | yes on keep | int 0–6 |
| `unit` | no | omit if `_SYSTEMD_UNIT` is not a `str` |
| `pid` | no | omit if `_PID` does not parse as int |

Drop-notice lines (rate/disk; **not** passed through `keep_journal_record`):

```json
{"timestamp":"<now RFC3339 microseconds +00:00>","source":"journal","identifier":"lab-journal-forward","message":"dropped 12 lines (rate limit)"}
```

`message` is exactly `dropped <N> lines (rate limit)` or `dropped <N> lines (disk cap)`. At most one such line per second.

### udev.log

```json
{"timestamp":"2026-08-23T00:00:00.000000+00:00","source":"usb-helper","action":"add","devtype":"disk","devname":"/dev/sdb"}
```

Remove uses `"action":"remove"`. No `ID_SERIAL`.

### process.log

```json
{"timestamp":"2026-08-23T00:00:00.000000+00:00","source":"usb-helper","action":"file_create","path":"/tmp/lab-usb-marker"}
{"timestamp":"2026-08-23T00:00:00.000000+00:00","source":"usb-helper","action":"process_create","image":"/tmp/lab-usb-marker","command_line":"/tmp/lab-usb-marker"}
```

`source: usb-helper` is the producer tag so slice C `file_create` later cannot be confused with helper confession. Marker success file is `/tmp/lab-usb-ok` (not the copy path).

Every string field on udev/process lines: same 16384 UTF-8 byte cap as syslog `message` (cut on codepoint boundary, then append `...`).

---

## Journal mapper algorithm (one implementation)

File: `infra/endpoint/guest/journal_map.py`.

Tests load it with `importlib.machinery.SourceFileLoader` + `spec_from_loader` / `module_from_spec`. Module name: `lab_endpoint_journal_map`. No `sys.path`. No `src/` copy. Ingest and Estate do not import it. No second allowlist table.

```python
IDENTIFIERS = frozenset({
    "kernel", "sudo", "sshd", "systemd-logind", "systemd-udevd", "CRON",
})
UNITS = frozenset({
    "ssh.service", "cron.service",
    "systemd-logind.service", "systemd-udevd.service",
})
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
        return value  # empty string keeps
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
    return json.dumps(mapped, ensure_ascii=False, separators=(",", ":")) + "\n"
```

Fixture lock: `__REALTIME_TIMESTAMP` `"1690000000000000"` → `timestamp` exactly `2023-07-22T04:26:40.000000+00:00` (`datetime.fromtimestamp(ts_raw / 1_000_000, tz=timezone.utc)` in UTC; do not use a local zone to recover `00:26:40`).

Truncate test: `endswith("...")` and `len(message.encode("utf-8")) <= 16387`.

---

## Vector and compose

### Vector sources (exact)

Each of `file_lab_endpoint_syslog`, `file_lab_endpoint_udev`, `file_lab_endpoint_process`:

```yaml
    type: file
    include: ["/var/log/lab/lab-endpoint/syslog.log"]  # udev.log / process.log
    max_line_bytes: 65536
    ignore_not_found: true
```

Do not set `read_from: end`. Do not set `ignore_checkpoints` / `remove_after`.

Remaps `wrap_lab_endpoint_{syslog,udev,process}`: rebuild RawRecord; `source_alias: "lab-endpoint"`; `source_type: "file"`; `collector: "vector"`; `inputs` is a one-element YAML list equal to the matching source id (same shape as `wrap_lab_shop`).

`sinks.kafka_raw.inputs` **appends** the three remaps. Existing six remain: `wrap_lab_shop`, `wrap_lab_idp`, `wrap_lab_wallet`, `wrap_soc_api`, `wrap_webhooks`, `wrap_redteam`.

`max_line_bytes: 65536` is the Vector drop cap (oversize never reaches Kafka/DLQ). Writer JSON lines stay ≤ ~17 KiB. Ingest `INGEST_MAX_PAYLOAD_BYTES` 262144 stays as envelope guard. Do not set Vector to 262144 “to match ingest.”

### Compose vector volumes

Keep `lab-logs:/var/log/lab:ro`. **Do not** bind the directory `./endpoint/logs`. Bind three files:

```yaml
      - ./endpoint/logs/syslog.log:/var/log/lab/lab-endpoint/syslog.log:ro
      - ./endpoint/logs/udev.log:/var/log/lab/lab-endpoint/udev.log:ro
      - ./endpoint/logs/process.log:/var/log/lab/lab-endpoint/process.log:ro
```

This inode-pins Vector’s open of shop/api siblings against a guest symlink in the 9p dir. Guest can still poison `lab-endpoint` content. Guest cannot **write** shop/api files. Symlink-follow into siblings is out of spec.

`run-vm.sh` 9p-exports **only** `infra/endpoint/logs` (string-tested). Never `infra/endpoint` (would export helper source).

---

## Estate

`AssetKind.LAB_HOST = "lab_host"`. `SCHEMA_VERSION` stays 1.

Inventory row (all fields):

```yaml
  - asset_id: "11111111-1111-4111-8111-111111111107"
    lab_id: default
    kind: lab_host
    name: lab-endpoint
    owner: lab_app
    lifecycle: declared
    execution_realm: lab
    respond_allowed: false
    self_defense_class: watch_only
    owner_ref: lab-ops
    approval_policy_id: default-hitl
    exposure: loopback
    aliases: ["lab-endpoint"]
    log_sources:
      - id: endpoint-syslog
        kind: file
        locator: "/var/log/lab-endpoint/syslog.log"
      - id: endpoint-udev
        kind: file
        locator: "/var/log/lab-endpoint/udev.log"
      - id: endpoint-process
        kind: file
        locator: "/var/log/lab-endpoint/process.log"
    in_scope_red_team: false
    red_team_skip: true
```

No attack_surface, containment_handles, restore_handles, edges.

Loader: new `_validate_lab_host_log_sources` next to `_validate_red_team_surface`, called after `model_validate`. If `kind == lab_host` and `not asset.log_sources` → `InventoryInvalid(f"lab_host {asset.name!r} has empty log_sources")`. Omitted key and `[]` are the same. Do not apply this rule to other kinds (`lab-net` has no logs).

---

## USB / udev (operator helper)

### Rules file (exact two lines of match, both `RUN+=/usr/local/sbin/lab-usb-ingest`)

```
ACTION=="add", SUBSYSTEM=="block", DEVTYPE=="disk", ID_USB_DRIVER=="usb-storage", RUN+="/usr/local/sbin/lab-usb-ingest"
ACTION=="remove", SUBSYSTEM=="block", DEVTYPE=="disk", ENV{ID_BUS}=="usb", RUN+="/usr/local/sbin/lab-usb-ingest"
```

No systemd `Type=oneshot` on udev. udev waits for `RUN+=`. Do not widen to `uas`.

`$DEVNAME` must match `^/dev/[a-zA-Z0-9]+$` else exit 1 with no writes. No shell interpolation of other udev env into the mount command.

### Add path

1. Open `udev.log` with `O_NOFOLLOW`; refuse non-regular; append add JSON; one `fsync`.
2. `timeout 10 mount -t vfat -o ro,nosuid,nodev,noexec "$DEVNAME" /mnt/lab-stick`
3. On mount/copy failure: udev line already written; **no** process lines; exit 1.
4. `cp /mnt/lab-stick/lab-marker.sh /tmp/lab-usb-marker`
5. `umount /mnt/lab-stick`
6. `chmod 0755 /tmp/lab-usb-marker`
7. Append `file_create` then `process_create`; one `fsync` after the pair.
8. Exec `/tmp/lab-usb-marker` (the copy). **Copied stick bytes run as root.**

### Remove path

Write remove JSON only. Do not mount. Do not exec.

### Marker

```sh
#!/bin/sh
printf 'LAB_USB_MARKER_V1\n' > /tmp/lab-usb-ok
```

---

## Journal forwarder (Task 6)

Thin wrapper: read journalctl JSON → `keep_journal_record` → write `format_syslog_line(...)` **once**. That helper already ends with one `\n`. Do not write `format_syslog_line(...) + "\n"`. No second allowlist. Test reads `lab-journal-forward` as text and asserts it imports `keep_journal_record` and `format_syslog_line` from `journal_map`.

Open `syslog.log` with `O_NOFOLLOW`; refuse non-regular.

| Item | Lock |
|---|---|
| Cursor | `/var/lib/lab-endpoint/journal.cursor` on qcow, never 9p |
| First start (no cursor) | `journalctl -f -o json --no-pager -n 0` plus `--output-fields` below |
| Later starts | `--after-cursor="$(cat cursor)" -f -o json --no-pager` |
| Fields | `PRIORITY,SYSLOG_IDENTIFIER,_SYSTEMD_UNIT,MESSAGE,__REALTIME_TIMESTAMP,__CURSOR,_PID` |
| Parse cap | skip journalctl line `> 262144` bytes **before** `json.loads` |
| Persist order | complete syslog line → batch fsync log → write cursor → fsync cursor. Crash between log and cursor = one duplicate (OK). Opposite order forbidden |
| Fsync | every **32 keep-lines or 1.0 s**, never per line. One `write()` of `format_syslog_line` output (already newline-terminated). This wrapper must not add a second newline. |
| Rate | **20 keep-lines/s**; excess dropped; ≤1 drop-notice line/s |
| Rotate | at **8 MiB**; keep `syslog.log.1` only; rename + create + **reopen by path** (no copytruncate, no held fd across rename) |
| Dir cap | **32 MiB** across the 9p dir; then drop (disk cap notice) |
| Unit | Python is main PID; journalctl is child; default KillMode; `Restart=on-failure`; `RestartSec=2`; `StartLimitBurst=10`; `StartLimitIntervalSec=60` |
| Write error | sleep-and-retry in-process; do not tight-loop exit 1 |

udev/process files: same 8 MiB rotate + reopen by path, implemented in the helper.

`stop-vm.sh` sends monitor `quit` only. No qemu-guest-agent. No SSH. Per-write/batch fsync is the durability story.

Monitor dir `infra/endpoint/run` mode `0700`; socket `0600`. Scripts reject extra argv (`if [ -n "${1:-}" ]; then exit 2; fi`). No `-monitor tcp:`. Compose must not mount `monitor.sock`.

---

## Implementation tasks

### Task 0: Banner the USB-only plan

**Files:** `docs/superpowers/plans/2026-08-23-linux-endpoint-telemetry.md`

- [ ] Insert immediately under the title:

```markdown
> **SUPERSEDED** by [`2026-08-23-linux-system-logs.md`](2026-08-23-linux-system-logs.md).
> Do not implement this file. Same UUID `…107` / alias `lab-endpoint` / log dir would fork.
```

- [ ] Commit only that banner.

### Task 1: Estate `lab_host` + inventory

**Files:** `src/estate/models.py`, `src/estate/loader.py`, `inventory/default.yaml`, `tests/estate/test_lab_host.py`

- [ ] Write `tests/estate/test_lab_host.py`:

```python
from pathlib import Path

import pytest
import yaml

from estate.errors import InventoryInvalid, RespondForbidden
from estate.loader import load_inventory
from estate.query import Estate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = REPO_ROOT / "inventory" / "default.yaml"
HOST_ID = "11111111-1111-4111-8111-111111111107"


def test_default_inventory_lab_host():
    estate = Estate(load_inventory(DEFAULT_INVENTORY))
    host = estate.get(HOST_ID)
    assert host.kind.value == "lab_host"
    assert estate.resolve_alias("default", "lab-endpoint") == HOST_ID
    assert {s.id for s in host.log_sources} == {
        "endpoint-syslog",
        "endpoint-udev",
        "endpoint-process",
    }
    with pytest.raises(RespondForbidden):
        estate.assert_respond_target(HOST_ID)


def test_lab_host_empty_log_sources_invalid(tmp_path: Path):
    data = yaml.safe_load(DEFAULT_INVENTORY.read_text(encoding="utf-8"))
    data["assets"] = [
        a
        for a in data["assets"]
        if a["asset_id"] != HOST_ID
    ] + [
        {
            "asset_id": HOST_ID,
            "lab_id": "default",
            "kind": "lab_host",
            "name": "lab-endpoint",
            "owner": "lab_app",
            "lifecycle": "declared",
            "execution_realm": "lab",
            "respond_allowed": False,
            "self_defense_class": "watch_only",
            "owner_ref": "lab-ops",
            "approval_policy_id": "default-hitl",
            "exposure": "loopback",
            "aliases": ["lab-endpoint"],
            "log_sources": [],
            "in_scope_red_team": False,
            "red_team_skip": True,
        }
    ]
    path = tmp_path / "inv.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(InventoryInvalid, match="empty log_sources"):
        load_inventory(path)
```

- [ ] Run `pytest tests/estate/test_lab_host.py -v` — fail until enum/row/loader exist.
- [ ] Add `LAB_HOST`, inventory row, `_validate_lab_host_log_sources`.
- [ ] Run `pytest tests/estate/ -v` — pass (existing uniqueness tests must still pass).
- [ ] Commit estate-only.

### Task 2: Golden lines + ingest mapping

**Files:** `tests/ingest/testdata/endpoint/syslog.jsonl`, `udev.jsonl`, `process.jsonl`, `README.md`; `tests/ingest/test_normalizer.py`

Do **not** change `normalize`. Do **not** use the `resolver` fixture. Do **not** extend `FakeResolver`.

Goldens stay contract fixtures. Task 6 must not overwrite them.

`syslog.jsonl` — **five** lines, in order:

1. sshd failed-password shape (locked JSON above; fixture timestamp `2026-08-23T00:00:00.000000+00:00`).
2. sudo: `"identifier":"sudo","message":"pam_unix(sudo:session): session opened for user root(uid=0) by (uid=1000)"` plus required keys.
3. kernel: `"identifier":"kernel","message":"usb 1-1: new high-speed USB device"` plus required keys (`unit` omitted).
4. Bearer in `message`: `"message":"cmd Authorization: Bearer eyJhbGciOi.fake.token"` (Authorization rule redacts; do not assert exact rebuilt JSON; assert `"eyJhbGciOi.fake.token"` absent and `"[REDACTED]"` present).
5. Spoof **inside** `message` string only: `"message":"note \"source_alias\":\"soc-api\" ignored"`.

`udev.jsonl` — add + remove, both `"source":"usb-helper"`, `devname` `/dev/sdb`.

`process.jsonl` — **two** lines: `file_create`; `process_create` with

`command_line` exactly `/tmp/lab-usb-marker Authorization: Bearer eyJhbGciOi.fake.token "source_alias":"soc-api"`

- [ ] Write tests (append to `test_normalizer.py`). Add `import pytest` and `from pathlib import Path` at the top of that file if missing.

```python
ENDPOINT_ID = "11111111-1111-4111-8111-111111111107"
ENDPOINT_DIR = Path(__file__).resolve().parent / "testdata" / "endpoint"


def _estate():
    return Estate(load_inventory(INVENTORY_PATH))


def _lines(name: str):
    return (ENDPOINT_DIR / name).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("name", ["syslog.jsonl", "udev.jsonl", "process.jsonl"])
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
    for name in ("syslog.jsonl", "process.jsonl"):
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
```

- [ ] Run `pytest tests/ingest/test_normalizer.py -v` — pass after goldens exist (normalize already works).
- [ ] `README.md`: contract fixtures; not proof a guest ran; IdP `auth.log` is application identity; host `syslog.log` `identifier=sshd|sudo` is host OS auth.
- [ ] Commit.

### Task 3: `journal_map.py` + tests

**Files:** `infra/endpoint/guest/journal_map.py`, `tests/infra/test_journal_map.py`, `tests/infra/testdata/journal/*.json`

- [ ] Write `tests/infra/test_journal_map.py` that loads the module via `SourceFileLoader` from `REPO_ROOT / "infra/endpoint/guest/journal_map.py"` as `lab_endpoint_journal_map`.
- [ ] Cases:
  - keep `PRIORITY` `"6"` and `6` with identifier `sshd`
  - keep identifier `kernel`, no unit
  - keep via `_SYSTEMD_UNIT` `ssh.service` with `SYSLOG_IDENTIFIER` missing → output `identifier` `"unknown"`
  - drop identifier `python3` / unit `unrelated.service`
  - drop `PRIORITY` `"7"` and `7`
  - drop missing / non-numeric PRIORITY
  - drop missing MESSAGE
  - keep empty string MESSAGE
  - MESSAGE byte-array `[115,115,104]` → `"ssh"`
  - COREDUMP key in input must not appear in output
  - timestamp `"1690000000000000"` → `2023-07-22T04:26:40.000000+00:00`
  - truncate 20000-byte MESSAGE
  - `format_syslog_line` one object, `ensure_ascii=False`, one trailing `\n`, no extra keys
- [ ] Implement `journal_map.py` as specified.
- [ ] `pytest tests/infra/test_journal_map.py -v` — pass.
- [ ] Commit. This task is the **only** writer of `journal_map.py`.

### Task 4: Vector + compose + stubs + config tests (TDD)

**Files:** `tests/infra/test_vector_endpoint_sources.py`, `tests/infra/test_compose_safety.py`, then `infra/vector/vector.yaml`, `infra/compose.yaml`, `infra/endpoint/logs/.gitkeep`, `infra/endpoint/logs/.gitignore`, `docs/ingest-layer.md`

- [ ] Write failing tests first.

`test_vector_endpoint_sources.py` uses `yaml.safe_load`, not substring search:

- `sinks.kafka_raw.inputs` contains the original six **and** `wrap_lab_endpoint_syslog`, `wrap_lab_endpoint_udev`, `wrap_lab_endpoint_process`
- each remap `inputs` == `[matching source id]` (one-element list)
- each remap source text assigns `source_alias` `lab-endpoint`, `source_type` `file`, `collector` `vector`
- each of the three sources: exact `include` path, `max_line_bytes == 65536`, `ignore_not_found is True`

`test_compose_safety.py`:

- parse compose; `vector.volumes` contains the three **file** binds above
- `vector.volumes` does **not** contain `./endpoint/logs:` as a directory bind
- no volume source contains `docker.sock`; no `privileged`; no `network_mode: host`
- scan `infra/endpoint/*.sh` (when present) for `docker.sock` and `network_mode: host`; do not fail on those strings in comments
- no compose mount of `monitor.sock`

Also: tests `touch` `infra/endpoint/logs/{syslog,udev,process}.log` if missing and assert they are regular files (not dirs, not symlinks).

- [ ] Run tests — fail.
- [ ] Implement YAML + `.gitignore` (`*.log`, `*.log.1`) + `.gitkeep`.
- [ ] Add three rows to ingest-layer current-sources table: `file_lab_endpoint_{syslog,udev,process}`, file tail, alias `lab-endpoint`. Note: payload untrusted; IdP auth vs host syslog.
- [ ] `pytest tests/infra/ tests/ingest/ tests/estate/ -v` — pass.
- [ ] Commit.

### Task 5: Agent docs (Tasks 0–4 only)

- [ ] ChangeLog: `lab_host`, inventory, Vector tails, file binds, `journal_map.py` tests. **Do not** claim a guest forwarder/QEMU exists.
- [ ] Decisions: bind three files; 9p dir; JSON lines; no Sysmon/auditd; helper writes process.log with `source=usb-helper`; journal allowlist is volume filter; watch-only; goldens are fixtures; no Event schema change; this supersedes USB-only plan.
- [ ] Flow.md: Vector sources include the three endpoint files.
- [ ] Linux only on re-read.
- [ ] Commit.

### Task 6: Operator QEMU (optional merge)

**Files:** layout below. Checksums filled in `run-vm.sh` before this task merges. Tasks 0–5 do not fetch images. URL must be a dated `bookworm/YYYYMMDD-NNN/...` path (no `latest`) + literal sha256 **in the script**.

```
infra/endpoint/
  logs/.gitkeep
  logs/.gitignore
  run/.gitignore
  run-vm.sh
  stop-vm.sh
  attach-usb.sh
  detach-usb.sh
  usb/build-stick.sh
  usb/lab-marker.sh
  guest/cloud-init.yaml
  guest/99-lab-usb.rules
  guest/lab-usb-ingest
  guest/lab-journal-forward
  guest/lab-journal-forward.service
  guest/journal_map.py          # already from Task 3; do not fork
  README.md
```

- [ ] Implement guest wrapper + helper + scripts per locks above.
- [ ] Test: `lab-journal-forward` source contains `keep_journal_record` and `format_syslog_line`.
- [ ] `run-vm.sh` string-contains `infra/endpoint/logs` and does not contain `docker.sock`; 9p that path only; `qemu-img` overlay 8G; `touch` three log files as regular files; cloud-init copies **repo** `guest/` only (no `curl | sh`, no `#include` URL).
- [ ] `attach-usb.sh` / `detach-usb.sh`: hardcoded paths; reject extra argv; unix monitor `device_add usb-storage,id=lab-stick,drive=lab-stick` with `drive_add` of `infra/endpoint/run/lab-stick.img` (lock this pair in the script comments; do not take argv).
- [ ] No compose QEMU service.
- [ ] If this task merges: one ChangeLog bullet for the guest appliance.
- [ ] Commit only with checksums filled.

---

## File map

| File | Change |
|---|---|
| `docs/superpowers/plans/2026-08-23-linux-endpoint-telemetry.md` | Superseded banner (Task 0) |
| `src/estate/models.py` | `LAB_HOST` |
| `src/estate/loader.py` | `_validate_lab_host_log_sources` |
| `inventory/default.yaml` | `lab-endpoint` |
| `infra/compose.yaml` | three file binds |
| `infra/vector/vector.yaml` | three sources/remaps/sink inputs |
| `infra/endpoint/guest/journal_map.py` | Task 3 only |
| `infra/endpoint/**` | Task 6 |
| tests listed above | new |
| `docs/ingest-layer.md` | three source rows + untrusted payload |
| `docs/agents/*` | after Tasks 0–4; Task 6 bullet only if 6 merges |

---

## NON-GOALS

- Detect rules; Kafka-order causality.
- Layer 7 calling `attach-usb.sh`; in-scope USB until helper autorun is gated.
- Respond via QEMU; `qemu_vm` handle.
- Parsing payloads into Event fields.
- Sysmon, auditd, Falco, osquery, Vector `journald` source.
- Guest NIC, `lab-net`, live sshd, shop HTTP from guest.
- OS-wide process telemetry (slice C).
- Tailing `/var/log/auth.log`.
- Inventory hot-reload; Vector generated from Estate.
- Other operating systems.

---

## Decisions to record after code

1. Three file binds + 9p of `infra/endpoint/logs` only — not `lab-logs`, not a directory bind into Vector.
2. Host logs stay `source_type=file`; payload untrusted self-report.
3. `lab-endpoint` watch-only / no respond / red_team_skip.
4. Event schema v1; `source` in payload (`journal` vs `usb-helper`) is the channel tag.
5. CI goldens are the merge contract; live QEMU is operator verification.
6. No auditd. Helper `process.log` is confession of copy/exec.
7. Journal allowlist is volume control; raw journal objects never hit Kafka on the honest path.
8. This plan supersedes the USB-only endpoint plan.

---

## Council rulings

Seats: [Ambiguity](087ec973-e915-45b5-be5f-352309123dda), [Cybersecurity](e724aefb-1a4e-4aa8-83f8-9af783c87951), [Coding](1e2f9cfa-3503-46f4-a912-86f20877de3d), [System design](73b94383-36e6-4b0b-bb0f-4da78746c9a9), [Scalability](7a71d801-0176-4465-90a0-685584504c7a). Judge: [Final check](dad17857-76f8-4a0f-bf01-6ff59959633b) — **APPROVE WITH CONDITIONS** (two splices applied).

| Demand | Ruling |
|---|---|
| Import/fallback menu for `journal_map.py` | **One path:** `SourceFileLoader` as `lab_endpoint_journal_map`. No `sys.path`, no `src/` copy, no grep-allowlist. |
| PRIORITY int vs journalctl string | **Parse as int** (int or digit string). Emit JSON number. Fixtures for both. |
| Identifier `unknown` algorithm | **Closed keep rules** in this file. Off-list identifier + matching unit keeps; identifier becomes the off-list string if it is a `str`, else `"unknown"`. |
| Timestamp any RFC3339 | **Exact** `1690000000000000` → `2023-07-22T04:26:40.000000+00:00` (UTC; judge correction). |
| `format_syslog_line` + extra newline | **Write helper output once.** Judge correction. |
| MESSAGE truncate bytes vs chars | **UTF-8 bytes**, cut 16384 on codepoint boundary, then `...`. |
| syslog.jsonl 4 vs 5 lines | **Five** lines. Process **two** lines; bearer + spoof in `command_line`. |
| udev add/remove implicit | **Two rules** as written. `$DEVNAME` regex. `ro,nosuid,nodev,noexec`. |
| Dual USB plan | **Task 0 banner** before Estate work. |
| Task 5 claiming guest forwarder | **Tasks 0–4 only** in Task 5 docs. |
| FakeResolver vs Estate | **Estate(load_inventory)** only. |
| Vector substring tests | **`yaml.safe_load` structure** including keeping the original six inputs. |
| Tests not written | **Exact test bodies** in tasks. Task 4 tests before YAML. |
| Syslog as authentic journal | **Self-report.** Allowlist is noise filter. Document in ingest-layer rows. |
| Directory bind symlink into shop logs | **Three file binds** + `O_NOFOLLOW`. |
| “Never exec stick programs” | **Reword:** copy-then-exec still runs stick bytes as root. Autorun demo. |
| `source` missing on helper lines | **`source: usb-helper`** on udev and process. |
| sshd goldens imply NIC | **Fixtures only.** Live sshd/NIC is a named non-goal. |
| journalctl `-n 0` + Restart=always | **Cursor on qcow**, `--after-cursor`, `--output-fields`, start limits. |
| fsync per line on 9p | **Batch 32 lines or 1s.** |
| Unbounded 9p logs | **8 MiB rotate, 32 MiB dir, 20 lines/s, 8G qcow.** |
| Vector `max_line_bytes` 256KiB | **65536** + `ignore_not_found: true`. |
| stop-vm guest sync | **Monitor `quit` only.** |
| Goldens replaced by live capture | **Forbidden.** |
| Checksums in the plan | **In `run-vm.sh` only**, Task 6 merge gate. |
| `os.fsync` or equivalent | **`os.fsync` / `fsync`**, batched as above. |

Should-fix items that were accepted are folded into the locks above (loader helper location, zero extra argv, `0700` run dir, no curl-pipe cloud-init, IdP vs host auth wording).
