#!/usr/bin/env bash
# Aplica o patch macOS occlusion-resume (flutter/flutter#155977, commit d70a0d3)
# no clone Flutter do GitHub. Idempotente: reaplica após git pull se necessário.
set -euo pipefail

apply_flutter_engine_patch() {
  local script_dir root patch flutter_root marker engine_mm
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  root="$(cd "$script_dir/.." && pwd)"
  patch="$root/scripts/patches/flutter-d70a0d3-macos-occlusion-resume.patch"
  flutter_root="${FLUTTER_ROOT:-${FLUTTER_GITHUB_DIR:-$HOME/dev/flutter-github}}"
  marker="_visible = YES;"
  engine_mm="$flutter_root/engine/src/flutter/shell/platform/darwin/macos/framework/Source/FlutterEngine.mm"

  patch_log() { echo "[flutter-patch] $*"; }
  patch_die() { patch_log "ERRO: $*"; return 1; }

  [[ -f "$patch" ]] || patch_die "patch não encontrado: $patch"
  [[ -d "$flutter_root/.git" ]] || patch_die "Flutter não encontrado em $flutter_root"
  [[ -f "$engine_mm" ]] || patch_die "FlutterEngine.mm não encontrado (engine ausente?)"

  if grep -qF "$marker" "$engine_mm" 2>/dev/null && \
     grep -qF "github.com/flutter/flutter/issues/155977" "$engine_mm" 2>/dev/null; then
    patch_log "patch d70a0d3 já aplicado em $flutter_root"
    export FLUTTER_ENGINE_PATCH_APPLIED=1
    return 0
  fi

  patch_log "aplicando patch d70a0d3 (macos occlusion-resume) em $flutter_root"
  if git -C "$flutter_root" apply --check "$patch" 2>/dev/null; then
    git -C "$flutter_root" apply "$patch"
  elif git -C "$flutter_root" apply --3way "$patch"; then
    patch_log "patch aplicado com merge (--3way)"
  else
    patch_die "falha ao aplicar $patch — resolva conflitos manualmente em $flutter_root"
    return 1
  fi

  export FLUTTER_ENGINE_PATCH_APPLIED=1
  patch_log "patch aplicado. Para o fix entrar no app macOS, compile o engine local:"
  patch_log "  ./scripts/build-flutter-local-engine-macos.sh"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  apply_flutter_engine_patch
else
  apply_flutter_engine_patch || return $?
fi
