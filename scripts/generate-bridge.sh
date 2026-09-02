#!/usr/bin/env bash
# Gera generated_bridge.dart + generated_bridge.freezed.dart + bridge Rust.
#
# Usa o Flutter stable pinado (scripts/setup-flutter-stable.sh) para codegen
# e para build_runner/freezed.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v cargo >/dev/null 2>&1; then
  if [[ -f "${HOME}/.cargo/env" ]]; then
    # shellcheck source=/dev/null
    . "${HOME}/.cargo/env"
  fi
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "[bridge] ERRO: cargo não encontrado. Instale o Rust (https://rustup.rs) e rode: source \"\$HOME/.cargo/env\""
  exit 1
fi

FLUTTER_BRIDGE_DIR="${FLUTTER_BRIDGE_DIR:-$ROOT/.tools/flutter-stable}"
FLUTTER_BRIDGE_VERSION="${FLUTTER_BRIDGE_VERSION:-}"
FLUTTER_BRIDGE_MIN_DART_MAJOR=3
FLUTTER_BRIDGE_MIN_DART_MINOR=9

log() { echo "[bridge] $*"; }

bridge_flutter_dart_minor() {
  local flutter_bin="$1"
  "$flutter_bin" --version 2>/dev/null | sed -n 's/.*Dart \([0-9]*\)\.\([0-9]*\).*/\1 \2/p' | head -1
}

bridge_flutter_is_usable() {
  local flutter_bin="$FLUTTER_BRIDGE_DIR/bin/flutter"
  [[ -x "$flutter_bin" ]] || return 1
  local dart_parts major minor
  dart_parts="$(bridge_flutter_dart_minor "$flutter_bin")"
  major="${dart_parts%% *}"
  minor="${dart_parts##* }"
  [[ -n "$major" && -n "$minor" ]] \
    && (( major > FLUTTER_BRIDGE_MIN_DART_MAJOR \
      || (major == FLUTTER_BRIDGE_MIN_DART_MAJOR && minor >= FLUTTER_BRIDGE_MIN_DART_MINOR) ))
}

setup_bridge_flutter() {
  if bridge_flutter_is_usable; then
    return 0
  fi
  log "ERRO: Flutter em $FLUTTER_BRIDGE_DIR não tem Dart >= $FLUTTER_BRIDGE_MIN_DART_MAJOR.$FLUTTER_BRIDGE_MIN_DART_MINOR."
  log "Rode ./scripts/setup-flutter-stable.sh (Flutter $FLUTTER_BRIDGE_VERSION)."
  exit 1
}

# shellcheck source=/dev/null
source "$ROOT/scripts/setup-flutter-stable.sh"
FLUTTER_BRIDGE_DIR="${FLUTTER_ROOT}"
FLUTTER_BRIDGE_VERSION="${FLUTTER_STABLE_VERSION}"

if ! command -v flutter_rust_bridge_codegen &>/dev/null; then
  cargo install flutter_rust_bridge_codegen --version 1.80.1 --features "uuid" --locked
fi

log "gerando bridge (Rust + Dart, sem build_runner)..."
flutter_rust_bridge_codegen --no-build-runner \
  --rust-input ./src/flutter_ffi.rs \
  --dart-output ./flutter/lib/generated_bridge.dart \
  --c-output ./flutter/macos/Runner/bridge_generated.h

cp ./flutter/macos/Runner/bridge_generated.h ./flutter/ios/Runner/bridge_generated.h

setup_bridge_flutter
log "gerando generated_bridge.freezed.dart com Flutter $FLUTTER_BRIDGE_VERSION..."
(
  export PATH="$FLUTTER_BRIDGE_DIR/bin:$PATH"
  cd "$ROOT/flutter"
  flutter pub get
  flutter pub run build_runner build --delete-conflicting-outputs
)

log "bridge gerado com sucesso"
