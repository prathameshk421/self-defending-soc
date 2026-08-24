# Lab Linux endpoint (operator)

This is **not** a merge gate. CI uses goldens. Live QEMU is optional.

## What you get

A Debian 12 guest with no NIC (`-nic none`). It writes JSON lines into `infra/endpoint/logs/` over virtio-9p. Vector (compose) tails those files as `lab-endpoint`.

`run-vm.sh` always deletes `overlay.qcow2` then recreates it from the pinned base. Journal cursor on qcow is lost every boot.

Do not add a NIC to make sshd goldens “live.” Those lines are fixtures.

USB helper is **copy-only**: it copies the marker and writes `file_create`. It does **not** write `process_create` and does **not** exec stick bytes.

Guest `lab-audit-forward` keep-filters allowlisted SYSCALL records onto `audit.log`. Compose already tails that file.

## Prereqs

QEMU (`qemu-system-x86_64`, `qemu-img`), `curl`, `nc` with `-U`, and an ISO builder (`genisoimage` / `mkisofs` / macOS `hdiutil`).

## Run

```sh
# from repo root
chmod +x infra/endpoint/*.sh infra/endpoint/usb/*.sh infra/endpoint/guest/lab-journal-forward infra/endpoint/guest/lab-usb-ingest infra/endpoint/guest/lab-audit-forward
./infra/endpoint/usb/build-stick.sh
./infra/endpoint/run-vm.sh
# other terminal, after boot:
./infra/endpoint/attach-usb.sh
# logs appear in infra/endpoint/logs/
./infra/endpoint/detach-usb.sh
./infra/endpoint/stop-vm.sh   # monitor quit only; no guest-agent
```

Image pin is the dated URL in `run-vm.sh` (bookworm/20260821-2577), verified with Debian’s SHA512.

Phase 1 hashed auditd `.deb`s are downloaded into `infra/endpoint/run/debs/` (SHA256) and copied onto the nocloud ISO. Guest `dpkg -i` never `apt`. After boot, confirm `audit.log` lines; compose already tails them.

9p exports **only** `infra/endpoint/logs`. Scripts reject extra argv. Monitor socket is unix, directory mode 0700.

## Operator ingest smoke (not pytest)

Compose already tails the host files. After `docker compose up -d --build` in `infra/` and `soc-agent-ingest` is healthy, append a syslog JSON line onto `infra/endpoint/logs/syslog.log` (regular file) and consume `soc.events.v1` as `User:admin` from the same Kafka image on `lab-net`. Success is Event JSON with `asset_id` `11111111-1111-4111-8111-111111111107`. Do not use `ingest emit`. Do not publish 9092/8081. Full command: `docs/ingest-layer.md` (“If you want to see it move”).
