#!/usr/bin/env bash
# Boot the pinned Debian 12 guest. 9p-exports infra/endpoint/logs only. -nic none.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -n "${1:-}" ]; then
  echo "no extra arguments" >&2
  exit 2
fi

# Dated bookworm build (not latest). Debian publishes SHA512 for this object;
# the script verifies SHA512. Hex below is SHA512 of debian-12-generic-amd64-20260821-2577.qcow2.
IMAGE_URL="https://cloud.debian.org/images/cloud/bookworm/20260821-2577/debian-12-generic-amd64-20260821-2577.qcow2"
IMAGE_SHA512="ee13344d530f70ca055d880e5c9b61e9af89874af02c5e2a5c26724461c79409e6d76db97c67ab222e71d03c3e33a738a8958fa5c497962f592258e9835cfcb0"
IMAGE_SHA256="verified-via-sha512-debian-publish"

RUN="$ROOT/infra/endpoint/run"
LOGS="$ROOT/infra/endpoint/logs"
GUEST="$ROOT/infra/endpoint/guest"
CACHE="$RUN/debian-12-generic-amd64-20260821-2577.qcow2"
OVERLAY="$RUN/overlay.qcow2"
SEED="$RUN/seed.iso"
SOCK="$RUN/monitor.sock"
SHARE="$LOGS"

mkdir -p "$RUN" "$LOGS"
chmod 0700 "$RUN"
touch "$LOGS/syslog.log" "$LOGS/udev.log" "$LOGS/process.log" "$LOGS/audit.log" "$LOGS/net.log"
if [ -L "$LOGS/syslog.log" ] || [ -L "$LOGS/udev.log" ] || [ -L "$LOGS/process.log" ] \
  || [ -L "$LOGS/audit.log" ] || [ -L "$LOGS/net.log" ]; then
  echo "log paths must be regular files" >&2
  exit 1
fi

if [ ! -f "$CACHE" ]; then
  echo "downloading $IMAGE_URL"
  curl -L --fail -o "$CACHE.partial" "$IMAGE_URL"
  got="$(shasum -a 512 "$CACHE.partial" | awk '{print $1}')"
  if [ "$got" != "$IMAGE_SHA512" ]; then
    echo "checksum mismatch" >&2
    rm -f "$CACHE.partial"
    exit 1
  fi
  mv "$CACHE.partial" "$CACHE"
fi

rm -f "$OVERLAY"
qemu-img create -f qcow2 -F qcow2 -b "$CACHE" "$OVERLAY" 8G

# Build nocloud ISO with guest files beside user-data.
CIDIR="$(mktemp -d)"
cp "$GUEST/cloud-init.yaml" "$CIDIR/user-data"
printf 'instance-id: lab-endpoint\nlocal-hostname: lab-endpoint\n' >"$CIDIR/meta-data"
cp "$GUEST/journal_map.py" "$GUEST/lab-journal-forward" "$GUEST/lab-usb-ingest" \
  "$GUEST/99-lab-usb.rules" "$GUEST/lab-journal-forward.service" "$CIDIR/"
if command -v genisoimage >/dev/null 2>&1; then
  genisoimage -output "$SEED" -volid cidata -joliet -rock "$CIDIR"
elif command -v mkisofs >/dev/null 2>&1; then
  mkisofs -output "$SEED" -volid cidata -joliet -rock "$CIDIR"
elif command -v hdiutil >/dev/null 2>&1; then
  hdiutil makehybrid -o "$SEED" -hfs -joliet -iso -default-volume-name cidata "$CIDIR"
else
  echo "need genisoimage, mkisofs, or hdiutil to build cloud-init ISO" >&2
  rm -rf "$CIDIR"
  exit 1
fi
rm -rf "$CIDIR"

# 9p source is infra/endpoint/logs only — never infra/endpoint (would export helpers).
exec qemu-system-x86_64 \
  -m 1024 \
  -smp 2 \
  -nic none \
  -drive "file=$OVERLAY,if=virtio,format=qcow2" \
  -cdrom "$SEED" \
  -fsdev "local,id=lablogs,path=$SHARE,security_model=mapped,writeout=immediate" \
  -device "virtio-9p-pci,fsdev=lablogs,mount_tag=labendpoint" \
  -monitor "unix:$SOCK,server,nowait" \
  -nographic
