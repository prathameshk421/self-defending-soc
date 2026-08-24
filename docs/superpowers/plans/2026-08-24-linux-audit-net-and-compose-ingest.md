# Finish Layer 2 ingest (compose agent + host audit + network JSON)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: Council-approved.** Draft critiqued by flaws, scalability, Kafka, Vector, Karapace, cybersecurity, then a plan-review seat. Judge ([Final check](72da1d29-1634-4463-941d-b3b3c56426ee)): **APPROVE WITH CONDITIONS**. Splices are in Global Constraints. Do not implement from the pre-council draft.
>
> **Supersedes C/D “Later”** in [`2026-08-23-linux-system-logs.md`](2026-08-23-linux-system-logs.md). In-guest `auditd` supersedes “No auditd/Sysmon” **for the guest only**. Vector still has no auditd/journald source.

**Goal:** Make the ingest pipe operator-runnable on compose, then feed `lab-endpoint` OS-wide audit JSON and (later merge) network JSON through the existing envelopes onto `soc.events.v1`, so an operator can boot compose + QEMU and see host Events.

**Architecture:** Vector still provenance-locks `source_alias=lab-endpoint` per file path. Guest writers emit JSON lines with payload `source` tags. Compose runs `soc-agent-ingest` on `lab-net`. Kafka stays unpublished. Schema v1 frozen.

**Tech Stack:** Existing Estate, Ingest, Vector, Kafka, Karapace, pytest. New: `infra/ingest/Dockerfile` (python:3.12-bookworm digest-pinned). Operator-only QEMU. Offline hashed `.deb`s on the nocloud ISO.

## Global Constraints

- Linux guests and Linux sensors only. Operator workstation is not an asset.
- Slice **E is out**: no Detect rules, no `assert_respond_target` success, no `in_scope_red_team` / `qemu_vm`, no in-scope USB attacks. `lab-endpoint` stays `watch_only` / `respond_allowed=false` / `red_team_skip=true` / `exposure: loopback`.
- `RawRecord.source_type` stays `file | webhook`. No Event/RawRecord field add. `EVENT_SCHEMA_VERSION=1`. No unmapped/dlq Karapace subjects. Channel tag lives only in opaque `payload` JSON key `source` ∈ `{journal, usb-helper, auditd, nft, dns}`.
- Envelope `source_alias` is **always** `lab-endpoint` (one alias). Log_source **ids** `endpoint-audit` / `endpoint-net` are inventory only. Detect must not treat alias or `source` as kernel proof. Guest JSON is self-report.
- No Kafka/Karapace/Vector/ingest `ports:`. Advertised `SASL://kafka:9092`. No ingest Write on `soc.raw.v1`. No ingest Read on `soc.events.v1`. `ingest emit` is not the operator smoke.
- No pcap, packet/hex dump, nflog copy-payload, guest on docker `lab-net`, `hostfwd`/`guestfwd`/`smb`/`tftp`, tap/bridge.
- Do not add lab-shop / lab-idp / lab-wallet / soc-api compose services. App-path stays Slice A CI goldens.
- Do not generate Vector from Estate locators. VRL rebuilds `. = {…}` (not merge). File sources have no JSON codec. `max_line_bytes: 65536`. `ignore_not_found: true`.
- 9p string-equals `infra/endpoint/logs` only. Vector inode-pins **files**, never `./endpoint/logs:`.
- CI goldens are the merge contract. Live QEMU/Kafka is operator verification, not a pytest gate.
- Three merge gates: Phase 0, Phase 1, Phase 2. Do not ship D in the same merge as C. Keep `-nic none` until Phase 2.
- Deb verify uses **SHA256** (what Debian `Packages` publishes). Qcow pin stays SHA512.

### Locked numbers

| Lock | Value |
|---|---|
| Keep-rate per 9p file | 20 lines/s |
| Drop-notice | ≤1 line/s per writer |
| Truncate | 8 MiB, same inode (`ftruncate` / `: >file`); no rename; no `.log.1` on 9p |
| 9p dir cap | 80 MiB, every writer, before keep-write |
| Fsync batch | 32 lines or 1.0 s |
| Vector `max_line_bytes` | 65536 |
| `INGEST_MAX_PAYLOAD_BYTES` | 262144 |
| Broker `message.max.bytes` | 1048576 |
| App sink disk buffer | 256 MiB, `when_full: block` |
| Endpoint sink disk buffer | 256 MiB, `when_full: drop_newest` |
| Ingest `mem_limit` | 512m |
| `soc.raw.v1` | 3 partitions, 48h, `retention.bytes=1073741824` |
| Overlay | 8G, **always deleted** then recreated |
| Guest journal `SystemMaxUse` | 256 MiB |
| auditd on qcow | `max_log_file=8`, `num_logs=2`, `max_log_file_action=ROTATE` |
| String field cap | 16384 UTF-8 bytes, codepoint cut, then `...` |

### Path table (lock)

| Vector `source_alias` | log_source id | Estate locator | Vector include | Host bind |
|---|---|---|---|---|
| `lab-endpoint` | endpoint-syslog | `/var/log/lab-endpoint/syslog.log` | `/var/log/lab/lab-endpoint/syslog.log` | `./endpoint/logs/syslog.log` |
| `lab-endpoint` | endpoint-udev | `/var/log/lab-endpoint/udev.log` | `/var/log/lab/lab-endpoint/udev.log` | `./endpoint/logs/udev.log` |
| `lab-endpoint` | endpoint-process | `/var/log/lab-endpoint/process.log` | `/var/log/lab/lab-endpoint/process.log` | `./endpoint/logs/process.log` |
| `lab-endpoint` | endpoint-audit | `/var/log/lab-endpoint/audit.log` | `/var/log/lab/lab-endpoint/audit.log` | `./endpoint/logs/audit.log` |
| `lab-endpoint` | endpoint-net | `/var/log/lab-endpoint/net.log` | `/var/log/lab/lab-endpoint/net.log` | `./endpoint/logs/net.log` |

