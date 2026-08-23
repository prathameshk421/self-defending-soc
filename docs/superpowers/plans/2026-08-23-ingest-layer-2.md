# Layer 2 Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

> This plan is the output of a council review: a draft was critiqued by three
> adversarial reviewers (cybersecurity, scalability/reliability, coding quality)
> and a judge synthesized their findings into this final version. Rulings that
> deferred work are recorded under NON-GOALS.

**Goal:** Deliver a tamper-resistant telemetry pipeline: Vector collects estate log sources and authenticated webhooks, wraps records in a provenance-locked raw envelope, and a Python normalizer turns them into schema-governed events on Kafka — with at-least-once delivery, deterministic IDs, and fail-closed schema sync.

**Architecture:** Vector (file tails + HTTP listeners) → `soc.raw.v1` → `ingest` normalizer (resolve alias via Estate, redact, validate) → `soc.events.v1` | `soc.ingest.unmapped.v1` | `soc.ingest.dlq.v1`. Karapace governs the event schema. Kafka is SASL-authenticated with per-principal ACLs; only Vector writes raw, only the normalizer writes events.

**Tech Stack:** Python 3.12+, Pydantic v2, httpx, confluent-kafka (optional extra), pytest; Kafka (KRaft, single node), Karapace, Vector; docker compose.

## Package layout

| File | Responsibility |
|------|----------------|
| `src/ingest/errors.py` | `IngestError` base; `ConfigInvalid`, `SchemaRegistryError`, `SchemaIncompatible`. Does not subclass `EstateError`. |
| `src/ingest/models.py` | Pydantic v2 `RawRecord` and `Event` (frozen, `extra="forbid"`, tz-aware datetimes) plus deterministic `event_id` derivation. |
| `src/ingest/config.py` | `IngestConfig` built from hand-rolled `os.environ` reads (`INGEST_*`); fail-closed validation; compose-friendly defaults. |
| `src/ingest/redact.py` | Regex + entropy redactor for free text: Authorization headers, JWTs, AWS-style keys, connection-string passwords, key=value secrets, high-entropy tokens. |
| `src/ingest/normalizer.py` | Pure `normalize(raw_bytes, resolver, ...) -> Normalized \| Unmapped \| Invalid` (frozen dataclasses). No I/O, no topic knowledge. Strips control chars; payload content can never set envelope metadata; redacts before returning any variant. `NotFound`/`AmbiguousAlias` → `Unmapped`. |
| `src/ingest/ports.py` | `typing.Protocol`s `Producer`/`Consumer` plus `RawMessage`/`DeliveryFailure` dataclasses — confluent types never leak. |
| `src/ingest/pipeline.py` | Consume → normalize → produce loop against the Protocols only; commit protocol below; never crash-loops on a poison record. |
| `src/ingest/schema_gen.py` | Canonical JSON Schema generation from the Pydantic models; packaged-schema loading via `importlib.resources`. |
| `src/ingest/schema_sync.py` | Karapace client (httpx): set FORWARD compat, register if absent, verify remote equals local, bounded retry with backoff, then fail closed. |
| `src/ingest/schemas/*.json` | Generated schema files, checked in as package data. Never hand-edited. |
| `src/ingest/kafka_adapter.py` | confluent-kafka wrappers implementing the ports. Imported only on CLI `run`/`emit` paths. |
| `src/ingest/cli.py`, `__main__.py` | Mirrors estate: `build_parser()` / `main(argv) -> int`; subcommands `run`, `check`, `emit`, `schema export`; errors → stderr + exit 1; console script `ingest`. |

`pyproject.toml`: add `httpx`; optional extra `kafka = ["confluent-kafka>=2.3"]`. CI installs base + dev only — tests never import confluent-kafka.

## Envelopes

**RawRecord** (produced by Vector, subject `soc.raw.v1-value`): `lab_id: str`, `source_alias: str`, `source_type: "file" | "webhook"`, `collector: str`, `raw: str`, `observed_at: datetime` (tz-aware).

