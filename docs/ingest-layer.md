# Ingest layer (Layer 2) — a guided tour

This is the learning doc for Layer 2. If you are new to Kafka, Vector, or schema registries, start here. Terms are defined the first time they appear; there is also a [glossary](#glossary) at the end.

Code lives in `src/ingest/`. Infra lives in `infra/`. The asset catalog that ingest looks up against is Layer 1 Estate (`src/estate/`, `inventory/default.yaml`).

---

## Why this layer exists

This project is a **self-defending SOC lab**. A SOC (Security Operations Center) is the function that watches systems for attacks and decides what to do about them.

The loop is:

```
Estate (what we protect)
  → Ingest (bring signals in)
    → Detect (spot attacks)
      → Investigate (build a case)
        → Human approves
          → Respond (stop the attack)
            → Recover (only if stopping failed or damage already exists)
```

Ingest is the **front door**. Lab apps, this SOC’s own API, and the red team all emit logs and webhooks. Ingest’s job is to turn that messy incoming firehose into a **clean, attributed, redacted event stream** that Detect can trust.

Ingest does **not** decide “this is an attack.” It only answers:

1. What arrived?
2. Which known asset did it come from?
3. Is the envelope valid?
4. Did we strip secrets before anyone else sees it?

---

## The 30-second picture

```
Lab logs / webhooks / red-team findings
        │
        ▼
   Vector (collector)
   wraps each line in a RawRecord
   (source_alias is hardcoded per source — never taken from the log line)
        │
        ▼
   Kafka topic soc.raw.v1
        │
        ▼
   ingest pipeline  (compose service soc-agent-ingest)
        │  decode, validate, redact, resolve alias via Estate
        │
        ├── known asset     →  soc.events.v1            (Detect reads this)
        ├── unknown alias   →  soc.ingest.unmapped.v1
        └── broken record   →  soc.ingest.dlq.v1
```

Karapace (a schema registry) sits beside Kafka and refuses to let the pipeline start if the event shapes have drifted incompatibly.

Think of it as a post office:

| Piece | Everyday analogy |
|---|---|
| Vector | The mail clerk who puts each letter in a stamped envelope and writes the return address from the *counter they were standing at*, not from whatever the letter claims |
| Kafka topic | A labeled mail slot that many senders and receivers share |
| Kafka message key | The sorting stamp that keeps mail from the same sender in order |
| Ingest pipeline | The clerk who opens the envelope, blacks out secrets, looks up the return address in the employee directory (Estate), and either files it or puts it in the “unknown sender” / “damaged mail” bin |
| Karapace | The rulebook that says “an Event must always have these fields” |

---

## A log line’s journey (walk this once)

Suppose `lab-shop` writes this line to `/var/log/lab/lab-shop/access.log`:

```
GET /checkout 200 Authorization: Bearer eyJhbGciOi...
```

### 1. Vector notices the new line

**Vector** is an edge collector: a small program that tails files and listens for HTTP posts, then ships records onward. It does not analyze attacks. It only collects.

In `infra/vector/vector.yaml` there is a *file source* pointed at that path, wired to a *transform* that hardcodes:

```
source_alias = "lab-shop"
source_type  = "file"
collector    = "vector"
```

The log line itself can scream `"source_alias": "lab-idp"` all it wants. Vector ignores that. Attribution comes from **which file / which HTTP listener** the record arrived on. That is called **provenance locking**: we lock “who sent this” to the collection path, not to content an attacker can forge.

Vector also has two HTTP listeners (webhooks):

- port 9000, bearer token `VECTOR_WEBHOOK_TOKEN` → alias `webhook-generic`
- port 9001, bearer token `VECTOR_REDTEAM_TOKEN` → alias `soc-agent-red-team`

Same rule: identity is the listener + token, not a field in the JSON body.

### 2. Vector publishes a RawRecord onto Kafka

Vector’s Kafka sink writes JSON like this to topic `soc.raw.v1`, with **key** = `lab-shop`:

```json
{
  "lab_id": "default",
  "source_alias": "lab-shop",
  "source_type": "file",
  "collector": "vector",
  "raw": "GET /checkout 200 Authorization: Bearer eyJhbGciOi...",
  "observed_at": "2026-08-23T15:01:02.123456+00:00"
}
```

That JSON is a **RawRecord** (defined in `src/ingest/models.py`). It is an *envelope*: metadata around an opaque `raw` string. The pipeline treats `raw` as untrusted content.

### 3. The ingest process consumes it

`python -m ingest run` starts a loop (`src/ingest/pipeline.py`):

1. Load config from `INGEST_*` env vars (fail closed if required ones are missing).
2. Load Estate inventory so aliases can be resolved.
3. Sync JSON Schemas with Karapace (fail closed if incompatible).
4. Poll Kafka for a batch of raw messages (up to 100).
5. For each message, call `normalize(...)`.
6. Produce the result to the matching topic.
7. **Flush** (wait until Kafka confirms every produce).
8. Only then **commit every partition in the batch** (max offset+1 per `(topic, partition)`). If any produce failed, commit nothing and try the batch again.

### 4. Normalize decides the fate

`normalize` (`src/ingest/normalizer.py`) is pure logic: no Kafka, no network. It returns one of three frozen results:

| Result | Meaning | Destination topic |
|---|---|---|
| `Normalized` | Envelope valid, alias maps to exactly one asset | `soc.events.v1` |
| `Unmapped` | Envelope valid, but Estate does not know the alias (or two assets share it) | `soc.ingest.unmapped.v1` |
| `Invalid` | Too big, not UTF-8, not a RawRecord, or the normalizer itself blew up | `soc.ingest.dlq.v1` |

For our shop line:

1. Size check (default max 256 KiB).
2. Decode as UTF-8.
3. Parse as `RawRecord` (unknown extra fields are rejected).
4. Strip control characters from `raw` (nulls, ANSI color codes, `\r`).
5. **Redact** secrets. The bearer token becomes `[REDACTED]`.
6. `Estate.resolve_alias("default", "lab-shop")` → asset UUID `11111111-1111-4111-8111-111111111102`.
7. Build an `Event` with a deterministic `event_id`.

The Event that lands on `soc.events.v1` looks like:

```json
{
  "event_id": "a-uuid-v5-always-the-same-for-this-input",
  "lab_id": "default",
  "asset_id": "11111111-1111-4111-8111-111111111102",
  "source_alias": "lab-shop",
  "source_type": "file",
  "occurred_at": null,
  "received_at": "2026-08-23T15:01:02.123456+00:00",
  "payload": "GET /checkout 200 Authorization: Bearer [REDACTED]",
  "schema_version": 1
}
```

`occurred_at` is a best-effort parse of `@timestamp` / `timestamp` / `time` / `ts` inside a JSON payload. A plain access-log line has none of those, so it stays `null`. Failure to parse is never fatal.

The Kafka **key** on this Event is `asset_id`, so every event for the shop stays in order for that asset.

Detect (Layer 3, not built yet) will read `soc.events.v1`. That is the contract: Detect never sees raw Vector output.

---

## The pieces, one by one

### Vector — the collector

Config: `infra/vector/vector.yaml`. Runs as the `vector` service in `infra/compose.yaml`.

| Vector term | Meaning here |
|---|---|
| **Source** | Where data comes from (a file tail, or an HTTP listener) |
| **Transform (remap)** | A small script that *rebuilds* the record as a RawRecord. Written in VRL (Vector Remap Language) |
| **Sink** | Where data goes. Two Kafka sinks share topic `soc.raw.v1`: `kafka_raw_app` (shop/idp/wallet/api/webhooks/redteam) and `kafka_raw_endpoint` (lab-endpoint remaps) |
| **Disk buffer** | App sink: 256 MiB, `when_full: block`. Endpoint sink: 256 MiB, `when_full: drop_newest` so host floods cannot stall app tails |
| **Checkpoint** | Vector remembers how far it has read each file so a restart does not re-tail from the beginning |

Current sources:

| Source | Type | Hardcoded `source_alias` |
|---|---|---|
| `file_lab_shop` | file tail | `lab-shop` |
| `file_lab_idp` | file tail | `lab-idp` |
| `file_lab_wallet` | file tail | `lab-wallet` |
| `file_soc_api` | file tail | `soc-api` |
| `http_webhooks` | HTTP :9000 | `webhook-generic` |
| `http_redteam` | HTTP :9001 | `soc-agent-red-team` |
| `file_lab_endpoint_syslog` | file tail | `lab-endpoint` |
| `file_lab_endpoint_udev` | file tail | `lab-endpoint` |
| `file_lab_endpoint_process` | file tail | `lab-endpoint` |
| `file_lab_endpoint_audit` | file tail | `lab-endpoint` |
| `file_lab_endpoint_net` | file tail | `lab-endpoint` |

Host endpoint payloads are guest-authored self-report (untrusted). IdP `auth.log` is application identity; `lab-endpoint` `syslog.log` with `identifier=sshd` or `sudo` is host OS auth; payload `source=auditd` is a channel tag, not kernel proof. An IdP login, a host sshd syslog line, and an audit `execve` are different signals. Payload `source=nft` / `source=dns` is likewise untrusted. Never add a host `auth.log` tail.

QEMU Phase 2 NIC is `-nic user,model=virtio,restrict=on`: guest TCP/UDP to the operator host and the internet is blocked. SLIRP still exists inside the operator QEMU process. Guest DNS is the in-guest stub on `127.0.0.1:53` (REFUSED, no recurse), not the operator resolver. No pcap. Guest is not on docker `lab-net`.

App remaps feed `kafka_raw_app` (`when_full: block`). Endpoint remaps feed `kafka_raw_endpoint` (`when_full: drop_newest`). There is no `sinks.kafka_raw`.

### Kafka — the bus

**Apache Kafka** is a distributed log. Producers append messages to named **topics**. Consumers read those topics, independently, at their own pace. Messages stay on the broker for a configured **retention** period, then expire. That is why we can replay: the events are still sitting there.

This lab runs a **single-node KRaft** broker (no ZooKeeper). KRaft is Kafka’s built-in consensus mode for cluster metadata.

#### Topic

A topic is a named stream. Ours:

| Topic | Key | Partitions | Kept for | Who writes | Who reads |
|---|---|---|---|---|---|
| `soc.raw.v1` | `source_alias` | 3 | 48 hours and 1 GiB | Vector only | Ingest only |
| `soc.events.v1` | `asset_id` | 3 | 7 days | Ingest only | Future Detect |
| `soc.ingest.unmapped.v1` | `source_alias` | 1 | 72 hours | Ingest | Humans / later reprocess |
| `soc.ingest.dlq.v1` | `source_alias` | 1 | 72 hours | Ingest | Humans / later reprocess |

`v1` in the name is a **breaking-change escape hatch**. Compatible field additions stay on `v1`. A change that would break existing consumers gets a new topic (`v2`). Auto topic creation is **off**; `infra/kafka-init.sh` creates these four on first boot.

#### Partition

A topic is split into **partitions** (think: parallel lanes of the same highway). Each partition is an ordered sequence. Kafka only guarantees order **inside one partition**, not across the whole topic.

How a message picks a lane: hash the **key**. Same key → same partition → same order.

- Raw key = `source_alias` → all `lab-shop` raw lines stay in order.
- Event key = `asset_id` → all events for that UUID stay in order. Detect can process assets in parallel without mixing one asset’s timeline.

#### Offset

Every message in a partition has an integer **offset** (0, 1, 2, …). A consumer remembers “I have processed up to offset 41 on partition 2.” That bookmark is the **committed offset**.

This pipeline **disables auto-commit**. It only commits after Kafka has confirmed every produce in the batch. If the process dies mid-batch, those offsets are uncommitted, Kafka redelivers, and Detect dedups using `event_id`.

#### Producer and consumer

| Term | Meaning |
|---|---|
| **Producer** | A program that writes messages (`produce` + `flush`) |
| **Consumer** | A program that reads messages (`poll` + `commit`) |
| **Consumer group** | A named team of consumers sharing a topic. Kafka assigns each partition to one member. Our group id is `ingest-normalizer` (`INGEST_GROUP_ID`) |
| **Bootstrap servers** | The first broker address the client contacts (`INGEST_BOOTSTRAP`, default `kafka:9092`). From there it learns the rest of the cluster |
| **Flush** | Block until the broker acknowledges queued produces |
| **Poll** | Ask the broker for the next message (or wait up to a timeout) |

#### Broker, replica, ISR (you will see these words)

| Term | Meaning |
|---|---|
| **Broker** | One Kafka server process. This lab has one |
| **Replica** | A copy of a partition on another broker. Lab replication factor is 1 (single node — no spare copy) |
| **ISR** | In-sync replicas: copies that have caught up. Used in bigger clusters |

#### Message anatomy

A Kafka message is more than a JSON blob:

| Part | What we put there |
|---|---|
| **Key** | `source_alias` (raw / unmapped / dlq) or `asset_id` (events) |
| **Value** | JSON bytes of RawRecord or Event |
| **Headers** | Extra key/value pairs. Events get `schema_version=1`. Unmapped/DLQ get `reason=...` |
| **Timestamp** | Set by Kafka when the message is appended |

#### Delivery words (the ones people mix up)

| Guarantee | Everyday meaning | This pipeline |
|---|---|---|
| **At most once** | Never a duplicate; you might lose a message | Not this |
| **At least once** | You might see a duplicate; you will not silently lose a confirmed batch | **This.** Commit only after flush succeeds |
| **Exactly once** | End-to-end, no loss and no dup | Not claimed. We get practical uniqueness via deterministic `event_id` |

Supporting producer settings in `src/ingest/kafka_adapter.py`:

- `acks=all` — wait until all in-sync replicas have the message (on one node, that is “the one broker”).
- `enable.idempotence=true` — the producer retries without creating extra copies of the *same* produce. This is not the same as exactly-once across a crash; that is why `event_id` exists.

**Idempotent** here means “doing it twice has the same effect as doing it once.” Downstream Detect should treat two Events with the same `event_id` as one event.

#### Why Kafka at all?

A database would also store events. Kafka is used because:

- Producers and consumers do not have to be up at the same time.
- Several future consumers (Detect, Observe, replay) can each read `soc.events.v1` from their own offset.
- Retention gives a time-boxed replay window without ingest writing a second store.
- ACLs let us say “only Vector may write raw; only ingest may write events.”

### Karapace — the schema registry

A **schema registry** is an HTTP service that stores the agreed shape of messages for each topic, and rejects incompatible changes.

**Karapace** is an open-source registry (Confluent-compatible API). It stores schemas in a Kafka topic named `_schemas`.

| Term | Meaning |
|---|---|
| **Subject** | The name a schema is registered under. We use `{topic}-value`: `soc.raw.v1-value` and `soc.events.v1-value` |
| **JSON Schema** | A document that says which fields exist, which are required, and that extra fields are forbidden |
| **Compatibility** | Rules for what a new schema version is allowed to do |

We use **FORWARD** compatibility: a *new producer* may add optional fields; it must not remove or rename fields that an older consumer still reads. We control both sides, so producer-led evolution is the rule. A rejected register raises `SchemaIncompatible` and the process **exits**. That is **fail closed**: do not run a pipeline whose contracts disagree.

Schemas are **generated** from the Pydantic models (`ingest schema export`), checked into `src/ingest/schemas/`, and a test asserts the files still match the models. Nobody hand-edits the JSON.

On `ingest run` and `ingest check`, `schema_sync.py` talks to Karapace:

1. Set the subject to FORWARD.
2. If the subject is missing, register the local schema.
3. If it exists and matches, continue.
4. If it exists and differs, try to register (Karapace enforces compatibility).
5. Connection errors retry with backoff (compose cold start), then fail.

### Estate — the directory ingest looks up

Ingest does not invent assets. `Estate.resolve_alias(lab_id, source_alias)` returns the stable `asset_id` UUID, or:

- `NotFound` → `Unmapped` (“alias not found”)
- `AmbiguousAlias` → `Unmapped` (“alias ambiguous”)

Unknown aliases are **data**, not a crash. A new container that is not in `inventory/default.yaml` will never become a respondable asset just because it logged something. That is deliberate: Layer 1 owns the catalog; Layer 2 only maps.

`webhook-generic` is an alias **on the Vector asset** so generic webhook traffic is attributed to the collector until a dedicated listener exists.

---

## The two envelopes

Both models are frozen (`frozen=True`) and reject unknown fields (`extra="forbid"`). Frozen means “cannot mutate after create.” Extra-forbid means a forged `asset_id` field on a RawRecord is **invalid**, not silently accepted.

### RawRecord — what Vector writes

| Field | Meaning |
|---|---|
| `lab_id` | Which lab (v1 is always `default`) |
| `source_alias` | Human-facing name of the source, locked by Vector config |
| `source_type` | `file` or `webhook` |
| `collector` | Who wrapped it (`vector`, or `ingest-cli` for test emits) |
| `raw` | The original line or body, treated as opaque text |
| `observed_at` | When Vector (or `ingest emit`) saw it. Timezone-aware |

### Event — what Detect will read

| Field | Meaning |
|---|---|
| `event_id` | Deterministic UUIDv5. Same inputs → same id, forever |
| `lab_id` | Copied from the envelope |
| `asset_id` | Resolved UUID from Estate |
| `source_alias` | Copied from the envelope |
| `source_type` | Copied from the envelope |
| `occurred_at` | When the *payload* says the thing happened, or `null` |
| `received_at` | Same as `observed_at` — when we collected it |
| `payload` | Redacted `raw` |
| `schema_version` | Integer, also a Kafka header. Today: `1` |

`event_id` is computed **before** redaction, from:

```
UUIDv5(fixed_namespace, sha256(lab_id | source_alias | observed_at | clean_raw))
```

If we later make the redactor stricter, the same original line still gets the same id. Redelivery after a crash also gets the same id.

---

## Inside the Python package

```
src/ingest/
  cli.py            run | check | emit | schema export
  config.py         INGEST_* env → IngestConfig (fail closed)
  models.py         RawRecord, Event, topic name constants, event_id
  redact.py         regex + entropy secret scrubber
  normalizer.py     bytes → Normalized | Unmapped | Invalid   (no I/O)
  pipeline.py       consume → normalize → produce → flush → maybe commit
  ports.py          Producer / Consumer / AliasResolver Protocols
  kafka_adapter.py  the only file that imports confluent-kafka
  schema_gen.py     Pydantic → JSON Schema text
  schema_sync.py    Karapace HTTP client
  schemas/          generated, checked-in JSON Schema files
  errors.py         ConfigInvalid, SchemaRegistryError, SchemaIncompatible
```

**Protocol** (Python `typing.Protocol`) here means “a duck-typed interface.” `Pipeline` only knows `poll` / `produce` / `flush` / `commit`. Tests pass fake objects. CI never installs `confluent-kafka`. The C library is an optional extra: `pip install 'self-defending-soc[kafka]'`.

### Redaction

`redact.py` runs on **every** variant, including unmapped and DLQ. Those topics would otherwise become a pile of the exact records that failed because they contained credentials.

It looks for:

- `Authorization` headers (keeps `Bearer`, replaces the token)
- JWTs (the `eyJ...` three-part strings)
- AWS-style `AKIA...` keys
- PEM private key blocks
- passwords in `scheme://user:password@host`
- `password=` / `token=` / `api_key=` style assignments
- long high-entropy tokens (Shannon entropy ≥ 4.2), so random-looking secrets that match no named pattern still get scrubbed

Benign words and normal UUIDs are left alone.

### Poison pills

A **poison pill** is a record that crashes the worker if you try to process it (bad bytes, a bug, a surprise exception). This pipeline catches any exception from `normalize`, turns it into `Invalid`, writes the DLQ, and keeps looping. One bad message cannot take ingest down.

### Commit protocol (the important reliability bit)

```
poll up to 100 raw messages
for each: normalize + produce (events or unmapped or dlq)
flush()
if every produce was acknowledged:
    commit the whole batch (max offset+1 per topic+partition)
else:
    commit nothing   → Kafka will redeliver the batch
```

Duplicates are expected under at-least-once. They are harmless if Detect keys on `event_id`.

---

## Security model (lab, but not open)

Kafka is **not** left open on the docker network. The in-scope red team is allowed to try to forge or sneak-consume events; open PLAINTEXT would make that a free win.

| Term | Meaning here |
|---|---|
| **Principal** | A Kafka username. Ours: `admin`, `vector`, `ingest`, `karapace` |
| **SASL** | A login handshake *before* you can talk to the broker |
| **PLAIN** | Username + password sent as-is (on an unencrypted docker-bridge connection). Good enough to block anonymous forge/consume. **SCRAM + TLS** is a recorded follow-up |
| **ACL** | Access-control list: which principal may Read/Write which topic |
| **Fail closed** | If we cannot prove it is safe (missing config, bad schema, unknown inventory), we stop. We do not “best-effort” run |

`allow.everyone.if.no.acl.found=false` — no ACL means **deny**, not allow.

What each user may do (`infra/kafka-init.sh`):

| Principal | Allowed |
|---|---|
| `admin` | Superuser (init only) |
| `vector` | Write + Describe `soc.raw.v1` |
| `ingest` | Read `soc.raw.v1`; Write events / unmapped / dlq; use group `ingest-normalizer` |
| `karapace` | All on `_schemas` and its own consumer group |

Vector cannot write events. A compromised collector cannot inject “normalized” traffic that Detect would trust as already-mapped. Ingest cannot write raw (it does not need to, except the test CLI `emit` which uses the ingest principal — `emit` is for operators, not Vector).

HTTP listeners require a **bearer token**. Each sender has its own token so you can revoke one without rotating the other.

Broker `message.max.bytes` is 1 MiB. The normalizer additionally rejects payloads over `INGEST_MAX_PAYLOAD_BYTES` (default 256 KiB) to the DLQ so a huge line cannot stall the loop.

---

## Config and CLI

Environment (prefix `INGEST_`), loaded by `src/ingest/config.py`:

| Variable | Required | Default | Role |
|---|---|---|---|
| `INGEST_BOOTSTRAP` | yes | — | Kafka address (`kafka:9092` in compose) |
| `INGEST_REGISTRY_URL` | yes | — | Karapace URL (`http://karapace:8081`) |
| `INGEST_GROUP_ID` | no | `ingest-normalizer` | Consumer group |
| `INGEST_SASL_USERNAME` | no | unset | Usually `ingest` |
| `INGEST_SASL_PASSWORD` | no | unset | From `infra/.env` |
| `INGEST_INVENTORY_PATH` | no | `inventory/default.yaml` | Estate catalog |
| `INGEST_LAB_ID` | no | `default` | Lab for `emit` |
| `INGEST_MAX_PAYLOAD_BYTES` | no | `262144` | Size cap |

Placeholders: `infra/.env.example`. Copy to `infra/.env`; never commit real passwords.

```
python -m ingest check           # config + inventory + registry; exit 1 on failure
python -m ingest run             # forever loop; compose runs this as soc-agent-ingest
python -m ingest schema export   # regenerate src/ingest/schemas/*.json
```

`check` is the “will this even start?” command (also the compose healthcheck). Operator smoke does **not** use `ingest emit` and does not publish Kafka ports.

---

## What ingest does *not* do

Layer boundaries matter. Ingest must not grow into the rest of the SOC.

| Temptation | Who actually owns it |
|---|---|
| Define or auto-create assets | Estate (Layer 1). Unknown runtime objects stay unmapped |
| Decide “this is an attack” | Detect (Layer 3) |
| Alert on a flood of DLQ | Detect (deferred) |
| Isolate / contain | Respond (Layer 5), after a human |
| Restore snapshots | Recover (Layer 6) |
| Generate attack traffic | Red team (Layer 7); findings enter *through* ingest as webhooks |
| Encrypt Kafka on the wire (TLS) | Recorded follow-up, not v1 |
| Hot-reload inventory | Restart the process (acceptable at lab scale) |
| `reprocess-unmapped` CLI | Deferred; unmapped records already carry the redacted RawRecord + reason |

---

## Inventory assets this layer added

Estate catalogs the ingest *infrastructure* too (self-inclusion: the SOC watches itself).

| Asset name | Kind | Why it is listed |
|---|---|---|
| `soc-kafka` | `soc_service` | `never_isolate` — isolating Kafka blinds the whole SOC |
| `soc-karapace` | `soc_service` | Schema registry |
| `soc-vector` | `soc_service` | Collector; also owns alias `webhook-generic` |
| `soc-agent-ingest` | `soc_agent` | The normalizer process |

Edges: Vector / Karapace / ingest-agent `depends_on` Kafka; ingest-agent `depends_on` Karapace; ingest-agent `emits_logs_as` soc-api.

---

## How the files map to the walkthrough

```
lab writes a log
   → Vector file source + remap          infra/vector/vector.yaml
   → Kafka produce soc.raw.v1            Vector sink (principal `vector`)
   → ingest consume                      src/ingest/kafka_adapter.py
   → normalize                           src/ingest/normalizer.py
        → redact                         src/ingest/redact.py
        → resolve_alias                  src/estate/query.py
        → Event / Unmapped / Invalid     src/ingest/models.py
   → produce variant topic               src/ingest/pipeline.py
   → schema gate at startup              src/ingest/schema_sync.py
   → topics + ACLs on first boot         infra/kafka-init.sh
   → broker + registry + collector       infra/compose.yaml
```

Control-flow cheat sheet for debugging “did this break before or after X” lives in `docs/agents/Flow.md`. Design choices (why confluent-kafka, why FORWARD, why UUIDv5) live in `docs/agents/Decisions.md`. The implementation plan is `docs/superpowers/plans/2026-08-23-ingest-layer-2.md`.

---

## Glossary

Jump list. Everyday language first, then the precise meaning in this repo.

**ACL.** A rule that says principal X may Read or Write topic Y. Enforced by Kafka’s authorizer. Missing ACL = deny.

**Alias / source_alias.** A human name for a source (`lab-shop`). Estate maps `(lab_id, alias)` → one `asset_id`. Vector sets the alias; log content cannot.

**At-least-once.** The delivery promise: a message may be processed more than once, but a flushed batch is not silently dropped. Duplicates are deduped by `event_id`.

**Broker.** One Kafka server. This lab: the `kafka` container.

**Bootstrap servers.** Initial broker address a client uses to join the cluster.

**Commit (offset).** The consumer telling Kafka “I am done through this offset.” After a crash, Kafka rewinds to the last commit.

**Consumer / consumer group.** Reader of a topic. A group shares partitions. Ours: `ingest-normalizer`.

**Dead-letter queue (DLQ).** `soc.ingest.dlq.v1`. The parking lot for records that cannot be normalized. Redacted. Does not block the pipeline.

**Deterministic ID.** An id you can recompute from the input. Opposite of “random UUID at insert time.” Needed so redelivery is not a new event.

**Envelope.** Metadata wrapper around opaque content. RawRecord is the raw envelope; Event is the normalized one.

**Fail closed.** On doubt, stop. Opposite of fail open (“keep going and hope”).

**Flush.** Wait until the broker has acknowledged queued produces.

**FORWARD compatibility.** New schemas may add fields consumers can ignore; they must not remove fields old consumers need.

**Header.** Optional key/value on a Kafka message (`reason`, `schema_version`).

**Idempotence.** Doing an action twice equals doing it once. Producer setting plus `event_id` together give this in practice.

**KRaft.** Kafka’s built-in metadata mode (no ZooKeeper).

**Karapace.** Schema registry used here. HTTP API, schemas stored in Kafka topic `_schemas`.

**Key (Kafka).** Bytes used to pick a partition and keep same-key messages ordered.

**Offset.** Integer position of a message inside a partition.

**Partition.** One ordered lane of a topic. Order is per partition, not per topic.

**Poison pill.** A record that would crash a naive worker. Here it becomes a DLQ entry.

**Poll.** Ask Kafka for the next record.

**Principal.** Kafka username (`vector`, `ingest`, …).

**Producer.** Writer of Kafka messages.

**Provenance.** “Where did this come from, and can we prove it?” Locked to Vector source config.

**Pydantic.** Python library that validates data against typed models. Our envelopes are Pydantic models.

**RawRecord.** Vector’s output shape. See [The two envelopes](#the-two-envelopes).

**Redaction.** Replacing secret-shaped substrings with `[REDACTED]` before a record is written anywhere.

**Retention.** How long Kafka keeps a topic’s messages. After that they expire, even if nobody consumed them.

**SASL / PLAIN.** Login mechanism. PLAIN = password as-is. Not TLS. Lab tradeoff; SCRAM+TLS is planned.

**Schema / schema registry / subject.** The contract for a message value, stored under a subject name, enforced by Karapace.

**Sink / source / transform.** Vector’s three building blocks: input, rewrite, output.

**Tagged union.** A value that is exactly one of several shapes. Here: `Normalized | Unmapped | Invalid`. The pipeline switches on the type to pick a topic.

**Telemetry.** The incoming signals (logs, webhooks) as a stream, before anyone has labeled them as attacks.

**Topic.** A named Kafka stream (`soc.raw.v1`, …).

**Unmapped.** Valid envelope, unknown or ambiguous alias. Not an error in the crash sense.

**Vector.** The collector that tails files and accepts authenticated HTTP, then writes RawRecords.

**Webhook.** An HTTP POST someone else sends you when something happens. Red team findings arrive this way.

---

## If you want to see it move

Operator path: compose ingest on `lab-net`, append one Slice B syslog golden onto the host bind, consume `soc.events.v1` as `User:admin` from the same Kafka image. Success is Event JSON with `asset_id` `11111111-1111-4111-8111-111111111107`. Do not use `ingest emit`. Do not publish 9092/8081.

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

Not a pytest gate. You do not need Detect running. Ingest’s success condition is: raw in, redacted Event (or unmapped / DLQ) out, offsets committed only after Kafka says the write landed.