Inventory `aliases: ["lab-endpoint"]` only. Asset id `11111111-1111-4111-8111-111111111107`.

### Vector sinks (Phase 0)

- `kafka_raw_app`: inputs = `wrap_lab_shop`, `wrap_lab_idp`, `wrap_lab_wallet`, `wrap_soc_api`, `wrap_webhooks`, `wrap_redteam`. Disk 256 MiB, `when_full: block`.
- `kafka_raw_endpoint`: inputs = all `wrap_lab_endpoint_*` (three in Phase 0; append audit then net in later phases). Disk 256 MiB, `when_full: drop_newest`.
- Delete `sinks.kafka_raw`. Same topic `soc.raw.v1`, `key_field: source_alias`, SASL `vector`.

### Phase 0 USB gate

`lab-usb-ingest` copies the marker, writes `file_create` only, **does not** write `process_create`, **does not** `exec`. Do not widen udev. Slice B `process.jsonl` goldens stay fixtures; do not overwrite them from live USB.

### Overlay

`run-vm.sh` always `rm -f "$OVERLAY"` then `qemu-img create` from the pinned base. Journal cursor on qcow is lost every boot. No instance-id bump.

### Track 0 smoke (not `emit`)

After compose up, append one Slice B syslog golden line onto `infra/endpoint/logs/syslog.log` (regular file). Consume `soc.events.v1` as `User:admin` from the **same** `apache/kafka@sha256:3f7b939115cd4872e9cee9369d80bd69712fde55f9902f46d793f64848dedc75` image on `lab-net`, throwaway group, never `ingest-normalizer`. Success = JSON Event `asset_id` `11111111-1111-4111-8111-111111111107`. Document in `docs/ingest-layer.md` and `infra/endpoint/README.md`. Not a pytest gate.

---

## Package / file map

| File | Responsibility |
|---|---|
| `src/ingest/ports.py` | `Consumer.commit(messages: list[RawMessage])` |
| `src/ingest/pipeline.py` | After flush, commit whole batch |
| `src/ingest/kafka_adapter.py` | Commit max(offset)+1 per `(topic, partition)` |
| `tests/ingest/conftest.py` | `make_raw_message(..., partition=)`; FakeConsumer.commit list |
| `tests/ingest/test_pipeline.py` | Two-partition commit test |
| `infra/ingest/Dockerfile` | Pinned python image; `pip install '.[kafka]'` |
| `infra/compose.yaml` | `soc-agent-ingest` service; two more file binds in later phases |
| `infra/kafka-init.sh` | Alter `soc.raw.v1` `retention.bytes` |
| `infra/vector/vector.yaml` | Two sinks; later two sources |
| `inventory/default.yaml` | Locator fix; later two log_source ids |
| `infra/endpoint/guest/lab-journal-forward` | Truncate + 80 MiB cap |
| `infra/endpoint/guest/lab-usb-ingest` | Truncate + dir cap; no exec |
| `infra/endpoint/guest/lab-audit-forward` | Phase 1 |
| `infra/endpoint/guest/lab-net-forward` | Phase 2 exclusive `net.log` writer |
| `infra/endpoint/guest/lab-dns-stub` | Phase 2; bind `127.0.0.1:53`; no recurse |
| `infra/endpoint/run-vm.sh` | Always recreate overlay; touch stubs; Phase 2 NIC |
| `docs/ingest-layer.md` | Sources table + “see it move” |

---

## Phase 0 — Track 0 (CI merge)

Operator can `docker compose up` and consume a host Event. USB no longer execs. Locators match the path table for the three existing files. No QEMU in CI. Still `-nic none`. No `audit.log` / `net.log` Vector sources yet; `touch` those stubs anyway so later binds cannot become directories.

### Task 1: Commit every partition in a batch

**Files:**
- Modify: `src/ingest/ports.py`, `src/ingest/pipeline.py`, `src/ingest/kafka_adapter.py`, `tests/ingest/conftest.py`, `tests/ingest/test_pipeline.py`

**Interfaces:**
- Consumes: `RawMessage.topic`, `.partition`, `.offset`
- Produces: `Consumer.commit(messages: list[RawMessage]) -> None`

- [ ] **Step 1: Write the failing test**

Add `partition` to `make_raw_message`. Replace `test_batch_commits_only_last_offset`.

```python
def make_raw_message(
    record: RawRecord, offset: int = 0, partition: int = 0
) -> RawMessage:
    return RawMessage(
        topic=TOPIC_RAW,
        partition=partition,
        offset=offset,
        key=record.source_alias,
        value=record.model_dump_json().encode("utf-8"),
    )
```

```python
def test_batch_commits_all_partitions(resolver):
    m0 = make_raw_message(make_raw_record(), offset=4, partition=0)
    m1 = make_raw_message(
        make_raw_record(source_alias="lab-idp"), offset=9, partition=1
    )
    pipeline, consumer, producer = _pipeline([m0, m1], resolver)

    result = pipeline.run_once()

    assert result.events == 2 and result.committed
    assert consumer.committed == [m0, m1]
```

Keep `test_happy_path_event_produced_and_committed` asserting `consumer.committed == [message]` (single-element batch).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingest/test_pipeline.py::test_batch_commits_all_partitions -v`

Expected: FAIL (`test_batch_commits_only_last_offset` gone / new test not found, or `committed == [m1]`).

- [ ] **Step 3: Implement**

`ports.py`:

```python
class Consumer(Protocol):
    def poll(self, timeout: float = 1.0) -> Optional[RawMessage]: ...

    def commit(self, messages: list[RawMessage]) -> None:
        """Commit max(offset)+1 for each distinct (topic, partition)."""
        ...
