#!/usr/bin/env bash
# Remove do clone Flutter GitHub tudo que não é necessário para recompilar o BGDesk
# com --local-engine (após o engine já ter sido compilado com o patch).
#
# Mantém:
#   - SDK Flutter (bin/, packages/, version, ...)
#   - engine/src/out/<config>/ artefatos de runtime (framework, gen_snapshot, dart-sdk, ...)
#
# Remove:
#   - source do engine (~17GB), obj/ ninja (~12GB), testes, docs, examples, depot_tools
#
# Uso:
#   ./scripts/prune-flutter-github.sh
#   FLUTTER_ENGINE_CONFIG=host_release_arm64 ./scripts/prune-flutter-github.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_ROOT="${FLUTTER_ROOT:-${FLUTTER_GITHUB_DIR:-$HOME/dev/flutter-github}}"
ENGINE_CONFIG="${FLUTTER_ENGINE_CONFIG:-host_release_arm64}"
OUT_DIR="$FLUTTER_ROOT/engine/src/out/$ENGINE_CONFIG"
DEPOT_TOOLS="${DEPOT_TOOLS:-$HOME/dev/depot_tools}"
MARKER="$OUT_DIR/.bgdesk-engine-pruned"

log() { echo "[flutter-prune] $*"; }
die() { log "ERRO: $*"; exit 1; }

bytes_human() {
  local kib="$1"
  if command -v numfmt >/dev/null 2>&1; then
    numfmt --to=iec-i --suffix=B "$((kib * 1024))" 2>/dev/null || echo "${kib}K"
  else
    echo "${kib}K"
  fi
}

dir_kib() {
  local p="$1"
  [[ -e "$p" ]] || { echo 0; return; }
  du -sk "$p" 2>/dev/null | awk '{print $1}'
}

remove_path() {
  local p="$1"
  local kib
  [[ -e "$p" || -L "$p" ]] || return 0
  kib="$(dir_kib "$p")"
  log "removendo $(bytes_human "$kib"): $p"
  rm -rf "$p"
  FREED_KIB=$((FREED_KIB + kib))
}

[[ "$(uname -s)" == "Darwin" ]] || die "apenas macOS"
[[ -d "$FLUTTER_ROOT/bin" ]] || die "Flutter não encontrado em $FLUTTER_ROOT"
[[ -d "$OUT_DIR/FlutterMacOS.framework" ]] || \
  die "FlutterMacOS.framework ausente em $OUT_DIR — compile o engine antes"
[[ -d "$OUT_DIR/FlutterMacOS.xcframework" ]] || \
  die "FlutterMacOS.xcframework ausente em $OUT_DIR — compile o engine antes"
[[ -e "$OUT_DIR/gen_snapshot_arm64" || -x "$OUT_DIR/artifacts_arm64/gen_snapshot_arm64" ]] || \
  die "gen_snapshot_arm64 ausente em $OUT_DIR"

FREED_KIB=0
BEFORE_KIB="$(dir_kib "$FLUTTER_ROOT")"
log "Flutter: $FLUTTER_ROOT ($(bytes_human "$BEFORE_KIB"))"
log "engine out: $OUT_DIR"

# --- engine source (tudo fora de out/) ---
if [[ -d "$FLUTTER_ROOT/engine/src" ]]; then
  while IFS= read -r -d '' entry; do
    base="$(basename "$entry")"
    [[ "$base" == "out" ]] && continue
    remove_path "$entry"
  done < <(find "$FLUTTER_ROOT/engine/src" -mindepth 1 -maxdepth 1 -print0)
fi
# scripts do engine (só úteis para gclient / rebuild)
remove_path "$FLUTTER_ROOT/engine/scripts"
remove_path "$FLUTTER_ROOT/.gclient"
remove_path "$FLUTTER_ROOT/.gclient_entries"
remove_path "$FLUTTER_ROOT/.cipd"
remove_path "$FLUTTER_ROOT/.gemini"

# --- dentro do out: manter só o necessário para --local-engine ---
KEEP_NAMES=(
  FlutterMacOS.framework
  FlutterMacOS.xcframework
  FlutterMacOS.stamp
  artifacts_arm64
  gen_snapshot
  gen_snapshot_arm64
  gen_snapshot_host_targeting_host
  dart-sdk
  flutter_patched_sdk
  flutter_patched_sdk_product
  font-subset
  impellerc
  icudtl.dat
  shader_lib
  shaders
  clang_arm64
  universal
  gen
)

