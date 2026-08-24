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

mkdir -p "$RUN" "$LOGS" "$RUN/debs"
chmod 0700 "$RUN"
touch "$LOGS/syslog.log" "$LOGS/udev.log" "$LOGS/process.log" "$LOGS/audit.log" "$LOGS/net.log"
if [ -L "$LOGS/syslog.log" ] || [ -L "$LOGS/udev.log" ] || [ -L "$LOGS/process.log" ] \
  || [ -L "$LOGS/audit.log" ] || [ -L "$LOGS/net.log" ]; then
  echo "log paths must be regular files" >&2
  exit 1
fi

DEBS="$RUN/debs"
fetch_deb() {
  local url=$1 sha=$2
  local dest="$DEBS/$(basename "$url")"
  if [ ! -f "$dest" ]; then
    echo "downloading $url"
    curl -L --fail -o "$dest.partial" "$url"
    got="$(shasum -a 256 "$dest.partial" | awk '{print $1}')"
    if [ "$got" != "$sha" ]; then
      echo "checksum mismatch $dest" >&2
      rm -f "$dest.partial"
      exit 1
    fi
    mv "$dest.partial" "$dest"
  else
    got="$(shasum -a 256 "$dest" | awk '{print $1}')"
    if [ "$got" != "$sha" ]; then
      echo "checksum mismatch $dest" >&2
      exit 1
    fi
  fi
}
fetch_deb "https://deb.debian.org/debian/pool/main/a/audit/libaudit1_3.0.9-1_amd64.deb" \
  "30954df4b5a7c505661ba8ae5e6ea94f5805e408899fb400783bb166eb5ff306"
fetch_deb "https://deb.debian.org/debian/pool/main/a/audit/libauparse0_3.0.9-1_amd64.deb" \
  "ee3b6378d7145e88bf2d226a735b124b9b85d792bd1ead10da797427853894d3"
fetch_deb "https://deb.debian.org/debian/pool/main/t/tcp-wrappers/libwrap0_7.6.q-32_amd64.deb" \
  "cbce2669a3ba4d74cfdc52b14f38014893e23d85a33d109a3422c342eefc55f8"
fetch_deb "https://deb.debian.org/debian/pool/main/a/audit/auditd_3.0.9-1_amd64.deb" \
  "0d5a20ad6a0348a183fa3f2b58aff06ecd0e475cd9322c8bd4443db3e6454cd1"

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
  "$GUEST/99-lab-usb.rules" "$GUEST/lab-journal-forward.service" \
  "$GUEST/lab-audit-forward" "$GUEST/lab-audit-forward.service" \
  "$GUEST/audit.rules" "$GUEST/auditd.conf" "$CIDIR/"
cp "$DEBS/libaudit1_3.0.9-1_amd64.deb" "$DEBS/libauparse0_3.0.9-1_amd64.deb" \
  "$DEBS/libwrap0_7.6.q-32_amd64.deb" "$DEBS/auditd_3.0.9-1_amd64.deb" "$CIDIR/"
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
