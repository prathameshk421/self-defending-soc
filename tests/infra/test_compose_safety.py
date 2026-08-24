"""Compose + endpoint script safety: no docker.sock, file binds not directory bind."""

from __future__ import annotations

import stat
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "infra" / "compose.yaml"
LOG_DIR = REPO_ROOT / "infra" / "endpoint" / "logs"
SCRIPTS_DIR = REPO_ROOT / "infra" / "endpoint"

FILE_BINDS = [
    "./endpoint/logs/syslog.log:/var/log/lab/lab-endpoint/syslog.log:ro",
    "./endpoint/logs/udev.log:/var/log/lab/lab-endpoint/udev.log:ro",
    "./endpoint/logs/process.log:/var/log/lab/lab-endpoint/process.log:ro",
]


def test_endpoint_log_stubs_are_regular_files():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("syslog.log", "udev.log", "process.log", "audit.log", "net.log"):
        path = LOG_DIR / name
        if not path.exists():
            path.touch()
        assert path.is_file()
        assert not path.is_symlink()
        assert not stat.S_ISDIR(path.stat().st_mode)


def test_vector_file_binds_not_directory():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    volumes = data["services"]["vector"]["volumes"]
    for bind in FILE_BINDS:
        assert bind in volumes
    for vol in volumes:
        assert not str(vol).startswith("./endpoint/logs:")
        assert "docker.sock" not in str(vol)
        assert "monitor.sock" not in str(vol)
    svc = data["services"]["vector"]
    assert svc.get("privileged") in (None, False)
    assert svc.get("network_mode") != "host"


def test_endpoint_scripts_have_no_docker_sock_or_host_net():
    if not SCRIPTS_DIR.exists():
        return
    for path in SCRIPTS_DIR.rglob("*.sh"):
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.split("#", 1)[0]
            lines.append(stripped)
        body = "\n".join(lines)
        assert "docker.sock" not in body, path
        assert "network_mode: host" not in body, path


def test_kafka_init_raw_retention_bytes():
    text = (REPO_ROOT / "infra" / "kafka-init.sh").read_text(encoding="utf-8")
    assert "soc.raw.v1" in text
    assert "retention.bytes=1073741824" in text
    assert "retention.ms=172800000" in text


def test_ingest_service_is_closed():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    svc = data["services"]["soc-agent-ingest"]
    assert svc.get("ports") in (None, [])
    assert svc.get("privileged") in (None, False)
    assert svc.get("network_mode") != "host"
    assert svc["mem_limit"] == "512m"
    assert svc["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in svc["security_opt"]
    volumes = [str(v) for v in svc.get("volumes", [])]
    for vol in volumes:
        assert "docker.sock" not in vol
        assert "monitor.sock" not in vol
        assert "endpoint/logs" not in vol
    env = svc["environment"]
    assert env["INGEST_BOOTSTRAP"] == "kafka:9092"
    assert env["INGEST_REGISTRY_URL"] == "http://karapace:8081"
    assert env["INGEST_SASL_USERNAME"] == "ingest"
    assert env["INGEST_GROUP_ID"] == "ingest-normalizer"
    depends = svc["depends_on"]
    assert depends["kafka"]["condition"] == "service_healthy"
    assert depends["kafka-init"]["condition"] == "service_completed_successfully"
    assert depends["karapace"]["condition"] == "service_healthy"
    dockerfile = (REPO_ROOT / "infra" / "ingest" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "python:3.12-bookworm@sha256:80f5d259a5969c86f6c92145d572de4a68c68e0edd28d4367dec0fb411b42af3" in dockerfile
    assert "pip install --no-cache-dir '.[kafka]'" in dockerfile
    assert "bind" not in dockerfile.lower()
