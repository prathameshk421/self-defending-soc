#!/usr/bin/env bash
# Build VFAT image containing lab-marker.sh only. Not committed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
if [ -n "${1:-}" ]; then
  echo "no extra arguments" >&2
  exit 2
fi
OUT="$ROOT/infra/endpoint/run/lab-stick.img"
mkdir -p "$ROOT/infra/endpoint/run"
rm -f "$OUT"
# 1 MiB FAT
dd if=/dev/zero of="$OUT" bs=1m count=1 status=none
if command -v mkfs.vfat >/dev/null 2>&1; then
  mkfs.vfat -n LABSTICK "$OUT"
elif command -v newfs_msdos >/dev/null 2>&1; then
  newfs_msdos -F 16 -v LABSTICK "$OUT"
else
  echo "need mkfs.vfat or newfs_msdos" >&2
  exit 1
fi
MNT="$(mktemp -d)"
cleanup() { umount "$MNT" 2>/dev/null || true; rmdir "$MNT"; }
trap cleanup EXIT
if mount -t msdos "$OUT" "$MNT" 2>/dev/null || mount -o loop "$OUT" "$MNT" 2>/dev/null; then
  cp "$ROOT/infra/endpoint/usb/lab-marker.sh" "$MNT/lab-marker.sh"
else
  echo "could not mount VFAT image to copy marker; image created empty at $OUT" >&2
fi
