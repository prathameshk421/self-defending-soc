"""Load lab-net-forward / lab-dns-stub via SourceFileLoader."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NET_PATH = REPO_ROOT / "infra" / "endpoint" / "guest" / "lab-net-forward"
STUB_PATH = REPO_ROOT / "infra" / "endpoint" / "guest" / "lab-dns-stub"
RUN_VM = REPO_ROOT / "infra" / "endpoint" / "run-vm.sh"

NFT_NEW = json.dumps(
    {
        "nftables": [
            {
                "trace": {
                    "family": "inet",
                    "table": "lab",
                    "chain": "output",
                    "type": "packet",
                    "ip": {"saddr": "10.0.2.15", "daddr": "1.2.3.4", "protocol": 6},
                    "tcp": {"sport": 54321, "dport": 443},
                    "ct": {"state": "new"},
                }
            }
        ]
    }
)
NFT_GW = json.dumps(
    {
        "nftables": [
            {
                "trace": {
                    "ip": {"saddr": "10.0.2.15", "daddr": "10.0.2.3", "protocol": 17},
                    "udp": {"sport": 53, "dport": 53},
                    "ct": {"state": "new"},
                }
            }
        ]
    }
)

PHASE2_SHA256 = (
    "3fc9742f9f1a37bcb9931df6074b4d1483419ef832ad5349f47323e75fc27864",
    "3a8223f9bfba99d97bf25296ac83de307ab036e1df63e5965f88809266851947",
    "966ff20ce58c17163a771c02ddbca264291408f94c512bd85dd18da0ebdbe88c",
)


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def netmod():
    return _load(NET_PATH, "lab_endpoint_net_forward")


@pytest.fixture(scope="module")
def stubmod():
    return _load(STUB_PATH, "lab_endpoint_dns_stub")


def test_keep_nft_new_tcp(netmod):
    out = list(netmod.records_from_nft_text(NFT_NEW + "\n"))
    assert len(out) == 1
    assert out[0]["source"] == "nft"
    assert out[0]["proto"] == "tcp"
    assert out[0]["daddr"] == "1.2.3.4"
    assert out[0]["dport"] == 443
    assert out[0]["event"] == "new"


def test_drop_gateway_dns(netmod):
    assert list(netmod.records_from_nft_text(NFT_GW + "\n")) == []


def test_first_tuple_only(netmod):
    text = NFT_NEW + "\n" + NFT_NEW + "\n"
    assert len(list(netmod.records_from_nft_text(text))) == 1


def test_truncate_string_field(netmod):
    long_q = "x" * 20000
    rec = netmod.dns_record(long_q, "A")
    assert rec["qname"].endswith("...")
    assert len(rec["qname"].encode("utf-8")) <= 16387


def test_format_is_one_object_one_newline(netmod):
    rec = list(netmod.records_from_nft_text(NFT_NEW + "\n"))[0]
    line = netmod.format_net_line(rec)
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert json.loads(line) == rec


def test_forwarder_source_locks():
    text = NET_PATH.read_text(encoding="utf-8")
    assert "O_NOFOLLOW" in text
    assert 'source":"nft"' in text or "'nft'" in text
    assert 'source":"dns"' in text or "'dns'" in text


def test_stub_binds_loopback_and_does_not_recurse():
    text = STUB_PATH.read_text(encoding="utf-8")
    assert 'bind("127.0.0.1"' in text or "bind('127.0.0.1'" in text
    assert "10.0.2.3" not in text


def test_run_vm_user_nic_restrict_on():
    text = RUN_VM.read_text(encoding="utf-8")
    assert "rm -f" in text and "overlay.qcow2" in text
    assert "-nic user,model=virtio,restrict=on" in text
    assert "-nic none" not in text
    assert "hostfwd" not in text
    for name in ("syslog.log", "udev.log", "process.log", "audit.log", "net.log"):
        assert name in text


def test_run_vm_embeds_phase2_deb_sha256():
    text = RUN_VM.read_text(encoding="utf-8")
    for digest in PHASE2_SHA256:
        assert digest in text