```

`pipeline.py` `run_once`: after `flush()` with no failures, `self._consumer.commit(batch)` (not `batch[-1]`).

`kafka_adapter.py`:

```python
def commit(self, messages: list[RawMessage]) -> None:
    latest: dict[tuple[str, int], int] = {}
    for message in messages:
        key = (message.topic, message.partition)
        prev = latest.get(key)
        if prev is None or message.offset > prev:
            latest[key] = message.offset
    self._consumer.commit(
        offsets=[
            confluent_kafka.TopicPartition(topic, partition, offset + 1)
            for (topic, partition), offset in sorted(latest.items())
        ],
        asynchronous=False,
    )
```

`FakeConsumer.commit`: `self.committed.extend(messages)`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ingest/test_pipeline.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingest/ports.py src/ingest/pipeline.py src/ingest/kafka_adapter.py tests/ingest/conftest.py tests/ingest/test_pipeline.py
git commit -m "$(cat <<'EOF'
fix: commit every raw partition after a successful ingest flush

EOF
)"
```

### Task 2: Locators, truncate-in-place, 80 MiB cap, USB exec gate, overlay delete, stubs

**Files:**
- Modify: `inventory/default.yaml` lab-endpoint `log_sources` locators
- Modify: `tests/estate/test_lab_host.py`
- Modify: `infra/endpoint/guest/lab-journal-forward`
- Modify: `infra/endpoint/guest/lab-usb-ingest`
- Modify: `infra/endpoint/run-vm.sh`
- Modify: `tests/infra/test_compose_safety.py`
- Modify: `tests/infra/test_journal_map.py` (`test_run_vm_exports_logs_dir_only` plus new asserts)

**Interfaces:**
- Consumes: path table (syslog/udev/process only this task)
- Produces: locators `/var/log/lab-endpoint/{syslog,udev,process}.log`; no USB exec; overlay always recreated

- [ ] **Step 1: Failing tests**

In `test_lab_host.py`, after resolving the host:

```python
    locators = {s.id: s.locator for s in host.log_sources}
    assert locators == {
        "endpoint-syslog": "/var/log/lab-endpoint/syslog.log",
        "endpoint-udev": "/var/log/lab-endpoint/udev.log",
        "endpoint-process": "/var/log/lab-endpoint/process.log",
    }
    assert host.aliases == ["lab-endpoint"]
```

In `test_compose_safety.py` stub names become `("syslog.log", "udev.log", "process.log", "audit.log", "net.log")`. `FILE_BINDS` stays three rows this phase (audit/net binds come in later phases). Stubs must still be regular files.

In `test_journal_map.py`:

```python
def test_run_vm_recreates_overlay_and_stays_nic_none():
    text = (REPO_ROOT / "infra/endpoint/run-vm.sh").read_text(encoding="utf-8")
    assert "rm -f" in text and "overlay.qcow2" in text
    assert "-nic none" in text
    assert "hostfwd" not in text
    for name in ("syslog.log", "udev.log", "process.log", "audit.log", "net.log"):
        assert name in text

def test_journal_forwarder_truncates_in_place():
    text = (REPO_ROOT / "infra/endpoint/guest/lab-journal-forward").read_text(
        encoding="utf-8"
    )
    assert "DIR_CAP = 80 * 1024 * 1024" in text
    assert "truncate" in text or "ftruncate" in text
    assert ".rename(" not in text
    assert 'with_name(LOG_PATH.name + ".1")' not in text

def test_usb_helper_does_not_exec_marker():
    text = (REPO_ROOT / "infra/endpoint/guest/lab-usb-ingest").read_text(
        encoding="utf-8"
    )
    assert "exec /tmp/lab-usb-marker" not in text
    assert "process_create" not in text
    assert "file_create" in text
    assert "mv " not in text.split("rotate_if_needed", 1)[-1][:400]
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/estate/test_lab_host.py tests/infra/test_compose_safety.py tests/infra/test_journal_map.py::test_run_vm_recreates_overlay_and_stays_nic_none tests/infra/test_journal_map.py::test_journal_forwarder_truncates_in_place tests/infra/test_journal_map.py::test_usb_helper_does_not_exec_marker -v`

- [ ] **Step 3: Implement**

`inventory/default.yaml` locators: `/var/log/lab-endpoint/syslog.log`, `/var/log/lab-endpoint/udev.log`, `/var/log/lab-endpoint/process.log`.

`lab-journal-forward`: `DIR_CAP = 80 * 1024 * 1024`. Replace `_rotate` with:

```python
def _truncate_in_place(fh):
    fh.flush()
    os.fsync(fh.fileno())
    fh.truncate(0)
    fh.seek(0)
    return fh
```

When `LOG_PATH.stat().st_size >= ROTATE_BYTES`, `flush()` then `fh = _truncate_in_place(fh)`. Remove rename/`.1`.

`lab-usb-ingest`: `rotate_if_needed` becomes truncate:

```sh
truncate_if_needed() {
  path=$1
  sz=$(wc -c <"$path" | tr -d ' ')
  if [ "$sz" -ge 8388608 ]; then
    : >"$path"
  fi
}
```

Before each `append_json`, if `du -sb "$LOGDIR" | awk '{print $1}'` ≥ 83886080, skip the write. After `file_create` JSON, `exit 0`. Delete the `process_create` line and `exec /tmp/lab-usb-marker`. Update the file header comment: copy-only; does not exec.

`run-vm.sh`: after `OVERLAY=...` is set, `rm -f "$OVERLAY"` then the existing `qemu-img create`. `touch` all five log names. Symlink check includes all five. Keep `-nic none`.

