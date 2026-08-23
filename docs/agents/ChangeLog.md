# ChangeLog

Append-only. One dated bullet when behavior, schema, inventory, or public APIs change.

## 2026-08-22

- Move agent working memory to `docs/agents/` (`ChangeLog.md`, `Decisions.md`, `Flow.md`). Root `AGENTS.md` remains the contract and points here.
- Bootstrap Layer 1 estate catalog (YAML inventory, Pydantic models, fail-closed loader, query API, CLI) and agent working files. Paths: `src/estate/`, `inventory/default.yaml`, `tests/estate/`, `pyproject.toml`, `docs/agents/`.

## 2026-08-23

- Layer 2 Ingest: new `src/ingest/` package (envelope models, redactor, tagged-union normalizer, at-least-once pipeline, Karapace schema sync, CLI `ingest run|check|emit|schema export`), generated JSON Schemas as package data, `infra/compose.yaml` (Kafka KRaft + SASL/PLAIN + ACLs, Karapace, Vector), `tests/ingest/`. Topics: `soc.raw.v1`, `soc.events.v1`, `soc.ingest.unmapped.v1`, `soc.ingest.dlq.v1`; subjects `soc.raw.v1-value`, `soc.events.v1-value` (FORWARD).
- Estate: new `soc_service` asset kind. Inventory gains `soc-kafka`, `soc-karapace`, `soc-vector`, `soc-agent-ingest` plus dependency edges (self-inclusion of ingest infra).
- New deps: `httpx` (core), `confluent-kafka` behind optional `[kafka]` extra; new console script `ingest`.

## 2026-08-24

- Estate: new `lab_host` asset kind. Inventory gains `lab-endpoint` (uuid `11111111-1111-4111-8111-111111111107`) with three endpoint log sources.
- Estate loader: `lab_host` assets with empty `log_sources` are rejected with `InventoryInvalid`.
- Vector tails `lab-endpoint` `syslog.log`, `udev.log`, and `process.log` with hardcoded alias `lab-endpoint`. Compose inode-pins those three files into Vector (not a directory bind).
- Guest journal remap lives in `infra/endpoint/guest/journal_map.py` (tests load it via SourceFileLoader; ingest/estate do not import it).
