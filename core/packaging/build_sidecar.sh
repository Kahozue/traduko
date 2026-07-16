#!/usr/bin/env bash
# Build the core as a single-file sidecar binary and place it where the
# Tauri bundler (externalBin) expects it, suffixed with the host triple.
set -euo pipefail
cd "$(dirname "$0")"

TRIPLE="$(rustc -Vv | awk '/^host:/ {print $2}')"
OUT_DIR="../../app/src-tauri/binaries"

uv run pyinstaller --clean --noconfirm traduko-core.spec

mkdir -p "$OUT_DIR"
cp "dist/traduko-core" "$OUT_DIR/traduko-core-${TRIPLE}"
echo "sidecar written to $OUT_DIR/traduko-core-${TRIPLE}"