- [ ] **Step 4: Tests PASS** then commit

```bash
git add inventory/default.yaml tests/estate/test_lab_host.py infra/endpoint/guest/lab-journal-forward infra/endpoint/guest/lab-usb-ingest infra/endpoint/run-vm.sh tests/infra/test_compose_safety.py tests/infra/test_journal_map.py
git commit -m "$(cat <<'EOF'
fix: pin endpoint locators, truncate 9p logs, and stop USB exec

EOF
)"
```

### Task 3: Split Vector Kafka sinks

**Files:**
- Modify: `infra/vector/vector.yaml`
- Modify: `tests/infra/test_vector_endpoint_sources.py`

- [ ] **Step 1: Failing tests**

Replace `test_kafka_sink_keeps_existing_and_appends_endpoint_remaps` with:

```python
def test_app_and_endpoint_sinks_split():
    cfg = _cfg()
    assert "kafka_raw" not in cfg["sinks"]
    app = cfg["sinks"]["kafka_raw_app"]
    end = cfg["sinks"]["kafka_raw_endpoint"]
    assert app["inputs"] == EXISTING_INPUTS
    assert app["buffer"]["max_size"] == 268435456
    assert app["buffer"]["when_full"] == "block"
    for _, remap, _ in NEW_REMAPS:
        assert remap in end["inputs"]
        assert remap not in app["inputs"]
    assert end["buffer"]["max_size"] == 268435456
    assert end["buffer"]["when_full"] == "drop_newest"
    for sink in (app, end):
        assert sink["topic"] == "soc.raw.v1"
        assert sink["key_field"] == "source_alias"
```

Keep `test_endpoint_sources_and_remaps` asserting `"source_alias": "lab-endpoint"`.

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/infra/test_vector_endpoint_sources.py -v`

- [ ] **Step 3: Implement**

Rename `sinks.kafka_raw` → two sinks as locked. Copy bootstrap/SASL/encoding/topic/key_field. App `when_full: block`. Endpoint `when_full: drop_newest`. Move the three endpoint remaps to `kafka_raw_endpoint.inputs`.

- [ ] **Step 4: Tests PASS** then commit

```bash
git add infra/vector/vector.yaml tests/infra/test_vector_endpoint_sources.py
git commit -m "$(cat <<'EOF'
fix: split Vector Kafka sinks so endpoint floods cannot block app tails

EOF
)"
```

### Task 4: Raw topic byte retention

**Files:**
- Modify: `infra/kafka-init.sh`
- Test: `tests/infra/test_compose_safety.py` (string contains)

- [ ] **Step 1: Failing test**

```python
def test_kafka_init_raw_retention_bytes():
    text = (REPO_ROOT / "infra" / "kafka-init.sh").read_text(encoding="utf-8")
    assert "soc.raw.v1" in text
    assert "retention.bytes=1073741824" in text
    assert "retention.ms=172800000" in text
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/infra/test_compose_safety.py::test_kafka_init_raw_retention_bytes -v`

- [ ] **Step 3: Implement**

After `create_topic soc.raw.v1 3 172800000`, alter so existing volumes pick it up:

```bash
"$BIN/kafka-configs.sh" --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" \
  --alter --entity-type topics --entity-name soc.raw.v1 \
  --add-config retention.bytes=1073741824
```

Keep `retention.ms` on create. No new topics. No partition change. No compact.

- [ ] **Step 4: PASS** then commit

```bash
git add infra/kafka-init.sh tests/infra/test_compose_safety.py
git commit -m "$(cat <<'EOF'
fix: cap soc.raw.v1 disk retention at 1 GiB

EOF
)"
```

### Task 5: Compose ingest image and service

**Files:**
- Create: `infra/ingest/Dockerfile`
- Modify: `infra/compose.yaml`
- Modify: `infra/.env.example` (comment: consumed by `soc-agent-ingest`)
- Modify: `tests/infra/test_compose_safety.py`

**Interfaces:**
- Consumes: `INGEST_BOOTSTRAP=kafka:9092`, `INGEST_REGISTRY_URL=http://karapace:8081`, SASL `ingest`
- Produces: compose service `soc-agent-ingest` running `python -m ingest run`

- [ ] **Step 1: Failing tests**

```python
def test_ingest_service_is_closed():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    svc = data["services"]["soc-agent-ingest"]
    assert svc.get("ports") in (None, [])
    assert svc.get("privileged") in (None, False)
    assert svc.get("network_mode") != "host"
    assert svc["mem_limit"] == "512m"
    assert svc["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in svc["security_opt"]
    volumes = [str(v) for v in svc.get("volumes", [])]
    for vol in volumes:
        assert "docker.sock" not in vol
        assert "monitor.sock" not in vol
        assert "endpoint/logs" not in vol
    env = svc["environment"]
    assert env["INGEST_BOOTSTRAP"] == "kafka:9092"
    assert env["INGEST_REGISTRY_URL"] == "http://karapace:8081"
    assert env["INGEST_SASL_USERNAME"] == "ingest"
    assert env["INGEST_GROUP_ID"] == "ingest-normalizer"
    depends = svc["depends_on"]
    assert depends["kafka"]["condition"] == "service_healthy"
    assert depends["kafka-init"]["condition"] == "service_completed_successfully"
    assert depends["karapace"]["condition"] == "service_healthy"
    dockerfile = (REPO_ROOT / "infra" / "ingest" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "python:3.12-bookworm@sha256:80f5d259a5969c86f6c92145d572de4a68c68e0edd28d4367dec0fb411b42af3" in dockerfile
    assert "pip install --no-cache-dir '.[kafka]'" in dockerfile
    assert "bind" not in dockerfile.lower()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/infra/test_compose_safety.py::test_ingest_service_is_closed -v`

