# self-defending-soc

A security operations lab that defends itself. It watches a lab estate, finds attacks, builds a case with evidence, and waits for a human to approve before it acts. The estate includes this platform, so the system also tests and defends itself.

**Status:** work in progress. Layers 1 and 2 are built and tested. The agent layers (Detect, Investigate, Respond, Recover, Red team) are next.

## The loop

```
Estate -> Ingest -> Detect -> Investigate -> Human approves -> Respond (stop the attack)
                                                            -> Recover (only if stopping failed)
Red team attacks the estate, including this SOC. Its findings enter the same path.
```

Agents can find and propose actions without a human. They execute only after a human approves, and only inside the lab.

## Layers

| # | Layer | What it does | Status |
|---|---|---|---|
| 1 | Estate | Asset inventory: lab services, one lab Linux host, and this SOC's own API, config and agents | Built |
| 2 | Ingest | Turns app logs, host logs and webhooks into a clean, attributed, redacted event stream | Built |
| 3 | Detect | Finds attacks in the event stream | Next |
| 4 | Investigate | Builds a case: evidence, blast radius, written reasons | Planned |
| 5 | Respond | Stops the attack in the lab after approval | Planned |
| 6 | Recover | Undoes damage only if Respond failed | Planned |
| 7 | Red team | Attacks the estate, including this SOC | Planned |
| 8 | Observe | Traces, metrics and replay | Planned |
| 9 | Memory | Cases, approvals and an audit trail | Planned |

## What is built

**Ingest pipeline.** Vector collects each log line and wraps it in a raw record. The records go to Kafka. A Python service checks each record against a JSON schema (kept in sync with a Karapace schema registry), finds the source asset in the estate inventory, removes secrets, and writes a normalized event. It commits Kafka offsets only after a successful flush.

**Lab Linux endpoint.** A Debian 12 VM under QEMU with no network path to the host or the internet. Guest forwarders write auditd syscalls, journald logs, network events (nftables and a DNS stub) and USB file copies as JSON lines. Vector tails those files as the `lab-endpoint` asset.

**Tests.** pytest covers the estate loader, schema contracts, normalization, redaction, the pipeline and the endpoint forwarders. CI uses golden log files, so it does not need the VM.

## Run

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,kafka]"
pytest                                  # no Kafka or VM needed
docker compose -f infra/compose.yaml up # Kafka, Karapace, Vector, ingest
```

The lab VM is optional. See [infra/endpoint/README.md](infra/endpoint/README.md).

## Docs

- [Project overview](docs/project-overview.md)
- [Ingest layer walkthrough](docs/ingest-layer.md)
- Decisions and change log: [docs/agents/](docs/agents/)

## Stack

Python 3.12, Pydantic, Kafka, Vector, Karapace, Docker Compose, QEMU, auditd, nftables, pytest.
