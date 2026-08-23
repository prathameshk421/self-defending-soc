"""Fail-closed schema sync against a Karapace registry.

For each subject: set FORWARD compatibility, then register the local schema
if the subject is absent or its latest schema differs. The registry enforces
compatibility, so a rejected registration means the local models have made an
incompatible change and startup must fail closed. Connection errors retry
with bounded exponential backoff to survive compose cold starts.
"""

from __future__ import annotations

import json
import time

import httpx

from ingest.errors import SchemaIncompatible, SchemaRegistryError
from ingest.schema_gen import SUBJECT_SCHEMAS, packaged_schema_text

_COMPATIBILITY = "FORWARD"


def _canonical(schema_text: str) -> str:
    return json.dumps(json.loads(schema_text), sort_keys=True, separators=(",", ":"))


def _sync_subject(client: httpx.Client, base_url: str, subject: str, schema_text: str) -> None:
    compat = client.put(
        f"{base_url}/config/{subject}",
        json={"compatibility": _COMPATIBILITY},
    )
    if compat.status_code >= 500:
        raise SchemaRegistryError(
            f"setting compatibility for {subject}: HTTP {compat.status_code}"
        )

    latest = client.get(f"{base_url}/subjects/{subject}/versions/latest")
    if latest.status_code == 200:
        remote = latest.json().get("schema", "")
        if _canonical(remote) == _canonical(schema_text):
            return
    elif latest.status_code != 404:
        raise SchemaRegistryError(
            f"fetching latest schema for {subject}: HTTP {latest.status_code}"
        )

    register = client.post(
        f"{base_url}/subjects/{subject}/versions",
        json={"schema": schema_text, "schemaType": "JSON"},
    )
    if register.status_code in (409, 422):
        raise SchemaIncompatible(
            f"schema for {subject} is incompatible with the registered version"
        )
    if register.status_code != 200:
        raise SchemaRegistryError(
            f"registering schema for {subject}: HTTP {register.status_code}"
        )


def sync_schemas(
    registry_url: str,
    *,
    client: httpx.Client | None = None,
    retries: int = 5,
    backoff_base: float = 1.0,
) -> None:
    """Ensure all subjects exist with the local schemas. Raise on any mismatch."""
    base_url = registry_url.rstrip("/")
    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=10.0)
    try:
        for subject, filename in SUBJECT_SCHEMAS.items():
            schema_text = packaged_schema_text(filename)
            attempt = 0
            while True:
                try:
                    _sync_subject(client, base_url, subject, schema_text)
                    break
                except httpx.TransportError as exc:
                    attempt += 1
                    if attempt > retries:
                        raise SchemaRegistryError(
                            f"registry unreachable after {retries} retries: {exc}"
                        ) from exc
                    time.sleep(backoff_base * (2 ** (attempt - 1)))
    finally:
        if own_client:
            client.close()
