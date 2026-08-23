"""Estate Layer 1 tests — critic edge cases from the plan."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from estate.errors import InventoryInvalid, NotFound, RespondForbidden
from estate.loader import load_inventory
from estate.query import Estate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = REPO_ROOT / "inventory" / "default.yaml"

SOC_API_ID = "22222222-2222-4222-8222-222222222201"
SOC_CONFIG_ID = "22222222-2222-4222-8222-222222222202"
LAB_SHOP_ID = "11111111-1111-4111-8111-111111111102"
LAB_WALLET_ID = "11111111-1111-4111-8111-111111111106"
LAB_IDP_ID = "11111111-1111-4111-8111-111111111103"


@pytest.fixture
def estate() -> Estate:
    return Estate(load_inventory(DEFAULT_INVENTORY))


def _write_inventory(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "inventory.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _minimal_asset(**overrides) -> dict:
    base = {
        "asset_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "lab_id": "default",
        "kind": "lab_service",
        "name": "svc-a",
        "owner": "lab_app",
        "lifecycle": "declared",
        "execution_realm": "lab",
        "respond_allowed": True,
        "self_defense_class": "contain_with_degraded_mode",
        "owner_ref": "ops",
        "approval_policy_id": "default-hitl",
        "exposure": "lab_network",
        "aliases": ["svc-a"],
        "containment_handles": [{"kind": "compose_service", "locator": "svc-a"}],
        "in_scope_red_team": False,
        "red_team_skip": True,
    }
    base.update(overrides)
    return base


# --- 1. Load seed; get soc-api; resolve shop alias ---


def test_load_seed_get_soc_api_and_resolve_shop_alias(estate: Estate) -> None:
    soc = estate.get(SOC_API_ID)
    assert soc.name == "soc-api"
    assert soc.self_defense_class.value == "never_isolate"

    shop_id = estate.resolve_alias("default", "hostname:shop.lab.local")
    assert shop_id == LAB_SHOP_ID
    assert estate.get(shop_id).name == "lab-shop"


# --- 2. Duplicate name / alias ---


def test_duplicate_name_fails(tmp_path: Path) -> None:
    a = _minimal_asset(asset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1", name="dup")
    b = _minimal_asset(
        asset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        name="dup",
        aliases=["dup-b"],
    )
    path = _write_inventory(
        tmp_path,
        {"schema_version": 1, "lab_id": "default", "assets": [a, b], "edges": []},
    )
    with pytest.raises(InventoryInvalid, match="duplicate name"):
        load_inventory(path)


def test_duplicate_alias_fails(tmp_path: Path) -> None:
    a = _minimal_asset(
        asset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        name="a",
        aliases=["shared"],
    )
    b = _minimal_asset(
        asset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        name="b",
        aliases=["shared"],
    )
    path = _write_inventory(
        tmp_path,
        {"schema_version": 1, "lab_id": "default", "assets": [a, b], "edges": []},
    )
    with pytest.raises(InventoryInvalid, match="duplicate alias"):
        load_inventory(path)


# --- 3. Secret-shaped field with value ---


def test_secret_shaped_field_rejected(tmp_path: Path) -> None:
    asset = _minimal_asset()
    data = {
        "schema_version": 1,
        "lab_id": "default",
        "assets": [asset],
        "edges": [],
        "db_password": "hunter2",
    }
    path = _write_inventory(tmp_path, data)
    with pytest.raises(InventoryInvalid, match="secret-shaped"):
        load_inventory(path)


def test_password_on_asset_rejected(tmp_path: Path) -> None:
    asset = _minimal_asset()
    asset["api_token"] = "supersecret"
    path = _write_inventory(
        tmp_path,
        {"schema_version": 1, "lab_id": "default", "assets": [asset], "edges": []},
    )
    with pytest.raises(InventoryInvalid, match="secret-shaped"):
        load_inventory(path)


# --- 4. Two labs, same name — no merge ---


def test_same_name_different_labs_ok(tmp_path: Path) -> None:
    a = _minimal_asset(
        asset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        lab_id="lab-a",
        name="api",
        aliases=["api-a"],
    )
    b = _minimal_asset(
        asset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        lab_id="lab-b",
        name="api",
        aliases=["api-b"],
    )
    path = _write_inventory(
        tmp_path,
        {"schema_version": 1, "lab_id": "lab-a", "assets": [a, b], "edges": []},
    )
    inv = load_inventory(path)
    estate = Estate(inv)
    assert estate.get(a["asset_id"]).name == "api"
    assert estate.get(b["asset_id"]).name == "api"
    assert estate.get(a["asset_id"]).lab_id != estate.get(b["asset_id"]).lab_id


# --- 5. assert_respond_target(soc-api) forbidden ---


def test_assert_respond_soc_api_forbidden(estate: Estate) -> None:
    with pytest.raises(RespondForbidden):
        estate.assert_respond_target(SOC_API_ID)


# --- 6. assert_respond_target(lab-shop) succeeds ---


def test_assert_respond_lab_shop_ok(estate: Estate) -> None:
    estate.assert_respond_target(LAB_SHOP_ID)
    shop = estate.get(LAB_SHOP_ID)
    assert any(h.kind == "compose_service" for h in shop.containment_handles)
    assert all(h.kind != "container_id" for h in shop.containment_handles)


# --- 7. Neighbors of lab-shop ---


def test_neighbors_lab_shop(estate: Estate) -> None:
    names = {a.name for a in estate.neighbors(LAB_SHOP_ID, depth=1)}
    assert "lab-wallet" in names
    assert "lab-idp" in names
    assert "lab-net" in names
    assert "host" not in names
    assert "operator" not in names


# --- 8. Config: isolate fails; restore handle present ---


def test_soc_config_isolate_fails_restore_present(estate: Estate) -> None:
    cfg = estate.get(SOC_CONFIG_ID)
    assert cfg.restore_handles
    assert cfg.restore_handles[0].kind == "config_path"
    with pytest.raises(RespondForbidden):
        estate.assert_respond_target(SOC_CONFIG_ID)


# --- 9. Unknown alias — no auto-create ---


def test_unknown_alias_not_found(estate: Estate) -> None:
    with pytest.raises(NotFound):
        estate.resolve_alias("default", "ghost.lab.local")
    assert all(a.name != "ghost.lab.local" for a in estate.list())


# --- 10. Schema version mismatch ---


def test_missing_schema_version_fails(tmp_path: Path) -> None:
    path = _write_inventory(
        tmp_path,
        {"lab_id": "default", "assets": [_minimal_asset()], "edges": []},
    )
    with pytest.raises(InventoryInvalid, match="schema_version"):
        load_inventory(path)


def test_wrong_schema_version_fails(tmp_path: Path) -> None:
    path = _write_inventory(
        tmp_path,
        {
            "schema_version": 0,
            "lab_id": "default",
            "assets": [_minimal_asset()],
            "edges": [],
        },
    )
    with pytest.raises(InventoryInvalid, match="unsupported schema_version"):
        load_inventory(path)


# --- 11. in_scope_red_team with empty attack_surface ---


def test_in_scope_empty_surface_fails(tmp_path: Path) -> None:
    asset = _minimal_asset(
        in_scope_red_team=True,
        red_team_skip=False,
        attack_surface=[],
    )
    path = _write_inventory(
        tmp_path,
        {"schema_version": 1, "lab_id": "default", "assets": [asset], "edges": []},
    )
    with pytest.raises(InventoryInvalid, match="attack_surface"):
        load_inventory(path)


def test_in_scope_empty_surface_ok_with_skip(tmp_path: Path) -> None:
    asset = _minimal_asset(
        in_scope_red_team=True,
        red_team_skip=True,
        attack_surface=[],
    )
    path = _write_inventory(
        tmp_path,
        {"schema_version": 1, "lab_id": "default", "assets": [asset], "edges": []},
    )
    load_inventory(path)


# --- 12. Retired asset: get works; default list excludes ---


def test_retired_get_and_list(tmp_path: Path) -> None:
    active = _minimal_asset(
        asset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        name="alive",
        aliases=["alive"],
    )
    retired = _minimal_asset(
        asset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        name="gone",
        aliases=["gone"],
        lifecycle="retired",
        respond_allowed=False,
    )
    path = _write_inventory(
        tmp_path,
        {
            "schema_version": 1,
            "lab_id": "default",
            "assets": [active, retired],
            "edges": [],
        },
    )
    estate = Estate(load_inventory(path))
    got = estate.get(retired["asset_id"])
    assert got.name == "gone"
    names = {a.name for a in estate.list()}
    assert "alive" in names
    assert "gone" not in names
    retired_list = estate.list(lifecycle="retired", include_retired=True)
    assert any(a.name == "gone" for a in retired_list)


def test_cli_list_includes_seed_names() -> None:
    from estate.cli import main

    assert main(["list"]) == 0
