#!/usr/bin/env bash
# Aplica o patch macOS occlusion-resume (flutter/flutter#188772 / #155977,
# commit 4332f3e) no clone Flutter do GitHub. Idempotente.
#
# Se o engine já foi compilado e a árvore foi podada
# (scripts/prune-flutter-github.sh), o source FlutterEngine.mm some — nesse
# caso consideramos o patch aplicado via marker no out/ local.
set -euo pipefail

apply_flutter_engine_patch() {
  local script_dir root patch flutter_root engine_mm engine_out marker
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  root="$(cd "$script_dir/.." && pwd)"
  patch="$root/scripts/patches/flutter-4332f3e-macos-occlusion-resume.patch"
  flutter_root="${FLUTTER_ROOT:-${FLUTTER_GITHUB_DIR:-$HOME/dev/flutter-github}}"
  engine_mm="$flutter_root/engine/src/flutter/shell/platform/darwin/macos/framework/Source/FlutterEngine.mm"
  engine_out="$flutter_root/engine/src/out/${FLUTTER_ENGINE_CONFIG:-host_release_arm64}"
  marker="$engine_out/.bgdesk-engine-patch"

  patch_log() { echo "[flutter-patch] $*"; }
  patch_die() { patch_log "ERRO: $*"; return 1; }

  [[ -d "$flutter_root/.git" || -x "$flutter_root/bin/flutter" ]] || \
    patch_die "Flutter não encontrado em $flutter_root"

  # Árvore podada: engine local já contém o fix.
  if [[ -f "$marker" ]] && \
     [[ -d "$engine_out/FlutterMacOS.framework" || -d "$engine_out/FlutterMacOS.xcframework" ]]; then
    patch_log "engine local podado com patch ($(cat "$marker")) em $engine_out"
    export FLUTTER_ENGINE_PATCH_APPLIED=1
    return 0
  fi

  if [[ -f "$engine_mm" ]] && \
     grep -qF "github.com/flutter/flutter/issues/155977" "$engine_mm" 2>/dev/null && \
     grep -qF "window.isVisible" "$engine_mm" 2>/dev/null; then
    patch_log "patch 4332f3e (PR #188772) já presente no source em $flutter_root"
    export FLUTTER_ENGINE_PATCH_APPLIED=1
    return 0
  fi

  [[ -f "$patch" ]] || patch_die "patch não encontrado: $patch"
  [[ -f "$engine_mm" ]] || patch_die "FlutterEngine.mm ausente (engine source removido?). Rode ./scripts/build-flutter-local-engine-macos.sh antes do prune."

  patch_log "aplicando patch 4332f3e (macos occlusion-resume, PR #188772) em $flutter_root"
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
  patch_log "depois pode liberar espaço:"
  patch_log "  ./scripts/prune-flutter-github.sh"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  apply_flutter_engine_patch
else
  apply_flutter_engine_patch || return $?
fi
