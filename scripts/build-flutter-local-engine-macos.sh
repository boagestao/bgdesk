#!/usr/bin/env bash
# Compila o Flutter engine local (macOS arm64 release) com o patch de occlusion-resume.
# Requer: Xcode, depot_tools, ninja (brew install ninja).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_ROOT="${FLUTTER_ROOT:-${FLUTTER_GITHUB_DIR:-$HOME/dev/flutter-github}}"
DEPOT_TOOLS="${DEPOT_TOOLS:-$HOME/dev/depot_tools}"
ENGINE_CONFIG="${FLUTTER_ENGINE_CONFIG:-host_release_arm64}"
OUT_DIR="$FLUTTER_ROOT/engine/src/out/$ENGINE_CONFIG"

log() { echo "[flutter-engine] $*"; }
die() { log "ERRO: $*"; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "apenas macOS"

# shellcheck source=/dev/null
source "$ROOT/scripts/setup-flutter-github.sh"
# shellcheck source=/dev/null
source "$ROOT/scripts/apply-flutter-engine-patch.sh"

if [[ ! -d "$DEPOT_TOOLS" ]]; then
  log "clonando depot_tools em $DEPOT_TOOLS"
  mkdir -p "$(dirname "$DEPOT_TOOLS")"
  git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git "$DEPOT_TOOLS"
fi
export PATH="$DEPOT_TOOLS:$PATH"

if ! command -v ninja >/dev/null 2>&1; then
  die "ninja não encontrado. Instale com: brew install ninja"
fi

GCLIENT_FILE="$FLUTTER_ROOT/.gclient"
if [[ ! -f "$GCLIENT_FILE" ]]; then
  log "criando .gclient a partir de engine/scripts/standard.gclient"
  cp "$FLUTTER_ROOT/engine/scripts/standard.gclient" "$GCLIENT_FILE"
fi

if [[ ! -d "$FLUTTER_ROOT/engine/src/flutter/third_party/skia" ]]; then
  log "gclient sync (primeira vez — pode demorar e baixar vários GB)..."
  git -C "$FLUTTER_ROOT" config --local core.longpaths true 2>/dev/null || true
  (cd "$FLUTTER_ROOT" && gclient sync -D --no-history)
else
  log "sincronizando dependências do engine..."
  (cd "$FLUTTER_ROOT" && gclient sync -D)
fi

ET="$FLUTTER_ROOT/engine/src/flutter/bin/et"
[[ -x "$ET" ]] || die "et não encontrado em $ET"

log "compilando engine --config $ENGINE_CONFIG (pode demorar)..."
"$ET" build --config "$ENGINE_CONFIG"

[[ -d "$OUT_DIR" ]] || die "build não gerou $OUT_DIR"

export FLUTTER_LOCAL_ENGINE="$ENGINE_CONFIG"
export FLUTTER_LOCAL_ENGINE_HOST="$ENGINE_CONFIG"
export FLUTTER_ENGINE="$FLUTTER_ROOT/engine/src"

log "engine pronto: $OUT_DIR"
log "export FLUTTER_LOCAL_ENGINE=$FLUTTER_LOCAL_ENGINE"
log "export FLUTTER_LOCAL_ENGINE_HOST=$FLUTTER_LOCAL_ENGINE_HOST"
log "export FLUTTER_ENGINE=$FLUTTER_ENGINE"
