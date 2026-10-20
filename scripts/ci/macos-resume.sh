#!/usr/bin/env bash
# Resume one macOS packaging stage from a checkpoint. Does not compile.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
stage="${1:-}"
checkpoint="${2:-}"
output="${3:-}"
python="$ROOT/scripts/ci/macos_checkpoint.py"

fail() { echo "[macOS] ERRO: $*" >&2; exit 1; }
[[ "$stage" == "package" || "$stage" == "notarize" || "$stage" == "staple" || "$stage" == "validate" ]] || \
  fail "Etapa desconhecida: $stage"
[[ -d "$checkpoint" ]] || fail "Checkpoint não encontrado: $checkpoint"

verify() {
  python3 "$python" --dir "$checkpoint" verify --name "$1"
}

case "$stage" in
  package)
    verify app.tar
    work="$(mktemp -d "${TMPDIR:-/tmp}/bgdesk-resume-app.XXXXXX")"
    trap 'rm -rf "$work"' EXIT
    COPYFILE_DISABLE=1 tar -xf "$checkpoint/app.tar" -C "$work"
    [[ -d "$work/BGDesk.app" ]] || fail "O app.tar não contém BGDesk.app."
    BGDESK_PACKAGE_STAGE=package BGDESK_CHECKPOINT_DIR="$checkpoint" \
      bash "$ROOT/scripts/package-macos.sh" "$work/BGDesk.app" "$output"
    ;;
  notarize)
    verify signed.dmg
    BGDESK_PACKAGE_STAGE=notarize BGDESK_CHECKPOINT_DIR="$checkpoint" \
      bash "$ROOT/scripts/package-macos.sh" "$checkpoint/signed.dmg" "$output"
    ;;
  staple)
    verify signed.dmg
    BGDESK_PACKAGE_STAGE=staple BGDESK_CHECKPOINT_DIR="$checkpoint" \
      bash "$ROOT/scripts/package-macos.sh" "$checkpoint/signed.dmg" "$output"
    ;;
  validate)
    image="$checkpoint/delivered.dmg"
    [[ -f "$image" ]] || image="$checkpoint/signed.dmg"
    verify "$(basename "$image")"
    BGDESK_PACKAGE_STAGE=validate bash "$ROOT/scripts/package-macos.sh" "$image"
    ;;
esac
