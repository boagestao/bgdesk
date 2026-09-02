#!/usr/bin/env bash
# Gera generated_bridge.dart + generated_bridge.freezed.dart + bridge Rust.
#
# Codegen: Flutter stable pinado (3.47.x).
# freezed/build_runner: Flutter 3.44.4 — o analyzer do freezed 2.5 não lê Dart 3.13.

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

FLUTTER_BRIDGE_DIR="${FLUTTER_BRIDGE_DIR:-$ROOT/.tools/flutter-bridge-tools}"
FLUTTER_BRIDGE_VERSION="${FLUTTER_BRIDGE_VERSION:-3.44.4}"
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
  local bin ver archive url tmp parent extracted os arch
  bin="$FLUTTER_BRIDGE_DIR/bin/flutter"
  if [[ -x "$bin" ]]; then
    ver="$("$bin" --version 2>/dev/null | head -1 || true)"
    if [[ "$ver" == *"$FLUTTER_BRIDGE_VERSION"* ]]; then
      return 0
    fi
    log "Flutter em $FLUTTER_BRIDGE_DIR não é $FLUTTER_BRIDGE_VERSION — reinstalando..."
  else
    log "baixando Flutter $FLUTTER_BRIDGE_VERSION para build_runner (freezed)..."
  fi
  os="$(uname -s)"
  arch="$(uname -m)"
  parent="$(dirname "$FLUTTER_BRIDGE_DIR")"
  mkdir -p "$parent" "$ROOT/.tools/tmp"
  if [[ "$os" == "Darwin" ]]; then
    if [[ "$arch" == "arm64" || "$arch" == "aarch64" ]]; then
      archive="flutter_macos_arm64_${FLUTTER_BRIDGE_VERSION}-stable.zip"
    else
      archive="flutter_macos_${FLUTTER_BRIDGE_VERSION}-stable.zip"
    fi
    url="https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/${archive}"
  else
    archive="flutter_linux_${FLUTTER_BRIDGE_VERSION}-stable.tar.xz"
    url="https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/${archive}"
  fi
  tmp="$ROOT/.tools/tmp/$archive"
  curl -fL "$url" -o "$tmp"
  rm -rf "$FLUTTER_BRIDGE_DIR"
  extracted="$parent/flutter"
  rm -rf "$extracted"
  case "$archive" in
    *.zip) unzip -q "$tmp" -d "$parent" ;;
    *)     tar xf "$tmp" -C "$parent" ;;
  esac
  [[ -d "$extracted" ]] || { log "ERRO: extração falhou em $extracted"; exit 1; }
  mv "$extracted" "$FLUTTER_BRIDGE_DIR"
  rm -f "$tmp"
  "$FLUTTER_BRIDGE_DIR/bin/flutter" config --no-analytics
}

# shellcheck source=/dev/null
source "$ROOT/scripts/setup-flutter-stable.sh"

if ! command -v flutter_rust_bridge_codegen &>/dev/null; then
  cargo install flutter_rust_bridge_codegen --version 1.80.1 --features "uuid" --locked
fi

log "flutter pub get (necessário para pubspec.lock)..."
(
  cd "$ROOT/flutter"
  flutter pub get
)

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
