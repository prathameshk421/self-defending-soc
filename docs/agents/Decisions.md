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
