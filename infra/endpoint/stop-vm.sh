#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -n "${1:-}" ]; then
  echo "no extra arguments" >&2
  exit 2
fi
SOCK="$ROOT/infra/endpoint/run/monitor.sock"
if [ -S "$SOCK" ]; then
  printf 'quit\n' | nc -U "$SOCK" || true
fi
