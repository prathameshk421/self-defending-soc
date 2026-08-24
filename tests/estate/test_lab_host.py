from pathlib import Path

import pytest
import yaml

from estate.errors import InventoryInvalid, RespondForbidden
from estate.loader import load_inventory
from estate.query import Estate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = REPO_ROOT / "inventory" / "default.yaml"
HOST_ID = "11111111-1111-4111-8111-111111111107"


def test_default_inventory_lab_host():
    estate = Estate(load_inventory(DEFAULT_INVENTORY))
    host = estate.get(HOST_ID)
    assert host.kind.value == "lab_host"
    assert estate.resolve_alias("default", "lab-endpoint") == HOST_ID
    assert {s.id for s in host.log_sources} == {
        "endpoint-syslog",
        "endpoint-udev",
        "endpoint-process",
        "endpoint-audit",
    }
    locators = {s.id: s.locator for s in host.log_sources}
    assert locators == {
        "endpoint-syslog": "/var/log/lab-endpoint/syslog.log",
        "endpoint-udev": "/var/log/lab-endpoint/udev.log",
        "endpoint-process": "/var/log/lab-endpoint/process.log",
        "endpoint-audit": "/var/log/lab-endpoint/audit.log",
    }
    assert host.aliases == ["lab-endpoint"]
    with pytest.raises(RespondForbidden):
        estate.assert_respond_target(HOST_ID)


def test_lab_host_empty_log_sources_invalid(tmp_path: Path):
    data = yaml.safe_load(DEFAULT_INVENTORY.read_text(encoding="utf-8"))
    data["assets"] = [
        a
        for a in data["assets"]
        if a["asset_id"] != HOST_ID
    ] + [
        {
            "asset_id": HOST_ID,
            "lab_id": "default",
            "kind": "lab_host",
            "name": "lab-endpoint",
            "owner": "lab_app",
            "lifecycle": "declared",
            "execution_realm": "lab",
            "respond_allowed": False,
            "self_defense_class": "watch_only",
            "owner_ref": "lab-ops",
            "approval_policy_id": "default-hitl",
            "exposure": "loopback",
            "aliases": ["lab-endpoint"],
            "log_sources": [],
            "in_scope_red_team": False,
            "red_team_skip": True,
        }
    ]
    path = tmp_path / "inv.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(InventoryInvalid, match="empty log_sources"):
        load_inventory(path)
