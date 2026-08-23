import json

import httpx
import pytest

from ingest.errors import SchemaIncompatible, SchemaRegistryError
from ingest.schema_gen import SUBJECT_SCHEMAS, packaged_schema_text
from ingest.schema_sync import sync_schemas

BASE = "http://karapace.test"


class RegistryFake:
    """Minimal Karapace behavior behind httpx.MockTransport."""

    def __init__(self, existing: dict[str, str] | None = None, reject_writes: bool = False):
        self.existing = dict(existing or {})
        self.reject_writes = reject_writes
        self.registered: list[str] = []
        self.compat_set: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/config/") and request.method == "PUT":
            self.compat_set.append(path.removeprefix("/config/"))
            return httpx.Response(200, json={"compatibility": "FORWARD"})
        if path.endswith("/versions/latest") and request.method == "GET":
            subject = path.split("/")[2]
            if subject in self.existing:
                return httpx.Response(
                    200, json={"subject": subject, "schema": self.existing[subject]}
                )
            return httpx.Response(404, json={"error_code": 40401})
        if path.endswith("/versions") and request.method == "POST":
            subject = path.split("/")[2]
            if self.reject_writes:
                return httpx.Response(409, json={"error_code": 409})
            self.registered.append(subject)
            self.existing[subject] = json.loads(request.content)["schema"]
            return httpx.Response(200, json={"id": len(self.registered)})
        return httpx.Response(500)


def _client(fake: RegistryFake) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake.handler))


def test_registers_when_absent():
    fake = RegistryFake()
    sync_schemas(BASE, client=_client(fake))
    assert sorted(fake.registered) == sorted(SUBJECT_SCHEMAS)
    assert sorted(fake.compat_set) == sorted(SUBJECT_SCHEMAS)


def test_noop_when_schemas_match():
    existing = {
        subject: packaged_schema_text(filename)
        for subject, filename in SUBJECT_SCHEMAS.items()
    }
    fake = RegistryFake(existing=existing)
    sync_schemas(BASE, client=_client(fake))
    assert fake.registered == []


def test_incompatible_registration_fails_closed():
    existing = {subject: json.dumps({"type": "string"}) for subject in SUBJECT_SCHEMAS}
    fake = RegistryFake(existing=existing, reject_writes=True)
    with pytest.raises(SchemaIncompatible):
        sync_schemas(BASE, client=_client(fake))


def test_registry_unreachable_bounded_retry_then_fail():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SchemaRegistryError):
        sync_schemas(BASE, client=client, retries=2, backoff_base=0.0)
    assert attempts == 3  # initial + 2 retries


def test_server_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SchemaRegistryError):
        sync_schemas(BASE, client=client)
