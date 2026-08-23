# ChangeLog

Append-only. One dated bullet when behavior, schema, inventory, or public APIs change.

## 2026-08-22

- Move agent working memory to `docs/agents/` (`ChangeLog.md`, `Decisions.md`, `Flow.md`). Root `AGENTS.md` remains the contract and points here.
- Bootstrap Layer 1 estate catalog (YAML inventory, Pydantic models, fail-closed loader, query API, CLI) and agent working files. Paths: `src/estate/`, `inventory/default.yaml`, `tests/estate/`, `pyproject.toml`, `docs/agents/`.