if [[ -d "$OUT_DIR" ]]; then
  while IFS= read -r -d '' entry; do
    base="$(basename "$entry")"
    keep=0
    for k in "${KEEP_NAMES[@]}"; do
      if [[ "$base" == "$k" ]]; then
        keep=1
        break
      fi
    done
    # marker / nosso arquivo
    [[ "$base" == .bgdesk-engine-pruned ]] && keep=1
    [[ "$base" == .bgdesk-engine-patch ]] && keep=1
    [[ $keep -eq 1 ]] && continue
    remove_path "$entry"
  done < <(find "$OUT_DIR" -mindepth 1 -maxdepth 1 -print0)
fi

# gen/: só sky_engine + const_finder
if [[ -d "$OUT_DIR/gen" ]]; then
  while IFS= read -r -d '' entry; do
    base="$(basename "$entry")"
    case "$base" in
      dart-pkg|const_finder.dart.snapshot|const_finder.dart.snapshot.d) continue ;;
      *) remove_path "$entry" ;;
    esac
  done < <(find "$OUT_DIR/gen" -mindepth 1 -maxdepth 1 -print0)
  if [[ -d "$OUT_DIR/gen/dart-pkg" ]]; then
    while IFS= read -r -d '' entry; do
      base="$(basename "$entry")"
      case "$base" in
        sky_engine|sky_engine.stamp) continue ;;
        *) remove_path "$entry" ;;
      esac
    done < <(find "$OUT_DIR/gen/dart-pkg" -mindepth 1 -maxdepth 1 -print0)
  fi
fi

# Garante symlinks gen_snapshot_arm64
if [[ -x "$OUT_DIR/artifacts_arm64/gen_snapshot_arm64" ]]; then
  ln -sfn "$OUT_DIR/artifacts_arm64/gen_snapshot_arm64" "$OUT_DIR/gen_snapshot_arm64"
  mkdir -p "$OUT_DIR/universal" "$OUT_DIR/clang_arm64"
  ln -sfn "$OUT_DIR/artifacts_arm64/gen_snapshot_arm64" "$OUT_DIR/universal/gen_snapshot_arm64"
  ln -sfn "$OUT_DIR/artifacts_arm64/gen_snapshot_arm64" "$OUT_DIR/clang_arm64/gen_snapshot_arm64"
fi

# --- SDK Flutter: docs/examples/dev ---
remove_path "$FLUTTER_ROOT/examples"
remove_path "$FLUTTER_ROOT/docs"
remove_path "$FLUTTER_ROOT/dev"
remove_path "$FLUTTER_ROOT/agent-artifacts"
remove_path "$FLUTTER_ROOT/buildtools"
remove_path "$FLUTTER_ROOT/third_party"

# cache: engines pré-compilados oficiais (usamos local-engine).
# podhelper.rb ainda exige darwin-x64(/-release)/FlutterMacOS.xcframework — só
# checa existência; recria stubs apontando para o out/ local.
if [[ -d "$FLUTTER_ROOT/bin/cache/artifacts/engine" ]]; then
  remove_path "$FLUTTER_ROOT/bin/cache/artifacts/engine"
fi
CACHE_ENGINE="$FLUTTER_ROOT/bin/cache/artifacts/engine"
for stub in darwin-x64 darwin-x64-release; do
  mkdir -p "$CACHE_ENGINE/$stub"
  ln -sfn "$OUT_DIR/FlutterMacOS.xcframework" "$CACHE_ENGINE/$stub/FlutterMacOS.xcframework"
done
log "stubs CocoaPods: $CACHE_ENGINE/{darwin-x64,darwin-x64-release}/FlutterMacOS.xcframework -> out/"
# artefatos iOS/Android USB desnecessários no build macOS desktop
for name in ios-deploy libimobiledevice libimobiledeviceglue libplist libusbmuxd openssl; do
  remove_path "$FLUTTER_ROOT/bin/cache/artifacts/$name"
done
remove_path "$FLUTTER_ROOT/bin/cache/downloads"

# depot_tools só serve para rebuild do engine
remove_path "$DEPOT_TOOLS"

# Marca árvore podada — setup/apply patch não tentam recompilar source
{
  echo "pruned_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "engine_config=$ENGINE_CONFIG"
  echo "patch_ref=4332f3e-macos-occlusion-resume"
  echo "flutter_commit=$(git -C "$FLUTTER_ROOT" -c core.hooksPath=/dev/null rev-parse HEAD 2>/dev/null || echo unknown)"
} > "$MARKER"
echo "4332f3e-macos-occlusion-resume" > "$OUT_DIR/.bgdesk-engine-patch"

AFTER_KIB="$(dir_kib "$FLUTTER_ROOT")"
log "antes:  $(bytes_human "$BEFORE_KIB")"
log "depois: $(bytes_human "$AFTER_KIB")"
log "liberado ~$(bytes_human "$FREED_KIB")"
log "marker: $MARKER"
log "OK — clone pronto para builds BGDesk (sem rebuild do engine source)"
