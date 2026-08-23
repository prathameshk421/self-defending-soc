# Flow

Control-flow map for debugging “did this break before or after X.” Update only when call chains change.

## Estate (Layer 1)

```
CLI (python -m estate)
  → estate.cli.main
  → estate.loader.load_inventory(path)
       → parse YAML
       → reject secret-shaped values
       → Pydantic Inventory validation
       → uniqueness checks (lab_id+name, aliases)
       → red-team surface rules
  → estate.query.Estate(inventory)
       → get / list / neighbors / resolve_alias / assert_respond_target
```

### Query entry points

| Function | Role |
|----------|------|
| `Estate.get(asset_id)` | Lookup by immutable id |
| `Estate.list(**filters)` | Filter; default excludes `retired` |
| `Estate.neighbors(asset_id, …)` | Declared graph walk for blast radius |
| `Estate.resolve_alias(lab_id, alias)` | Ingest mapping; no auto-create |
| `Estate.assert_respond_target(asset_id)` | Fail-closed respond policy check |

### Failure points (before vs after)

1. **YAML / schema / uniqueness** — `InventoryInvalid` in loader (before query exists).
2. **Missing asset / alias** — `NotFound` in query.
3. **Respond policy** — `RespondForbidden` in `assert_respond_target` (after get succeeds).
