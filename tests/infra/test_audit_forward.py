"""Load lab-audit-forward via SourceFileLoader — ingest/estate do not import it."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FORWARD_PATH = REPO_ROOT / "infra" / "endpoint" / "guest" / "lab-audit-forward"

SAMPLE = (
    "type=SYSCALL msg=audit(1690000000.000000:1): arch=c000003e syscall=59 "
    'success=yes exit=0 a0=1 a1=2 a2=0 a3=0 items=1 ppid=1 pid=9 '
    'exe="/bin/ls"\n'
    'type=EXECVE msg=audit(1690000000.000000:1): argc=2 a0="/bin/ls" a1="-l"\n'
)

PHASE1_SHA256 = (
    "30954df4b5a7c505661ba8ae5e6ea94f5805e408899fb400783bb166eb5ff306",
    "ee3b6378d7145e88bf2d226a735b124b9b85d792bd1ead10da797427853894d3",
    "cbce2669a3ba4d74cfdc52b14f38014893e23d85a33d109a3422c342eefc55f8",
    "0d5a20ad6a0348a183fa3f2b58aff06ecd0e475cd9322c8bd4443db3e6454cd1",
)


def _load():
    loader = importlib.machinery.SourceFileLoader(
        "lab_endpoint_audit_forward", str(FORWARD_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load()


def test_keep_execve(mod):
    out = list(mod.records_from_text(SAMPLE))
    assert len(out) == 1
    assert out[0]["source"] == "auditd"
    assert out[0]["syscall"] == "execve"
    assert out[0]["command_line"] == "/bin/ls -l"
    assert out[0]["timestamp"] == "2023-07-22T04:26:40.000000+00:00"


def test_drop_success_no(mod):
    text = SAMPLE.replace("success=yes", "success=no")
    assert list(mod.records_from_text(text)) == []


def test_drop_execveat(mod):
    text = (
        "type=SYSCALL msg=audit(1690000000.000000:2): arch=c000003e syscall=322 "
        'success=yes exit=0 a0=1 a1=2 a2=0 a3=0 items=0 ppid=1 pid=9 '
        'exe="/bin/ls"\n'
    )
    assert list(mod.records_from_text(text)) == []


def test_drop_openat_without_creat(mod):
    text = (
        "type=SYSCALL msg=audit(1690000000.000000:3): arch=c000003e syscall=257 "
        'success=yes exit=0 a0=1 a1=2 a2=0 a3=0 items=1 ppid=1 pid=9 '
        'exe="/bin/touch"\n'
    )
    assert list(mod.records_from_text(text)) == []


def test_truncate_command_line(mod):
    long_arg = "x" * 20000
    text = (
        "type=SYSCALL msg=audit(1690000000.000000:4): arch=c000003e syscall=59 "
        'success=yes exit=0 a0=1 a1=2 a2=0 a3=0 items=1 ppid=1 pid=9 '
        'exe="/bin/echo"\n'
        f'type=EXECVE msg=audit(1690000000.000000:4): argc=2 a0="/bin/echo" a1="{long_arg}"\n'
    )
    out = list(mod.records_from_text(text))
    assert len(out) == 1
    assert out[0]["command_line"].endswith("...")
    assert len(out[0]["command_line"].encode("utf-8")) <= 16387


def test_format_is_one_object_one_newline(mod):
    rec = list(mod.records_from_text(SAMPLE))[0]
    line = mod.format_audit_line(rec)
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert json.loads(line) == rec


def test_forwarder_source_locks():
    text = FORWARD_PATH.read_text(encoding="utf-8")
    assert "O_NOFOLLOW" in text
    assert 'source":"auditd"' in text or "'auditd'" in text


def test_run_vm_embeds_phase1_deb_sha256():
    text = (REPO_ROOT / "infra" / "endpoint" / "run-vm.sh").read_text(encoding="utf-8")
    for digest in PHASE1_SHA256:
        assert digest in text