- [ ] **Step 3: Implement**

`infra/ingest/Dockerfile`:

```dockerfile
FROM python:3.12-bookworm@sha256:80f5d259a5969c86f6c92145d572de4a68c68e0edd28d4367dec0fb411b42af3
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY inventory /app/inventory
RUN pip install --no-cache-dir '.[kafka]'
ENV INGEST_INVENTORY_PATH=/app/inventory/default.yaml
```

Compose (repo root is build context because compose lives in `infra/`):

```yaml
  soc-agent-ingest:
    build:
      context: ..
      dockerfile: infra/ingest/Dockerfile
    networks: [lab-net]
    security_opt: ["no-new-privileges:true"]
    cap_drop: [ALL]
    mem_limit: 512m
    pids_limit: 128
    restart: unless-stopped
    depends_on:
      kafka:
        condition: service_healthy
      kafka-init:
        condition: service_completed_successfully
      karapace:
        condition: service_healthy
    environment:
      INGEST_BOOTSTRAP: kafka:9092
      INGEST_REGISTRY_URL: http://karapace:8081
      INGEST_GROUP_ID: ingest-normalizer
      INGEST_SASL_USERNAME: ingest
      INGEST_SASL_PASSWORD: ${KAFKA_INGEST_PASSWORD}
      INGEST_INVENTORY_PATH: /app/inventory/default.yaml
    command: ["python", "-m", "ingest", "run"]
    healthcheck:
      test: ["CMD", "python", "-m", "ingest", "check"]
      interval: 15s
      timeout: 10s
      retries: 8
      start_period: 30s
```

No `ports:`. No bind-mount of `src`. No pip at runtime. No `docker.sock`. No endpoint logs. No `monitor.sock`.

- [ ] **Step 4: PASS** then commit

```bash
git add infra/ingest/Dockerfile infra/compose.yaml infra/.env.example tests/infra/test_compose_safety.py
git commit -m "$(cat <<'EOF'
feat: run the ingest normalizer as a compose service on lab-net

EOF
)"
```

### Task 6: Phase 0 docs (CI merge)

**Files:**
- Modify: `docs/ingest-layer.md` current-sources table note (sinks split); replace “If you want to see it move”
- Modify: `docs/agents/Flow.md` ingest CLI → compose `soc-agent-ingest`
- Modify: `infra/endpoint/README.md` USB no longer execs; overlay always recreated; smoke is syslog append + admin consume
- Modify: `docs/agents/ChangeLog.md`, `docs/agents/Decisions.md`

Operator smoke (document only, not pytest):

```sh
cd infra
docker compose up -d --build
# wait until soc-agent-ingest healthy
printf '%s\n' '{"timestamp":"2023-07-22T04:26:40.000000+00:00","source":"journal","priority":6,"identifier":"sshd","message":"operator smoke"}' >> ../infra/endpoint/logs/syslog.log
docker compose run --rm --no-deps \
  -e KAFKA_ADMIN_PASSWORD \
  kafka \
  bash -lc 'printf "security.protocol=SASL_PLAINTEXT\nsasl.mechanism=PLAIN\nsasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required username=\"admin\" password=\"%s\";\n" "$KAFKA_ADMIN_PASSWORD" > /tmp/admin.properties
  /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --command-config /tmp/admin.properties --topic soc.events.v1 --from-beginning --timeout-ms 15000 --group operator-verify-$$'
```

Success: Event JSON with `asset_id` `11111111-1111-4111-8111-111111111107`. Do not use `ingest emit`. Do not publish 9092/8081.

Delete the host `pip install` + `python -m ingest emit` happy path from `docs/ingest-layer.md`.

Decisions to record:

1. Compose `soc-agent-ingest` is the operator consumer; Kafka unpublished.
2. Two Vector sinks (app block / endpoint drop_newest).
3. Truncate-in-place at 8 MiB (inode-pin compatible); dir cap 80 MiB.
4. USB helper copy-only; no exec.
5. `run-vm.sh` always deletes overlay.
6. Commit all raw partitions after flush.
7. `soc.raw.v1` `retention.bytes=1GiB`.
8. In-guest auditd (Phase 1) supersedes “No auditd” for the guest only.

- [ ] **Step 1: Edit the docs listed above**
- [ ] **Step 2: Commit**

```bash
git add docs/ingest-layer.md docs/agents/Flow.md docs/agents/ChangeLog.md docs/agents/Decisions.md infra/endpoint/README.md docs/superpowers/plans/2026-08-23-linux-system-logs.md
git commit -m "$(cat <<'EOF'
docs: operator ingest path is compose plus admin consume

EOF
)"
```

**Phase 0 merge gate:** `pytest` green. Operator (optional): compose smoke above.

---

## Phase 1 — Slice C (CI merge)

Still `-nic none`. Add `audit.log` Vector source. Guest `lab-audit-forward` + hashed auditd debs.

### Audit keep algorithm (closed)

`lab-audit-forward` (Python, same style as `lab-journal-forward`) reads `/var/log/audit/audit.log` on qcow with a cursor file `/var/lib/lab-endpoint/audit.cursor` (byte offset). Writes **one** JSON object per kept **SYSCALL** to `/var/log/lab-endpoint/audit.log` with `O_NOFOLLOW`.

Keep iff:

- `arch=x86_64` (`arch=c000003e` in the SYSCALL line) **and**
- `success=yes` or `success=1` **and**
- syscall name ∈ `{execve, openat, unlink, unlinkat, rename, renameat, renameat2}` **and**
- if syscall is `openat`, the flags word has `O_CREAT` (octal `0100`)

