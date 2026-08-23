"""Canonical JSON Schema generation from the Pydantic envelope models.

Schemas are generated, never hand-written: `ingest schema export` writes
them and a contract test asserts the checked-in files byte-equal the
generated output, so the Pydantic models and registry schemas cannot drift.
"""

from __future__ import annotations

import json
from importlib import resources

from pydantic import BaseModel

from ingest.models import Event, RawRecord

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "raw_record.schema.json": RawRecord,
    "event.schema.json": Event,
}

SUBJECT_SCHEMAS: dict[str, str] = {
    "soc.raw.v1-value": "raw_record.schema.json",
    "soc.events.v1-value": "event.schema.json",
}


def generate_schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def packaged_schema_text(filename: str) -> str:
    return (
        resources.files("ingest").joinpath("schemas").joinpath(filename).read_text("utf-8")
    )
