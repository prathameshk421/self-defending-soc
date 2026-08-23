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
