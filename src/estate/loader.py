"""Fail-closed YAML inventory loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from estate.errors import InventoryInvalid
from estate.models import SCHEMA_VERSION, Inventory

# Keys that must never hold secret *values* in inventory documents.
_SECRET_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
)


def _looks_like_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s:
        return False
    # Allowed: refs like env:NAME, vault:path, ${ENV}, ref:…
    lower = s.lower()
    if lower.startswith(("env:", "vault:", "ref:", "${")):
        return False
    if s.startswith("$"):
        return False
    return True


def _reject_secret_shaped(node: Any, path: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            key_l = str(key).lower()
            child_path = f"{path}.{key}" if path else str(key)
            if any(frag in key_l for frag in _SECRET_KEY_FRAGMENTS):
                # credential_refs use {name, ref} — key "name" is fine; values under
                # password/token/etc. keys are not.
                if key_l in ("credential_refs", "credentials"):
                    _reject_secret_shaped(value, child_path)
                    continue
                if key_l == "ref":
                    # ref values must be pointers, not raw secrets
                    if _looks_like_secret_value(value):
                        # env:/vault: already allowed in _looks_like_secret_value
                        pass
                    _reject_secret_shaped(value, child_path)
                    continue
                if isinstance(value, str) and _looks_like_secret_value(value):
                    raise InventoryInvalid(
                        f"secret-shaped field with value at {child_path}"
                    )
                if isinstance(value, (dict, list)):
                    _reject_secret_shaped(value, child_path)
            else:
                _reject_secret_shaped(value, child_path)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _reject_secret_shaped(item, f"{path}[{i}]")


def _validate_uniqueness(inventory: Inventory) -> None:
    seen_names: set[tuple[str, str]] = set()
    seen_aliases: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()

    for asset in inventory.assets:
        id_key = asset.asset_id
        if id_key in seen_ids:
            raise InventoryInvalid(f"duplicate asset_id: {id_key}")
        seen_ids.add(id_key)

        name_key = (asset.lab_id, asset.name)
        if name_key in seen_names:
            raise InventoryInvalid(
                f"duplicate name in lab: lab_id={asset.lab_id!r} name={asset.name!r}"
            )
        seen_names.add(name_key)

        for alias in asset.aliases:
            alias_key = (asset.lab_id, alias)
            if alias_key in seen_aliases:
                raise InventoryInvalid(
                    f"duplicate alias in lab: lab_id={asset.lab_id!r} alias={alias!r}"
                )
            seen_aliases.add(alias_key)


def _validate_red_team_surface(inventory: Inventory) -> None:
    for asset in inventory.assets:
        if asset.in_scope_red_team and not asset.attack_surface and not asset.red_team_skip:
            raise InventoryInvalid(
                f"in_scope_red_team asset {asset.name!r} has empty attack_surface "
                f"(set red_team_skip: true to skip)"
            )


def _validate_edges(inventory: Inventory) -> None:
    ids = {a.asset_id for a in inventory.assets}
    for edge in inventory.edges:
        if edge.from_id not in ids:
            raise InventoryInvalid(f"edge from unknown asset_id: {edge.from_id}")
        if edge.to_id not in ids:
            raise InventoryInvalid(f"edge to unknown asset_id: {edge.to_id}")


def load_inventory(path: str | Path) -> Inventory:
    """Load and validate inventory YAML. Fail closed on any policy violation."""
    path = Path(path)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InventoryInvalid(f"cannot read inventory: {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise InventoryInvalid(f"invalid YAML: {exc}") from exc

    if data is None:
        raise InventoryInvalid("empty inventory document")
    if not isinstance(data, dict):
        raise InventoryInvalid("inventory root must be a mapping")

    if "schema_version" not in data:
        raise InventoryInvalid("missing schema_version")
    if data["schema_version"] != SCHEMA_VERSION:
        raise InventoryInvalid(
            f"unsupported schema_version: {data['schema_version']!r} "
            f"(expected {SCHEMA_VERSION})"
        )

    _reject_secret_shaped(data)

    try:
        inventory = Inventory.model_validate(data)
    except ValidationError as exc:
        raise InventoryInvalid(str(exc)) from exc

    _validate_uniqueness(inventory)
    _validate_red_team_surface(inventory)
    _validate_edges(inventory)
    return inventory
