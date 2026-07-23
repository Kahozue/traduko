#!/usr/bin/env bash
# Build the core as a one-folder sidecar and place it where the Tauri
# bundler (bundle.resources) expects it. The folder is copied wholesale into
# the app's resource directory, so no host-triple suffix is needed: each
# platform bundles the sidecar it just built.
set -euo pipefail
cd "$(dirname "$0")"

OUT_DIR="../../app/src-tauri/binaries/traduko-core"

uv run pyinstaller --clean --noconfirm traduko-core.spec

rm -rf "$OUT_DIR"
mkdir -p "$(dirname "$OUT_DIR")"
cp -R "dist/traduko-core" "$OUT_DIR"
echo "sidecar written to $OUT_DIR"
