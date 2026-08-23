#!/usr/bin/env bash
# Attach hardcoded USB image via QEMU unix monitor. No extra argv.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -n "${1:-}" ]; then
  echo "no extra arguments" >&2
  exit 2
fi
SOCK="$ROOT/infra/endpoint/run/monitor.sock"
IMG="$ROOT/infra/endpoint/run/lab-stick.img"
# device_add usb-storage with drive_add of lab-stick.img
printf 'drive_add 0 if=none,id=lab-stick,format=raw,file=%s\n' "$IMG" | nc -U "$SOCK"
printf 'device_add usb-storage,id=lab-stick-dev,drive=lab-stick\n' | nc -U "$SOCK"