Drop `execveat`. Parse-skip lines >262144 bytes before grouping. `command_line` = EXECVE `a0`..`aN` joined by space; omit key if no EXECVE record in the event id. `timestamp` = Slice B RFC3339 microseconds `+00:00` from `msg=audit(seconds.millis:serial)`. `source`=`auditd`. String fields UTF-8 truncated 16384 then `...`. Rate 20 keep-lines/s, drop-notice ≤1/s with `"identifier":"lab-audit-forward"`, fsync 32 or 1.0s, truncate 8 MiB, dir cap 80 MiB.

`auditd.conf` on qcow: `max_log_file=8`, `num_logs=2`, `max_log_file_action=ROTATE`. Journal allowlist **not** expanded. Dual USB `file_create` + a later audit `execve` (if Phase 0 still copies a file) is expected; USB no longer execs so live `execve` of the marker will not appear.

Audit rules (audit.rules, immutable after load):

```
-a always,exit -F arch=b64 -S execve -k lab-exec
-a always,exit -F arch=b64 -S openat -F a2&0100 -k lab-creat
-a always,exit -F arch=b64 -S unlink,unlinkat,rename,renameat,renameat2 -k lab-unlink
```

Exclude watches on `/var/log/lab-endpoint` and `/var/lib/lab-endpoint` if auditctl supports path exclude; otherwise rate-limit notices will dominate — keep the 20/s cap.

### Debs (Phase 1)

`run-vm.sh` downloads into `infra/endpoint/run/debs/`, verifies **SHA256**, copies onto the nocloud ISO. Guest `runcmd` `dpkg -i` in this order. Guest never `apt`. `cloud-init` stays `packages: []` / `package_update: false`.

| Order | URL | SHA256 |
|---|---|---|
| 1 | `https://deb.debian.org/debian/pool/main/a/audit/libaudit1_3.0.9-1_amd64.deb` | `30954df4b5a7c505661ba8ae5e6ea94f5805e408899fb400783bb166eb5ff306` |
| 2 | `https://deb.debian.org/debian/pool/main/a/audit/libauparse0_3.0.9-1_amd64.deb` | `ee3b6378d7145e88bf2d226a735b124b9b85d792bd1ead10da797427853894d3` |
| 3 | `https://deb.debian.org/debian/pool/main/t/tcp-wrappers/libwrap0_7.6.q-32_amd64.deb` | `cbce2669a3ba4d74cfdc52b14f38014893e23d85a33d109a3422c342eefc55f8` |
| 4 | `https://deb.debian.org/debian/pool/main/a/audit/auditd_3.0.9-1_amd64.deb` | `0d5a20ad6a0348a183fa3f2b58aff06ecd0e475cd9322c8bd4443db3e6454cd1` |

If `dpkg -i` reports a missing Depends, add **that exact** bookworm package from `Packages` (SHA256 from the same file) to this table in the same task. Do not apt.

### Task 7: Audit goldens

**Files:**
- Create: `tests/ingest/testdata/endpoint/audit.jsonl`
- Modify: `tests/ingest/test_normalizer.py` parametrize + redaction loop
- Modify: `tests/ingest/testdata/endpoint/README.md`

**audit.jsonl** — four lines, in order:

1. execve with `command_line` containing `Authorization: Bearer eyJhbGciOi.fake.token`
2. openat create of `/tmp/lab-creat`
3. unlink of `/tmp/lab-creat`
4. same as (1) plus `"source_alias":"soc-api"` inside a string field (spoof)

Each line is one compact JSON object with `"source":"auditd"` and Slice B `timestamp`.

- [ ] **Step 1: Write goldens + extend tests**

```python
@pytest.mark.parametrize(
    "name", ["syslog.jsonl", "udev.jsonl", "process.jsonl", "audit.jsonl"]
)
def test_endpoint_goldens_map_to_lab_host(name):
    ...
```

```python
    for name in ("syslog.jsonl", "process.jsonl", "audit.jsonl"):
```

README: payload `source=auditd` is a channel tag, not kernel proof.

- [ ] **Step 2: Run — goldens map FAIL until inventory grows in Task 8** (or add inventory in this task)

Add `endpoint-audit` to inventory **in this task** so goldens can pass without Vector yet:

```yaml
      - id: endpoint-audit
        kind: file
        locator: "/var/log/lab-endpoint/audit.log"
```

Update `test_lab_host.py` id set and locators dict.

- [ ] **Step 3: PASS** then commit

```bash
git add tests/ingest/testdata/endpoint/audit.jsonl tests/ingest/test_normalizer.py tests/ingest/testdata/endpoint/README.md inventory/default.yaml tests/estate/test_lab_host.py
git commit -m "$(cat <<'EOF'
test: add lab-endpoint audit goldens and inventory log source

EOF
)"
```

### Task 8: Vector + compose bind for audit.log

**Files:**
- Modify: `infra/vector/vector.yaml`, `infra/compose.yaml`, `tests/infra/test_vector_endpoint_sources.py`, `tests/infra/test_compose_safety.py`

- [ ] **Step 1: Tests**

Append to `NEW_REMAPS`:

```python
    ("file_lab_endpoint_audit", "wrap_lab_endpoint_audit", "/var/log/lab/lab-endpoint/audit.log"),
```

`FILE_BINDS` add:

`"./endpoint/logs/audit.log:/var/log/lab/lab-endpoint/audit.log:ro"`

`test_app_and_endpoint_sinks_split` already asserts every `NEW_REMAPS` remap is in the endpoint sink.

Remap VRL identical to syslog except it is a new transform id. `"source_alias": "lab-endpoint"` (not a new alias).

- [ ] **Step 2: FAIL then implement** then PASS then commit

```bash
git add infra/vector/vector.yaml infra/compose.yaml tests/infra/test_vector_endpoint_sources.py tests/infra/test_compose_safety.py
git commit -m "$(cat <<'EOF'
feat: tail lab-endpoint audit.log through the endpoint Vector sink

EOF
)"
```

