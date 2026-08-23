# Lab Linux endpoint (operator)

This is **not** a merge gate. CI uses goldens. Live QEMU is optional.

## What you get

A Debian 12 guest with no NIC. It writes JSON lines into `infra/endpoint/logs/` over virtio-9p. Vector (compose) tails those files as `lab-endpoint`.

Do not add a NIC to make sshd goldens “live.” Those lines are fixtures.

USB copy-then-exec still runs stick bytes as root. Autorun demo, not USB defense.

## Prereqs

QEMU (`qemu-system-x86_64`, `qemu-img`), `curl`, `nc` with `-U`, and an ISO builder (`genisoimage` / `mkisofs` / macOS `hdiutil`).

## Run

```sh
# from repo root
chmod +x infra/endpoint/*.sh infra/endpoint/usb/*.sh infra/endpoint/guest/lab-journal-forward infra/endpoint/guest/lab-usb-ingest
./infra/endpoint/usb/build-stick.sh
./infra/endpoint/run-vm.sh
# other terminal, after boot:
./infra/endpoint/attach-usb.sh
# logs appear in infra/endpoint/logs/
./infra/endpoint/detach-usb.sh
./infra/endpoint/stop-vm.sh   # monitor quit only; no guest-agent
```

Image pin is the dated URL in `run-vm.sh` (bookworm/20260821-2577), verified with Debian’s SHA512.

9p exports **only** `infra/endpoint/logs`. Scripts reject extra argv. Monitor socket is unix, directory mode 0700.