**Event** (subject `soc.events.v1-value`): `event_id` — UUIDv5 over `sha256(lab_id | source_alias | observed_at | raw)` under a fixed ingest namespace UUID, so reprocessing yields the same ID; `lab_id`; `asset_id`; `source_alias`; `source_type`; `occurred_at: datetime | None` (best-effort parse from payload; failure is not fatal); `received_at` (= `observed_at`); `payload: str` (redacted raw); `schema_version: int` (also sent as a Kafka header).

Unmapped/DLQ messages carry the full original (redacted) `RawRecord` plus `reason` headers, so later reprocessing needs nothing else.

## Topics

| Topic | Key | Partitions | Retention | Purpose |
|-------|-----|------------|-----------|---------|
| `soc.raw.v1` | `source_alias` | 3 | 48h | Raw envelopes from Vector; per-source ordering. |
| `soc.events.v1` | `asset_id` | 3 | 7d | Normalized events; replayable source of truth for Layer 3; per-asset ordering. |
| `soc.ingest.unmapped.v1` | `source_alias` | 1 | 72h | Alias did not resolve (or was ambiguous); redacted. |
| `soc.ingest.dlq.v1` | `source_alias` | 1 | 72h | Any normalize/validation failure; redacted; never blocks the pipeline. |

Auto topic creation disabled; topics created by `kafka-init` with explicit `retention.ms`. Versioning: `vN` in the name marks breaking changes (new topic); FORWARD compatibility governs evolution within a name.

## Pipeline commit protocol (at-least-once)

Producer: `enable.idempotence=true`, `acks=all`. Loop: poll a bounded batch → normalize each (any unexpected exception routes that record to the DLQ — the pipeline never dies on a poison pill) → produce each result to its variant topic → `flush()` and collect delivery reports → only if every message is confirmed delivered, commit the batch offsets; on any delivery failure, commit nothing and reprocess (dedup downstream via deterministic `event_id`). Bounds: broker `message.max.bytes` ≈ 1 MB; normalizer rejects payloads over `INGEST_MAX_PAYLOAD_BYTES` to the DLQ. `group.id` comes from config so a second stateless normalizer is possible later.

## Schema generation and Karapace sync

Schemas are never hand-written: `ingest schema export` regenerates the JSON files from the Pydantic models; a contract test asserts the checked-in files byte-equal the generated output. On startup (`run` and `check`): ensure subjects `soc.raw.v1-value` and `soc.events.v1-value` have FORWARD compatibility, register the local schema if the subject is absent or differs (the registry enforces compatibility; a rejected registration raises `SchemaIncompatible`). Connection errors retry with exponential backoff (bounded) to survive cold-start ordering, then fail closed.

## Vector configuration essentials

- **File sources:** one per estate `log_source`, each feeding a transform with a **static** `source_alias` — provenance-locked, never derived from line content.
- **HTTP listeners:** one `http_server` source per sender (webhooks, red-team findings), each with its own bearer token from env and a hardcoded `source_alias` — identity is bound to the credential/listener, giving attribution and per-sender revocation. Body size capped via `max_request_bytes`.
- **Transform (VRL):** build the `RawRecord` envelope; strip control characters; treat content as opaque — no field of the body may override envelope metadata.
- **Sink:** Kafka with the `vector` SASL principal, key = `source_alias`, disk buffer (`when_full: block`), file-source checkpoints on a named volume.

## Compose (`infra/compose.yaml`)

All images pinned by sha256 digest; all services get `no-new-privileges`, `cap_drop: [ALL]`, memory/pids limits, healthchecks, `depends_on: condition: service_healthy`, no docker.sock mounts; `read_only` where the image tolerates it.

1. **kafka** — single-node KRaft; SASL/PLAIN on broker and controller listeners; `StandardAuthorizer`; `allow.everyone.if.no.acl.found=false`; auto topic creation off; named data volume. *Judge amendment:* SASL/PLAIN instead of SCRAM — KRaft requires SCRAM credentials at storage-format time, which the `apache/kafka` image entrypoint does not support; PLAIN provides identical per-principal authentication and ACL enforcement here, and the SCRAM+TLS upgrade is a recorded follow-up.
2. **kafka-init** — one-shot: creates topics with retention; applies ACLs: `vector` writes `soc.raw.v1` only; `ingest` reads `soc.raw.v1`, writes `soc.events.v1`/unmapped/dlq; `karapace` limited to `_schemas`; nothing else may write `soc.events.v1`.
3. **karapace** — schema registry backed by Kafka with its own principal.
4. **vector** — config read-only, log paths read-only, buffer/checkpoint volume.

