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
       → lab_host log_sources rule
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

## Ingest (Layer 2)

```
Vector (file tails + authed HTTP listeners; source_alias set per source)
  → Kafka soc.raw.v1  (key = source_alias)

CLI (python -m ingest run)
  → ingest.cli.main
  → ingest.config.load_config (fail closed)
  → estate.loader.load_inventory → estate.query.Estate  (alias resolver)
  → ingest.schema_sync.sync_schemas (Karapace; FORWARD; retry then fail closed)
  → ingest.pipeline.Pipeline.run_forever
       → consumer.poll soc.raw.v1
       → ingest.normalizer.normalize
            → decode / size check → Invalid
            → RawRecord validate  → Invalid
            → strip control chars + ingest.redact.redact
            → Estate.resolve_alias → Unmapped on NotFound/AmbiguousAlias
            → Event (deterministic event_id)
       → produce: Normalized→soc.events.v1 (key=asset_id)
                  Unmapped→soc.ingest.unmapped.v1, Invalid→soc.ingest.dlq.v1
       → flush; commit offsets only if all deliveries confirmed
```

### Failure points

1. **Config** — `ConfigInvalid` in `load_config` (before anything runs).
2. **Inventory** — `InventoryInvalid` from the estate loader.
3. **Registry** — `SchemaRegistryError` / `SchemaIncompatible` in `schema_sync` (startup gate).
4. **Per record** — never fatal: routed to unmapped or DLQ; poison pills cannot crash the loop.
5. **Delivery** — failed flush blocks offset commit; batch is redelivered (dedup via event_id).
