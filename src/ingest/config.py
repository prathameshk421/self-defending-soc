"""Fail-closed ingest configuration from INGEST_* environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel, ValidationError

from ingest.errors import ConfigInvalid

DEFAULT_INVENTORY = (
    Path(__file__).resolve().parents[2] / "inventory" / "default.yaml"
)


class IngestConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    bootstrap: str
    registry_url: str
    group_id: str = "ingest-normalizer"
    sasl_username: Optional[str] = None
    sasl_password: Optional[str] = None
    inventory_path: Path = DEFAULT_INVENTORY
    lab_id: str = "default"
    max_payload_bytes: int = 262144


_REQUIRED = {
    "bootstrap": "INGEST_BOOTSTRAP",
    "registry_url": "INGEST_REGISTRY_URL",
}

_OPTIONAL = {
    "group_id": "INGEST_GROUP_ID",
    "sasl_username": "INGEST_SASL_USERNAME",
    "sasl_password": "INGEST_SASL_PASSWORD",
    "inventory_path": "INGEST_INVENTORY_PATH",
    "lab_id": "INGEST_LAB_ID",
    "max_payload_bytes": "INGEST_MAX_PAYLOAD_BYTES",
}


def load_config(env: Mapping[str, str] | None = None) -> IngestConfig:
    """Build and validate IngestConfig. Fail closed on anything missing/invalid."""
    if env is None:
        env = os.environ

    values: dict[str, object] = {}
    missing: list[str] = []
    for field, var in _REQUIRED.items():
        raw = env.get(var, "").strip()
        if not raw:
            missing.append(var)
        else:
            values[field] = raw
    if missing:
        raise ConfigInvalid(f"missing required env vars: {', '.join(missing)}")

    for field, var in _OPTIONAL.items():
        raw = env.get(var)
        if raw is not None and raw.strip():
            values[field] = raw.strip()

    try:
        config = IngestConfig.model_validate(values)
    except ValidationError as exc:
        raise ConfigInvalid(str(exc)) from exc

    if config.max_payload_bytes <= 0:
        raise ConfigInvalid("INGEST_MAX_PAYLOAD_BYTES must be positive")
    return config
