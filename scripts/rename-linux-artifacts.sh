#!/usr/bin/env bash
# Rename Cargo output artifacts to BGDesk names so installers and Flutter Linux
# bundle pick up bgdesk / libbgdesk.so instead of rustdesk / liblibrustdesk.so.
#
# Usage:
#   ./scripts/rename-linux-artifacts.sh [target-triple]
# Examples:
#   ./scripts/rename-linux-artifacts.sh
#   ./scripts/rename-linux-artifacts.sh x86_64-unknown-linux-gnu
#   ./scripts/rename-linux-artifacts.sh aarch64-unknown-linux-gnu

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Linux" ]]; then
  exit 0
fi

BASE="target"
if [[ -n "${1:-}" ]]; then
  BASE="target/$1"
fi

rename_in_dir() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0

  if [[ -f "$dir/rustdesk" ]]; then
    mv -f "$dir/rustdesk" "$dir/bgdesk"
    echo "[rename-linux-artifacts] $dir/rustdesk -> $dir/bgdesk"
  fi

  if [[ -f "$dir/liblibrustdesk.so" ]]; then
    rm -rf "$dir/libbgdesk.so"
    mv -f "$dir/liblibrustdesk.so" "$dir/libbgdesk.so"
    echo "[rename-linux-artifacts] $dir/liblibrustdesk.so -> $dir/libbgdesk.so"
  fi
}

rename_in_dir "$BASE/release"
rename_in_dir "$BASE/debug"
