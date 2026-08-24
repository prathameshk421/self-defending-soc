# Decisions

Record real A-vs-B choices and why. Do not duplicate.

## 2026-08-22 — Agent docs layout

### Working memory under `docs/agents/` (not repo root)

Keep root `AGENTS.md` for tool discovery. Put ChangeLog / Decisions / Flow under `docs/agents/` so the repo root stays for contracts and code, not agent scratchpads.

## 2026-08-22 — Layer 1 Estate

### Stack: Python + Pydantic + pytest (not Postgres / Neo4j / FastAPI)

Layer 1 is an in-process library other layers can `import`. A HTTP surface waits until a separate process needs it.

### Source of truth: one YAML file (not a CMDB UI)

Lab inventory is small and reviewable in git. Schema validation + fail-closed load beats an admin UI for v1.

### Stable `asset_id` (UUID), never container ID / IP / compose name as FK

Containers recreate; cases and playbooks must keep pointing at the same asset. Runtime fields are optional and stale-able.

### `lab_id` on every asset even with one lab

Avoids merging two labs that both name a service `web` later. v1 uses `lab_id: default`.

### SOC split into multiple assets

`soc-api` (`never_isolate`), `soc-config` (restore only), `soc-agent-detect`, `soc-agent-red-team`. One blob would make isolate-API suicide and blast radius useless.

### Secrets: refs only in inventory

Credential *values* rejected at load. Red team and git must not get passwords from the catalog.

### No auto-register of shadow containers as respondable assets

Unknown runtime objects stay non-targets. Respond must use allowlisted handles from inventory.

## 2026-08-23 — Layer 2 Ingest

Plan was council-reviewed (cybersecurity, scalability, coding critics + judge); rulings in `docs/superpowers/plans/2026-08-23-ingest-layer-2.md`.

### confluent-kafka behind Protocol ports as an optional extra (not kafka-python / aiokafka)

kafka-python is under-maintained and aiokafka drags in asyncio the codebase does not use. But confluent-kafka is a C extension, so it lives behind `[kafka]` and one adapter module; the pipeline depends only on `ingest.ports` Protocols and CI never imports it.

### JSON Schemas generated from Pydantic (not hand-written)

Two sources of truth drift. `ingest schema export` regenerates; a contract test asserts byte-equality with the checked-in files.

### FORWARD compatibility in Karapace (not BACKWARD)

We control both producer and consumer; producer-led evolution with FORWARD prevents removing fields consumers rely on. `vN` in topic names is the breaking-change escape hatch.

### Deterministic UUIDv5 event ids (not uuid4 at normalize time)

At-least-once redelivery and future replay must yield the same id so downstream can dedup. Derived from lab_id + source_alias + observed_at + content hash, pre-redaction.

### SASL/PLAIN with per-principal ACLs, no TLS yet (not SCRAM or open PLAINTEXT)

Open Kafka is a forge/blind primitive for the in-scope red team, so auth + ACLs ship now. SCRAM needs credentials at KRaft storage-format time, which the apache/kafka image entrypoint cannot do; PLAIN gives identical authorization here. SCRAM+TLS is a recorded follow-up.

### Unknown alias is data, not an exception

Normalizer returns a tagged union (`Normalized | Unmapped | Invalid`); the pipeline maps variants to topics. Unmapped/DLQ records carry the redacted original envelope + reason header so they are reprocessable, never a raw-secret swamp.

### httpx (not requests) for the Karapace client

`httpx.MockTransport` lets tests fake the registry without adding a mocking library, matching the repo's hand-rolled-fakes convention.

## 2026-08-24 — Linux system logs (lab-endpoint)

### Three file binds + 9p of `infra/endpoint/logs` only (not `lab-logs`, not a Vector directory bind)

A guest symlink in a directory bind can follow into shop/API log files inside Vector. File binds pin inodes. The QEMU 9p share is still the directory (guest must write files) but Vector never opens that directory.

### Host logs stay `source_type=file`; payload is untrusted self-report

The journal allowlist is a volume/noise filter for the honest forwarder, not authenticity. Detect must not treat `identifier` as proof of origin.

### `lab-endpoint` is watch-only / `respond_allowed=false` / `red_team_skip=true`

QEMU lives on the operator workstation. No `qemu_vm` containment handle.

### Event schema stays v1; payload `source` is the channel tag (`journal` vs `usb-helper`)

So later OS-wide `file_create` (slice C) is not confused with USB helper confession.

### CI goldens are the merge contract; live QEMU is operator verification

### No auditd/Sysmon. `process.log` is helper-authored copy/exec confession

Superseded for the **guest only** by in-guest auditd in [`2026-08-24-linux-audit-net-and-compose-ingest.md`](../superpowers/plans/2026-08-24-linux-audit-net-and-compose-ingest.md) Phase 1. Vector still has no auditd/journald source.

### This plan supersedes the USB-only endpoint plan

## 2026-08-24 — Compose ingest + endpoint writers (Phase 0)

### Compose `soc-agent-ingest` is the operator consumer; Kafka unpublished

The normalizer runs on `lab-net`. No Kafka/Karapace/Vector/ingest `ports:`. Operator smoke is syslog append + admin consume, not host `pip install` + `ingest emit`.

### Two Vector sinks (app block / endpoint drop_newest)

Endpoint floods must not stall shop/idp/wallet/api tails. Same topic `soc.raw.v1`, `key_field: source_alias`.

### Truncate-in-place at 8 MiB; dir cap 80 MiB

Rename-rotate would break Vector inode-pin on 9p. Same inode (`ftruncate` / `: >file`). No `.log.1` on 9p.

### USB helper copy-only; no exec

Copies the marker and writes `file_create` only. Slice B `process.jsonl` goldens stay fixtures.

### `run-vm.sh` always deletes overlay

Journal cursor on qcow is lost every boot. No instance-id bump.

### Commit all raw partitions after flush

`commit(batch[-1])` dropped other partitions in a mixed batch. Adapter commits max(offset)+1 per `(topic, partition)`.

### `soc.raw.v1` `retention.bytes=1GiB`

Time retention (48h) stays. Byte cap so an endpoint flood cannot fill the broker disk.

### In-guest auditd (Phase 1) supersedes “No auditd” for the guest only

Vector still file-tails. Envelope `source_alias` stays `lab-endpoint`. Payload `source=auditd` is a channel tag, not kernel proof.

## 2026-08-24 — In-guest auditd (Phase 1)

### In-guest auditd; Vector still file tails `audit.log`

OS-wide exec/file keep-filter runs in the guest (`lab-audit-forward`). Vector has no auditd source. Envelope alias stays `lab-endpoint`.

### Payload `source=auditd` is untrusted self-report

Detect must not treat alias or `source` as kernel proof. Guest JSON can be forged.
