# Linux lab endpoint telemetry — implementation plan

> **SUPERSEDED** by [`2026-08-23-linux-system-logs.md`](2026-08-23-linux-system-logs.md).
> Do not implement this file. Same UUID `…107` / alias `lab-endpoint` / log dir would fork.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> This plan is the output of a council review. A draft was critiqued by five seats (ambiguity, cybersecurity, coding, critic, scalability). A judge synthesized the findings into this version. Rulings are in [Council rulings](#council-rulings). Do not implement from an older draft.

**Goal:** Plug one Linux lab host into the existing ingest pipe. Two file tails (`udev` + helper-written process JSON), one hardcoded alias `lab-endpoint`, redacted Events on that asset. CI proves the pipe with golden lines. A fully specified QEMU + virtual USB path exists for the operator; it is not a merge gate.

**Architecture:** Estate gains `lab_host` + inventory row. Compose bind-mounts a repo-local log dir into Vector. Vector remaps both files as `RawRecord` `source_type=file`, `source_alias=lab-endpoint`. Ingest does not parse host events. Optional live guest writes **only** that directory over virtio-9p; USB attach runs an in-guest helper that logs device/file/process and execs a copy of the marker (never a program from the stick).

**Tech Stack:** Existing Estate, Ingest, Vector, Kafka, pytest. Operator-only: QEMU, pinned Debian cloud image, udev, VFAT image built by a script. No Sysmon, no auditd, no extra kernel sensor.

**This plan is Linux only.**

## Global Constraints

- Linux guests and Linux sensors only. Agent docs (`docs/agents/*`, `AGENTS.md`) stay Linux-only.
- Operator workstation is not an asset, not a log source, not a red-team target, not a respond target.
- `ExecutionRealm` stays `{lab}` only.
- Estate stays a catalog. No execute methods in `src/estate/`.
- `RawRecord.source_type` stays `file | webhook`. Host logs are files.
- `LogSource.kind` stays a free `str` this slice. Inventory uses `file` (same as shop). Do not add a `process`/`device`/`syslog` enum here.
- No Event / Karapace schema bump. Payload stays opaque.
- No Sysmon. No auditd, Falco, or osquery. Device insert: udev (one JSON line). File create + process start: the in-guest USB helper writes one JSON line each to `process.log` for the copy and the exec it just performed. That is enough for this USB slice; it is not OS-wide process telemetry.
- Detect is out. Kafka order is not the USB story. Do not assert cross-file order.
- Respond and Recover execution are out. This asset is **watch-only**.
- Red-team assert / `in_scope_red_team` on this host are out. They land with Layer 7.
- No `docker.sock`, no host `$HOME` bind, no `network_mode: host`, no privileged SOC service, no guest NIC this slice (`-nic none`).
- No malware samples. USB image is a benign marker that only writes `/tmp/lab-usb-marker`.
- Secrets in inventory remain `env:` refs.

---

## How to read this

1. [Council rulings](#council-rulings) — what changed after the five reviews.
2. [What this builds](#what-this-builds) — the picture.
3. [What “done” means](#what-done-means) — merge vs operator.
4. [Locked paths](#locked-paths) — one path each, no “or.”
5. [Estate](#estate) / [Vector and ingest](#vector-and-ingest) / [Safety](#safety) / [Live guest](#live-guest-operator-path).
6. [Tasks](#implementation-tasks) — implement in order.

---

## Council rulings

Seats: [Ambiguity](b5009f41-9bd4-41ab-a1fd-5ca41c8990d5), [Cybersecurity](6e68c658-2434-4e2c-9b6f-9841890fabe2), [Coding](6c4b2049-1554-4213-8c60-fc6747f9f040), [Critic](f7b0afe7-4516-498e-9aa2-0d512a326f30), [Scalability](b978b13f-c1b9-40c3-bfaf-7f20a112e5ea).

| Demand | Ruling |
|---|---|
| Live QEMU is theater if CI only replays goldens | **Accept the honesty, keep the guest as operator-only.** Merge does not claim a live USB Event. README is verification, not the product test. |
| Named volume `lab-logs` cannot be a QEMU share | **Accept.** New repo-local dir + Vector bind + 9p of **that dir only**. Compose **does** change. |
| Three disagreeing log paths | **Accept.** Lock the table in [Locked paths](#locked-paths). Inventory locators stay in-guest style (same as shop). Do not “fix” them to Vector paths. |
| USB attach does not run the marker | **Accept.** In-guest helper, installed on the guest disk, udev `RUN+=` that helper only. Helper mounts, copies marker to `/tmp`, unmounts, writes process JSON, execs the **copy**. Never exec from the stick. |
| Sysmon XML will shred on Vector file tails | **Superseded.** Sysmon is out of this plan. See [Post-council: drop Sysmon](#post-council-drop-sysmon). |
| FileCreate exclude-shaped config will flood the shared Kafka sink | **Superseded.** No kernel FileCreate sensor. The helper emits two process lines per attach. |
| Shop `curl`, `lab-net` edge, guest user-net | **Delete.** Marker writes a file. Guest gets `-nic none`. No `shares_network` edge. |
| `assert_red_team_target` / USB `attack_surface` / `in_scope_red_team` with no runner | **Delete from this slice.** Catalog the host as `red_team_skip: true`, `in_scope_red_team: false`. |
| `respond_allowed` + `qemu_vm` handle (monitor is a host control plane) | **Delete.** `respond_allowed: false`, `watch_only`, no containment handle. `attach-usb.sh` is an operator script. Layer 7 must not call it. |
| Widen `LogSource.kind` to process/device/syslog | **Delete.** Keep `kind: file`. Sensor class waits for Detect. |
| virtio-fs as an option | **Delete.** virtio-9p only, mapped, endpoint-dir only. |
| Dual Sysmon install (repo or `.deb`) | **Superseded.** No Sysmon package. |
| Task 1 `assert_red_team_target(soc-api)` would pass today | **Moot** — that function is not in this slice. |
| Writing-plans missing signatures / golden contents | **Accept.** Tasks below name types, inventory fields, and golden line shapes. |
| Compose substring `/Users/` vs a needed home bind | **Accept.** Bind is **repo-relative** `./endpoint/logs`. Deny-list does not ban `/Users/` as a bare string; it bans host home and docker.sock **on volume/network keys and on `infra/endpoint/*.sh`**. |
| SCHEMA_VERSION bump | **Reject.** Stays `1`. Only new `AssetKind.LAB_HOST`. |

### Post-council: drop Sysmon

Operator lock after the council: this slice is Linux only. Sysmon is an extra package, eBPF, a pinned `.deb`, and an XML-to-JSON converter for Event IDs we do not need.

**Keep two files.** `udev.log` is still the device sensor. `process.log` is file_create + process_create for the USB helper’s own copy/exec. That is the lab USB story, not a host-wide process feed.

**Do not add auditd** in this slice (volume, format, kernel hook). If we later want OS-wide exec/file on Linux, that is a new sensor decision, not a silent substitute.

---

## What this builds

Today the pipe only sees application files (shop, idp, wallet, soc-api) and two webhooks. A USB on a machine never writes those files.

We add **one lab Linux host** as a catalogued log source. The pipe learns two new files. That is the slice.

```
repo  infra/endpoint/logs/     ← only directory the guest may write
        udev.log
        process.log
            │
            │ compose bind (read-only in Vector)
            ▼
      Vector  /var/log/lab/lab-endpoint/*.log
      source_alias hardcoded "lab-endpoint"
            │
            ▼
      Kafka soc.raw.v1 → ingest → Event
      asset_id = 11111111-1111-4111-8111-111111111107
```

Optional, same bytes, not CI:

```
QEMU Linux guest  -nic none
  udev + usb helper (writes udev.json lines + process.json lines)
  virtio-9p → same infra/endpoint/logs
  attach-usb.sh → QEMU monitor unix socket (operator only)
```

---

## What “done” means

**Merge (CI, required):**

1. Default inventory loads `lab-endpoint` as `lab_host`.
2. `resolve_alias("default", "lab-endpoint")` returns `11111111-1111-4111-8111-111111111107`.
3. Golden udev + process **JSON lines**, each wrapped as a `RawRecord` with `source_alias=lab-endpoint`, normalize to that `asset_id`.
4. A spoof line that contains `"source_alias":"soc-api"` still maps to `lab-endpoint`.
5. A `Authorization: Bearer …` inside a process `command_line` is `[REDACTED]`.
6. `vector.yaml` has both sources, both remaps, both aliases `lab-endpoint`, both remaps listed in `sinks.kafka_raw.inputs`.
7. Compose bind-mounts `./endpoint/logs` to `/var/log/lab/lab-endpoint:ro` on Vector.
8. `infra/endpoint/logs/{udev,process}.log` exist (empty is fine) so the include path is present with the guest down.
9. Safety scan: compose volume/network keys and `infra/endpoint/*.sh` contain no `docker.sock`, no `privileged:`, no `network_mode: host`, no `/var/run/docker.sock`.

**Operator (documented, not a merge gate):**

10. `run-vm.sh` boots the pinned guest, 9p-exports `infra/endpoint/logs` only, `-nic none`.
11. `build-stick.sh` builds a VFAT image (not committed).
12. `attach-usb.sh` adds that image via a **unix** QEMU monitor socket.
13. In-guest helper produces udev + process JSON lines in the shared dir.
14. You may confirm Events by hand. CI does not.

If (1–9) pass, the slice ships even if you never install QEMU.

---

## Locked paths

One name everywhere: `lab-endpoint`.

| Role | Path |
|---|---|
| Repo / QEMU 9p source (host) | `infra/endpoint/logs/` |
| Files on host | `infra/endpoint/logs/udev.log`, `infra/endpoint/logs/process.log` |
| Vector container | `/var/log/lab/lab-endpoint/udev.log`, `…/process.log` |
| Guest mount (9p) | `/var/log/lab-endpoint` |
| Guest files | `/var/log/lab-endpoint/udev.log`, `…/process.log` |
| Estate `log_sources[].locator` | `/var/log/lab-endpoint/udev.log`, `/var/log/lab-endpoint/process.log` |
| QEMU monitor (host, gitignored runtime) | `infra/endpoint/run/monitor.sock` |
| USB image (built, not committed) | `infra/endpoint/run/lab-stick.img` |

Estate locators are **in-guest** paths, matching `lab-shop` → `/var/log/lab-shop/access.log` vs Vector `/var/log/lab/lab-shop/access.log`. Do not generate Vector sources from Estate locators in this slice.

---

## Estate

### Models (`src/estate/models.py`)

Add only:

```python
class AssetKind(str, Enum):
    # ... existing members ...
    LAB_HOST = "lab_host"
```

`SCHEMA_VERSION` remains `1`. `LogSource.kind` remains `str`. `ExecutionRealm` remains `{lab}`.

### Inventory (`inventory/default.yaml`)

Full record (all fields current assets set):

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
      - id: endpoint-udev
        kind: file
        locator: "/var/log/lab-endpoint/udev.log"
      - id: endpoint-process
        kind: file
        locator: "/var/log/lab-endpoint/process.log"
    in_scope_red_team: false
    red_team_skip: true
```

No `attack_surface`, no `containment_handles`, no `restore_handles`, no new edges.

Loader: if `kind == lab_host` and `log_sources` is empty → `InventoryInvalid`. No docker.sock deny-list on handles this slice (we are not adding executable handles).

### Query / errors / CLI

No `RedTeamForbidden`. No `assert_red_team_target`. CLI unchanged. `Estate.list` will show `lab_host` once the enum exists.

---

## Vector and ingest

### Compose (`infra/compose.yaml`)

On the existing `vector` service, **add** (do not remove `lab-logs`):

```yaml
      - ./endpoint/logs:/var/log/lab/lab-endpoint:ro
```

Keep `lab-logs:/var/log/lab:ro` for the app files. The bind overlays only the `lab-endpoint` subdirectory. Vector stays `read_only`, `cap_drop: ALL`, no `docker.sock`.

### Vector (`infra/vector/vector.yaml`)

Copy the shop pattern. Two sources, two remaps, **append both remaps** to `sinks.kafka_raw.inputs` (that list is explicit today; forgetting it means Kafka never sees the lines).

| Source id | include | remap | hardcoded alias |
|---|---|---|---|
| `file_lab_endpoint_udev` | `/var/log/lab/lab-endpoint/udev.log` | `wrap_lab_endpoint_udev` | `lab-endpoint` |
| `file_lab_endpoint_process` | `/var/log/lab/lab-endpoint/process.log` | `wrap_lab_endpoint_process` | `lab-endpoint` |

Both remaps: `source_type: "file"`, `collector: "vector"`, rebuild the RawRecord; content cannot set envelope fields.

On both file sources set `max_line_bytes: 262144` (match `INGEST_MAX_PAYLOAD_BYTES`). Vector’s default line cap is smaller than ingest’s and would **drop** a long CommandLine before DLQ.

Two files, one alias: both hash to the same `soc.raw.v1` partition. Ingest then keys Events on `asset_id`. Streams **interleave**. Detect (later) may sort JSON `timestamp`; this slice must not claim Kafka order is udev → file → process.

### Ingest

No model change. `normalize` already takes one RawRecord JSON blob, not a multi-line file.

Tests wrap **each golden line**:

```python
record = make_raw_record(source_alias="lab-endpoint", raw=line)
# then serialize to bytes the way existing tests do
result = normalize(raw_bytes, resolver, max_payload_bytes=262144)
```

Use `Estate(load_inventory(INVENTORY_PATH))` after the inventory row exists. The default fake resolver does not know `lab-endpoint` unless you add it — prefer the real inventory.

JSON lines **must** use a key `normalize` already reads for `occurred_at`: `@timestamp`, `timestamp`, `time`, or `ts`. Use `"timestamp"`.

---

## Safety

| Rule | Enforcement |
|---|---|
| Operator box not in Estate | No inventory row, no Vector source on host OS logs. |
| Guest cannot forge shop/api logs | 9p and bind are **only** `infra/endpoint/logs`. Guest never sees `lab-logs` siblings. |
| Guest cannot reach operator or SOC net | `-nic none`. No shop curl. No `lab-net`. |
| Hypervisor is not a respond tool | No `qemu_vm` handle. `respond_allowed: false`. |
| USB attach is not Layer 7 | Scripts take no extra argv. Image path and monitor path hardcoded. |
| Envelope spoof | Existing provenance lock + one process-JSON spoof test. |
| Prompt-shaped payload | Golden line may contain instruction-like text; it still cannot set `source_alias`. Document: endpoint payload is guest-controlled and forgeable. |
| udev does not run stick programs | `RUN+=/usr/local/sbin/lab-usb-ingest` only. Helper is on the guest disk. |
| Compose / scripts | Policy test on volume/network keys and `infra/endpoint/*.sh`. |

Human-in-the-loop is not in this slice. Structural locks still land.

---

## Live guest (operator path)

Not CI. Still specified so two operators do not invent two VMs.

### Layout

```
infra/endpoint/
  logs/.gitkeep
  logs/udev.log          # committed empty
  logs/process.log       # committed empty
  run/.gitignore         # monitor.sock, lab-stick.img, qcow overlay
  run-vm.sh
  stop-vm.sh
  attach-usb.sh
  detach-usb.sh
  usb/build-stick.sh
  usb/lab-marker.sh      # source of the marker; writes /tmp/lab-usb-ok only
  guest/cloud-init.yaml
  guest/99-lab-usb.rules
  guest/lab-usb-ingest   # log udev → mount → cp → log file_create → log process_create → exec copy
  README.md
```

Do not commit `lab-stick.img` or a qcow.

### Pins (fill the checksums at implement time, in the scripts, before merge of Task 5)

- Distro: **Debian 12** cloud image, `qemu` x86_64.
- Image URL + sha256 in `run-vm.sh`.

No extra telemetry packages. If the cloud image cannot be fetched, Task 5 stays unmerged; do not add a kernel sensor to compensate.

### QEMU flags (required)

- `-nic none`
- virtio-9p: host `infra/endpoint/logs` → guest `/var/log/lab-endpoint`, mapped, `cache=none`
- monitor: unix socket `infra/endpoint/run/monitor.sock`, no TCP
- no `-enable-kvm` requirement in CI (there is no CI QEMU). Operator may use KVM if present.
- no `docker.sock`, no `/Users`, no `/home` binds, no virtio-fs

`stop-vm.sh` issues a monitor `quit` after a `sync`-equivalent so 9p does not lose the last lines (`cache=none` plus a guest `sync` in the helper after each write).

### process.log shape

The helper appends **one JSON object per line**. Goldens use the same keys. Newlines inside `command_line` must be escaped.

```json
{"timestamp":"2026-08-23T00:00:00.000000+00:00","action":"file_create","path":"/tmp/lab-usb-marker"}
{"timestamp":"2026-08-23T00:00:00.000000+00:00","action":"process_create","image":"/tmp/lab-usb-marker","command_line":"/tmp/lab-usb-marker"}
```

These lines describe what the helper did. They are guest-controlled and forgeable. They are not a kernel audit trail.

### udev

Rule matches `ACTION=="add"` for USB storage (kernel `usb-storage` / `ID_USB_DRIVER=="usb-storage"`). `RUN+=/usr/local/sbin/lab-usb-ingest`.

udev log line (only this shape):

```json
{"timestamp":"2026-08-23T00:00:00.000000+00:00","action":"add","devtype":"disk","devname":"/dev/sdb"}
```

`ID_SERIAL` is optional. No key=value format.

### USB helper (`lab-usb-ingest`)

1. Write the udev JSON add line to `/var/log/lab-endpoint/udev.log`.
2. Mount the new device read-only at `/mnt/lab-stick`.
3. `cp /mnt/lab-stick/lab-marker.sh /tmp/lab-usb-marker` (file on the image is `lab-marker.sh`, dest is `/tmp/lab-usb-marker`).
4. `umount /mnt/lab-stick`
5. `chmod 0755 /tmp/lab-usb-marker`
6. Append `action=file_create` for `/tmp/lab-usb-marker` to `process.log`.
7. Append `action=process_create` for `/tmp/lab-usb-marker` to `process.log`.
8. `sync` the log dir.
9. Exec `/tmp/lab-usb-marker` (the copy).

Never exec a path on the stick. Never write programs from the stick into `lab-usb-ingest` itself.

### Marker (`usb/lab-marker.sh`)

```sh
#!/bin/sh
printf 'LAB_USB_MARKER_V1\n' > /tmp/lab-usb-ok
```

No curl. No network. Success is that file. Process proof is the helper’s `process_create` line for `/tmp/lab-usb-marker`, not a kernel sensor.

### `attach-usb.sh` / `detach-usb.sh`

Hardcoded image `infra/endpoint/run/lab-stick.img` and monitor `infra/endpoint/run/monitor.sock`. No extra arguments. Monitor commands only add/remove that `usb-storage` drive. Unix socket, owner-only (`0600` on the sock dir).

---

## Tests

No live QEMU. No Kafka. No Vector binary.

### Estate (`tests/estate/test_estate.py` or `tests/estate/test_lab_host.py`)

- Default inventory: `get("11111111-1111-4111-8111-111111111107").kind.value == "lab_host"`.
- `resolve_alias("default", "lab-endpoint")` equals that UUID.
- `assert_respond_target` on that UUID raises `RespondForbidden` (`respond_allowed=false`).
- Loader: `lab_host` with empty `log_sources` → `InventoryInvalid`.
- Existing tests still pass.

### Ingest (`tests/ingest/test_normalizer.py` + `tests/ingest/testdata/endpoint/`)

There is no top-level `testdata/` today. Put goldens next to ingest tests.

Files:

- `tests/ingest/testdata/endpoint/udev.jsonl` — two lines, the add event above plus one remove.
- `tests/ingest/testdata/endpoint/process.jsonl` — two lines, `file_create` then `process_create` for `/tmp/lab-usb-marker`. One includes `command_line` with `Authorization: Bearer eyJhbGciOi.fake.token`.
- One spoof line: JSON that includes `"source_alias":"soc-api"` in the payload.

Loop each line → wrap RawRecord → `normalize` → `Normalized`, `event.asset_id` is the new UUID, `event.source_alias == "lab-endpoint"`. Bearer redacted. Spoof alias unchanged.

`tests/ingest/testdata/endpoint/README.md`: these are **contract fixtures** in the locked JSON shape. The first successful live guest should replace them with captured lines of the same keys. Until then they are not a claim that a guest ran.

### Vector / compose

- `tests/infra/test_vector_endpoint_sources.py`: read `infra/vector/vector.yaml` as text (or yaml.safe_load). Assert both includes, both `source_alias` assignments equal `lab-endpoint`, and `wrap_lab_endpoint_udev` / `wrap_lab_endpoint_process` appear under `sinks.kafka_raw.inputs`.
- `tests/infra/test_compose_safety.py`: parse compose; on `vector` (and any new endpoint-related service, of which there should be **none** in compose) reject `privileged`, `network_mode: host`, volume sources containing `docker.sock`. Also scan `infra/endpoint/*.sh` for `docker.sock` and `network_mode: host`. Do not fail on the word `/Users/` in a comment.

---

## File map

| File | Change |
|---|---|
| `src/estate/models.py` | `LAB_HOST` |
| `inventory/default.yaml` | `lab-endpoint` row above |
| `src/estate/loader.py` | empty-log-sources rule for `lab_host` |
| `infra/compose.yaml` | Vector bind `./endpoint/logs` |
| `infra/vector/vector.yaml` | two sources, two remaps, sink inputs, `max_line_bytes` |
| `infra/endpoint/logs/*` | empty log files + `.gitkeep` |
| `infra/endpoint/**` | operator scripts + guest files (Task 5) |
| `tests/estate/test_lab_host.py` | new |
| `tests/ingest/testdata/endpoint/*` | goldens |
| `tests/ingest/test_normalizer.py` | golden / spoof / redact cases |
| `tests/infra/test_vector_endpoint_sources.py` | new |
| `tests/infra/test_compose_safety.py` | new |
| `docs/ingest-layer.md` | two rows in the current-sources table |
| `docs/agents/ChangeLog.md` | one Linux-only bullet after code lands |
| `docs/agents/Decisions.md` | decisions below, after code lands |
| `docs/agents/Flow.md` | Vector sources include endpoint files, after code lands |

---

## Implementation tasks

### Task 1: Estate `lab_host` + inventory

**Files:** `src/estate/models.py`, `src/estate/loader.py`, `inventory/default.yaml`, `tests/estate/test_lab_host.py`

**Interfaces:**

- `AssetKind.LAB_HOST.value == "lab_host"`
- `load_inventory` rejects `kind: lab_host` with `log_sources: []`
- No new query methods

- [ ] Write `tests/estate/test_lab_host.py` (load default, resolve alias, respond forbidden, empty logs invalid).
- [ ] Run `pytest tests/estate/test_lab_host.py -v` — fail until models/inventory exist.
- [ ] Add enum member + inventory row + loader rule.
- [ ] Run `pytest tests/estate/ -v` — pass.
- [ ] Commit estate-only.

### Task 2: Golden lines + ingest mapping

**Files:** `tests/ingest/testdata/endpoint/*`, `tests/ingest/test_normalizer.py`

**Interfaces:**

- Consume: `normalize(raw_bytes, resolver, *, max_payload_bytes: int) -> Normalized | Unmapped | Invalid`
- Produce: `Normalized.event.asset_id == "11111111-1111-4111-8111-111111111107"`

- [ ] Add the jsonl fixtures (exact keys in [Vector and ingest](#vector-and-ingest) / [Live guest](#live-guest-operator-path)).
- [ ] Tests: map, redact, spoof, unknown alias `lab-endpoint-shadow` → `Unmapped`.
- [ ] Run `pytest tests/ingest/test_normalizer.py -v` — pass.
- [ ] Commit.

### Task 3: Vector + compose bind + empty logs + config tests

**Files:** `infra/vector/vector.yaml`, `infra/compose.yaml`, `infra/endpoint/logs/udev.log`, `infra/endpoint/logs/process.log`, `tests/infra/test_vector_endpoint_sources.py`, `tests/infra/test_compose_safety.py`, `docs/ingest-layer.md` source table only.

- [ ] Create empty log files.
- [ ] Vector sources/remaps/sink inputs/`max_line_bytes`.
- [ ] Compose bind.
- [ ] Config + safety tests.
- [ ] Update ingest-layer current-sources table (Linux only; two new rows).
- [ ] Run `pytest tests/infra/ tests/ingest/ tests/estate/ -v` — pass.
- [ ] Commit.

### Task 4: Agent docs (Linux only, after Tasks 1–3)

- [ ] `docs/agents/ChangeLog.md` — `lab_host`, inventory row, Vector tails, compose bind. No other OS families.
- [ ] `docs/agents/Decisions.md` — bind+9p dir; JSON lines; no Sysmon; helper writes process.log; watch-only host; no red-team/respond gates; goldens are contract fixtures; two files one alias interleave; no Event schema change.
- [ ] `docs/agents/Flow.md` — Vector sources include the two endpoint files. Query list unchanged (no new assert).
- [ ] Re-read those three files: Linux only.
- [ ] Commit.

### Task 5: Operator QEMU path (optional merge; required if you want live USB)

**Files:** `infra/endpoint/**` as in the layout. Split from Task 3.

- [ ] Scripts and guest files with pins, `-nic none`, 9p, unix monitor, helper that writes udev + process JSON, `build-stick.sh`, README.
- [ ] Safety test already scans `*.sh`.
- [ ] Do not add a compose QEMU service.
- [ ] Commit only when checksums are filled in.

---

## NON-GOALS

- Detect rules (device → file → process). Events must exist first; order is not in Kafka.
- `assert_red_team_target` / Layer 7 calling `attach-usb.sh`.
- Respond isolating the guest or the operator QEMU process.
- Parsing process JSON into Event fields / schema bump.
- Sysmon, auditd, Falco, osquery, extra forwarders.
- Guest on `lab-net`, shop HTTP, NetworkConnect.
- Inventory hot-reload.
- Generating Vector config from Estate locators.
- Other operating systems.

---

## Decisions to record after code (Linux only)

1. Repo-local `infra/endpoint/logs` + Vector bind + virtio-9p of that directory — not the `lab-logs` named volume.
2. Host logs stay `RawRecord.source_type=file`; Estate `LogSource.kind` stays `file`.
3. `lab-endpoint` is `watch_only` / `respond_allowed=false` / `red_team_skip=true` until actuation exists that is not the operator hypervisor.
4. Ingest schema stays v1; Detect will parse JSON payloads later. Interleaved offsets are not causality.
5. CI goldens are the merge contract; live QEMU is operator verification.
6. No Sysmon. `process.log` is written by `lab-usb-ingest` for the copy/exec it performs. OS-wide process telemetry is a later Linux sensor decision.
