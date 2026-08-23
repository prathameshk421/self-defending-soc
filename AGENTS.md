# Agent contract

Rules for any AI agent working in this repo. Prefer silence over noise.

Working memory lives under [`docs/agents/`](docs/agents/). This file stays at the repo root so tools can find it.

## After every finished task

Open and check these files. Update only when required. If nothing would be false or incomplete, **do not write**.

1. [docs/agents/ChangeLog.md](docs/agents/ChangeLog.md)
2. [docs/agents/Decisions.md](docs/agents/Decisions.md)
3. [docs/agents/Flow.md](docs/agents/Flow.md)
4. [AGENTS.md](AGENTS.md) (this file)

## When to update each file

| File | Update when | Do not update for |
|------|-------------|-------------------|
| `docs/agents/ChangeLog.md` | Behavior, schema, inventory, or public API changed | Running tests, restating git log, typo-only edits |
| `docs/agents/Decisions.md` | A real A-vs-B choice was made and is not already recorded | “We used X because X is popular,” duplicate decisions |
| `docs/agents/Flow.md` | Control flow of a loaded component changed (who calls whom) | Tutorials, typo fixes, unrelated refactors |
| `AGENTS.md` | Agent process or rules themselves changed | Routine feature work |

## Do not add dumb stuff

- No emoji, motivational blurbs, or “as an AI I…”
- No dumping entire file diffs into these docs
- No logging every thought or step
- Prefer silence over noise

## Layer boundaries

Layer 1 (Estate) defines and serves the asset catalog. Do not sneak ingest, detect, respond, recover, or red-team execution into Estate.