### Task 9: `lab-audit-forward` + unit tests + guest install

**Files:**
- Create: `infra/endpoint/guest/lab-audit-forward`, `lab-audit-forward.service`, `audit.rules`, `auditd.conf`
- Modify: `infra/endpoint/guest/cloud-init.yaml`, `infra/endpoint/run-vm.sh`
- Create: `tests/infra/test_audit_forward.py` (SourceFileLoader, same pattern as journal_map)

Parser tests (exact):

```python
SAMPLE = (
    'type=SYSCALL msg=audit(1690000000.000000:1): arch=c000003e syscall=59 '
    'success=yes exit=0 a0=1 a1=2 a2=0 a3=0 items=1 ppid=1 pid=9 '
    'exe="/bin/ls"\n'
    'type=EXECVE msg=audit(1690000000.000000:1): argc=2 a0="/bin/ls" a1="-l"\n'
)

def test_keep_execve(mod):
    out = list(mod.records_from_text(SAMPLE))
    assert len(out) == 1
    assert out[0]["source"] == "auditd"
    assert out[0]["syscall"] == "execve"
    assert out[0]["command_line"] == "/bin/ls -l"
    assert out[0]["timestamp"] == "2023-07-22T04:26:40.000000+00:00"
```

Use the same timestamp conversion as journal_map (UTC). `msg=audit(1690000000.000000:1)` → `2023-07-22T04:26:40.000000+00:00`.

Also test: drop `success=no`; drop `execveat`; drop `openat` without `O_CREAT`; truncate `command_line` at 16384 bytes; `format` is one object + one `\n`.

`cloud-init.yaml` runcmd: install the new files from nocloud seed; `dpkg -i` debs in order; `systemctl enable --now auditd.service lab-audit-forward.service`; `touch` `audit.log`.

`run-vm.sh` seed copy list adds the new guest files and the debs. Download+SHA256 happens here (same pattern as qcow, but SHA256).

Tests: `lab-audit-forward` source contains `O_NOFOLLOW` and `source":"auditd"` / `'auditd'`. `run-vm.sh` contains each Phase 1 SHA256.

- [ ] Implement mapper so tests pass. Commit.

```bash
git add infra/endpoint/guest/lab-audit-forward infra/endpoint/guest/lab-audit-forward.service infra/endpoint/guest/audit.rules infra/endpoint/guest/auditd.conf infra/endpoint/guest/cloud-init.yaml infra/endpoint/run-vm.sh tests/infra/test_audit_forward.py
git commit -m "$(cat <<'EOF'
feat: forward allowlisted audit SYSCALL records onto audit.log

EOF
)"
```

### Task 10: Phase 1 docs

`docs/ingest-layer.md` sources table: add `file_lab_endpoint_audit`. Note: untrusted self-report; not kernel proof; IdP auth vs host syslog vs audit `execve`.

`docs/agents/Flow.md`: Vector also tails `audit.log`.

`docs/agents/ChangeLog.md` one bullet. `Decisions.md`: in-guest auditd; payload `source=auditd`; Vector still file tails.

Operator: delete is automatic now; `run-vm.sh`; confirm `audit.log` lines; compose already tails them.

- [ ] Commit docs.

**Phase 1 merge gate:** `pytest` green. Operator: QEMU + admin consume of an audit Event.

---

## Phase 2 — Slice D (CI merge)

USB exec already gated in Phase 0. Add NIC. Exclusive `net.log` writer. Disable sshd. DNS stub does not recurse.

### Net keep algorithm (closed)

One process `lab-net-forward` is the **only** writer of `net.log`.

It reads:

1. stdout of `nft -j monitor trace` (one subprocess). Keep objects whose destination is **not** in `{10.0.2.2, 10.0.2.3}` and that are the first packet of a flow (`ct` state new, or the first trace event for that tuple). Cap 20/s.
2. stdin pipe from `lab-dns-stub` (the stub prints one JSON object per query to stdout; systemd `StandardOutput=file` is forbidden — use a socketpair in the unit `ExecStart` wrapper so only `lab-net-forward` opens `net.log`).

JSON lines: `source=nft` or `source=dns`; Slice B timestamp; string fields 16384 cap; rate 20/s; truncate 8 MiB; dir cap 80 MiB; `O_NOFOLLOW`; fsync 32 or 1.0s. `json.dumps`, one object, one `\n`. No packet bytes. No second fd on `net.log`. No systemd-resolved query logging. No nft `log` / `LOG` / `printk` into kmsg.

nftables (trace only, never kmsg):

```
table inet lab {
  chain output {
    type filter hook output priority 0; policy accept;
    ip daddr { 10.0.2.2, 10.0.2.3 } accept
    meta nftrace set 1
  }
}
```

DNS stub `lab-dns-stub`: bind `127.0.0.1:53` UDP (and TCP if needed for systemd). Guest `resolv.conf` `nameserver 127.0.0.1`. Stub logs qname (and qtype) to the forwarder and replies **REFUSED**. It **does not** query `10.0.2.3`. cloud-init: `systemctl disable --now ssh.service systemd-resolved.service` (or stop resolved so it does not steal :53); write `/etc/resolv.conf` as a regular file `nameserver 127.0.0.1`.

### QEMU NIC (Phase 2 only)

Replace `-nic none` with exactly `-nic user,model=virtio,restrict=on`. No other `-nic`/`-netdev`. No `hostfwd`/`guestfwd`/`smb`/`tftp`. Guest not on `lab-net`. `exposure` stays `loopback`.