Credentials via env; `infra/.env.example` documents them with lab-only placeholders.

## Inventory additions

New `soc_service` asset kind (Estate model vocabulary extension, no behavior change). Assets: `soc-kafka` (never_isolate — isolating it blinds the SOC), `soc-karapace`, `soc-vector`, `soc-agent-ingest` (soc_agent, contain_with_degraded_mode). Edges: vector/karapace/agent `depends_on` kafka; agent `depends_on` karapace; agent `emits_logs_as` soc-api. Credential refs are pointers (`env:`) only.

## Config (env vars, `INGEST_` prefix)

`INGEST_BOOTSTRAP`, `INGEST_GROUP_ID` (default `ingest-normalizer`), `INGEST_SASL_USERNAME`, `INGEST_SASL_PASSWORD`, `INGEST_REGISTRY_URL`, `INGEST_INVENTORY_PATH` (default repo `inventory/default.yaml`), `INGEST_LAB_ID` (default `default`), `INGEST_MAX_PAYLOAD_BYTES` (default 262144). Missing/invalid → `ConfigInvalid`, exit 1.

## Tests (`tests/ingest/`, no live services, hand-rolled fakes)

1. `test_models.py` — field validation, tz-aware datetimes, frozen/extra-forbid.
2. `test_schema_contract.py` — checked-in JSON schemas byte-equal generated output.
3. `test_normalizer.py` — resolved alias → `Normalized`; unknown/ambiguous → `Unmapped` with reason; oversized/undecodable → `Invalid`; control chars stripped; payload cannot alter envelope metadata (spoof case); timestamp parse failure still yields an Event.
4. `test_redact.py` — bearer headers, JWTs, connection strings, high-entropy tokens redacted on realistic samples; benign text untouched.
5. `test_event_id.py` — deterministic across runs; distinct for distinct inputs.
6. `test_pipeline.py` — fake Producer/Consumer: commit only after all deliveries confirmed; simulated delivery failure → no commit and reprocess; resolver blow-up → DLQ + commit (no crash-loop); correct topic/key/headers per variant.
7. `test_schema_sync.py` — httpx `MockTransport`: registers when absent, verifies when present, incompatible → fail closed, bounded retry then failure.
8. `test_config.py` — env parsing, defaults, fail-closed on missing/invalid.
9. `test_cli.py` — parser, exit codes, `schema export` output, errors to stderr.
10. `test_layering.py` — `estate` modules never import `ingest`.

## NON-GOALS / deferred (recorded, not dropped)

- **TLS/mTLS and SCRAM on Kafka; TLS on the Vector HTTP source** — PLAIN auth blocks the forge/consume primitive now; encryption defends on-path sniffing, which on a single-host docker bridge requires an already-elevated attacker. Follow-up when the red-team layer lands.
- **HMAC-signed webhooks + rate limiting** — per-listener tokens give attribution and revocation at lab scale.
- **Image signature verification (cosign)** — digest pinning covers drift; signing needs registry infra.
- **Inventory hot-reload and `reprocess-unmapped` CLI** — container restart is an acceptable refresh; unmapped messages already carry everything needed.
- **`replay --from-timestamp` CLI** — no consumer exists yet; `soc.events.v1` is documented as the replayable source of truth and `group.id` is parameterized.
- **DLQ-rate alerting** — belongs to Layer 3 Detect.

## docs/agents updates

- `ChangeLog.md`: Layer 2 package, topics, schema subjects, inventory additions, `soc_service` kind.
- `Decisions.md`: confluent-kafka behind Protocol ports as optional extra; generated schemas; FORWARD compat; SASL/PLAIN-without-TLS phasing; httpx for MockTransport-based testing; deterministic UUIDv5 event IDs.
- `Flow.md`: Vector → `soc.raw.v1` → normalizer → `soc.events.v1`/unmapped/dlq, with schema_sync gating startup.
