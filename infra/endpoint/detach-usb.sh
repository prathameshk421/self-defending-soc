#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -n "${1:-}" ]; then
  echo "no extra arguments" >&2
  exit 2
fi
SOCK="$ROOT/infra/endpoint/run/monitor.sock"
printf 'device_del lab-stick-dev\n' | nc -U "$SOCK"
printf 'drive_del lab-stick\n' | nc -U "$SOCK"