Update `test_run_vm_recreates_overlay_and_stays_nic_none` → `test_run_vm_user_nic_restrict_on`: assert `-nic user,model=virtio,restrict=on`, assert `-nic none` **absent**, assert `hostfwd` absent.

### Debs (Phase 2)

| Order | URL | SHA256 |
|---|---|---|
| 1 | `https://deb.debian.org/debian/pool/main/j/jansson/libjansson4_2.14-2_amd64.deb` | `3fc9742f9f1a37bcb9931df6074b4d1483419ef832ad5349f47323e75fc27864` |
| 2 | `https://deb.debian.org/debian/pool/main/n/nftables/libnftables1_1.0.6-2+deb12u2_amd64.deb` | `3a8223f9bfba99d97bf25296ac83de307ab036e1df63e5965f88809266851947` |
| 3 | `https://deb.debian.org/debian/pool/main/n/nftables/nftables_1.0.6-2+deb12u2_amd64.deb` | `966ff20ce58c17163a771c02ddbca264291408f94c512bd85dd18da0ebdbe88c` |

Same missing-Depends rule as Phase 1. DNS stub is Python on the seed ISO (no stub `.deb`).

### Task 11: Net goldens + inventory

**net.jsonl** — four lines:

1. `source=nft` NEW tcp to `1.2.3.4:443`
2. `source=dns` qname `Authorization.Bearer.eyJhbGciOi.fake.token.example.`
3. `source=dns` qname URL-encoded bearer `Authorization%3A%20Bearer%20eyJhbGciOi.fake.token.example.`
4. nft line containing `"source_alias":"soc-api"` spoof

Parametrize goldens + redaction loop include `net.jsonl`. Inventory add `endpoint-net`. Update `test_lab_host.py`.

Commit tests+inventory.

### Task 12: Vector + compose bind for net.log

Same pattern as audit. `NEW_REMAPS` + `FILE_BINDS` + remap `"source_alias": "lab-endpoint"` + endpoint sink inputs append `wrap_lab_endpoint_net`.

Commit.

### Task 13: `lab-net-forward` + `lab-dns-stub` + NIC + sshd off

Create guest files; systemd units; cloud-init enable; `run-vm.sh` seed copy; dpkg nft debs; tests analogous to audit (JSON shape, truncate, no recurse to `10.0.2.3` in stub source, `bind("127.0.0.1"`).

`lab-dns-stub` source must not contain `10.0.2.3`.

Commit.

### Task 14: Phase 2 docs

ingest-layer sources table + SLIRP honesty: `restrict=on` blocks guest TCP/UDP to host/internet; SLIRP still exists inside the operator QEMU process; guest DNS is the in-guest stub, not the operator resolver.

Flow.md: tails `net.log`. ChangeLog + Decisions: NIC `restrict=on`; exclusive net writer; no pcap; sshd disabled; payload `source` nft|dns untrusted.

**Phase 2 merge gate:** `pytest` green. Operator: `run-vm.sh`, generate DNS/nft lines, admin consume.

---

## NON-GOALS

- Slice E (Detect / Respond / Red team on the host, including in-scope USB)
- Lab-shop / lab-idp / lab-wallet / soc-api compose writers
- Host `ports:` on Kafka, Karapace, Vector, ingest
- `ingest emit` smoke; ingest Write on `soc.raw.v1`; ingest Read on `soc.events.v1`
- Event/`RawRecord` field add or topic/schema bump (`log_source_id` is v2)
- pcap / packet bytes / guest on `lab-net` / `hostfwd`
- Generating Vector from Estate locators
- Sysmon, Falco, osquery, Vector `journald` source
- Expanding the journal allowlist; nft `printk` into syslog
- Second writer on `process.log` or `net.log`
- Live sshd-over-network as an ingest path
- Splitting envelope aliases (`lab-endpoint-audit` / `lab-endpoint-net`)

---

## Council rulings

Seats: [Flaws](a1be43c0-428f-4589-a3bb-5d08ade75f64), [Scalability](74ee4d53-6cd2-4eb7-b73f-0e87af4a0c9b), [Kafka](3df03155-a238-44ce-896a-262e3a100764), [Vector](15e5ff8a-3270-4289-94ff-e6aee9596179), [Karapace](6bbd5433-8cd1-4fa0-a8aa-b8f8a16f8b09), [Cybersecurity](cba51aa2-cc24-4be7-aeea-29fdc21794f3), [Plan review](f37f079b-8a81-4df8-bb51-de881f3f89f1). Judge: [Final check](72da1d29-1634-4463-941d-b3b3c56426ee) — **APPROVE WITH CONDITIONS**.

| Demand | Ruling |
|---|---|
| Slice E in this ingest plan | **OUT.** Layers 3/5/7. |
| D in a later file | **This file, Phase 2.** Not the same merge as C. |
| USB exec + NIC | **USB exec off in Phase 0** before D. |
| Split aliases for raw isolation | **Single alias `lab-endpoint`.** Channel tag in payload. |
| One Vector sink | **Two sinks.** App block / endpoint drop_newest. |
| Rename-rotate vs inode-pin | **Truncate in place.** Change Slice B writers in Phase 0. |
| Dir cap 32 MiB | **80 MiB.** |
| `retention.bytes` | **1 GiB on `soc.raw.v1` only.** |
| `commit(batch[-1])` | **Commit all partitions.** Track 0. |
| Overlay pickup | **Always delete overlay.** |
| `emit` smoke / publish Kafka | **Forbidden.** Syslog append + admin consume on `lab-net`. |
| Envelope field / Karapace bump | **No.** FORWARD + `additionalProperties: false`. |
| Deb hash algorithm | **SHA256** from Debian Packages (qcow stays SHA512). |
| DNS stub recurse to 10.0.2.3 | **Forbidden.** In-guest stub, REFUSED. |
| pcap | **OUT.** |
