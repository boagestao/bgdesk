#!/usr/bin/env bash
# Gera generated_bridge.dart + generated_bridge.freezed.dart + bridge Rust.
#
# macOS: Flutter stable 3.44.6 (setup-flutter-macos.sh).
# Outras plataformas: Flutter stable 3.29 apenas para build_runner/freezed quando
# o Flutter principal não suporta build_runner.

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

FLUTTER_BRIDGE_DIR="${FLUTTER_BRIDGE_DIR:-$HOME/dev/flutter-bridge-tools}"
FLUTTER_BRIDGE_VERSION="${FLUTTER_BRIDGE_VERSION:-3.29.0}"

log() { echo "[bridge] $*"; }

setup_bridge_flutter() {
  if [[ ! -x "$FLUTTER_BRIDGE_DIR/bin/flutter" ]]; then
    log "baixando Flutter $FLUTTER_BRIDGE_VERSION para build_runner (apenas freezed)..."
    mkdir -p "$(dirname "$FLUTTER_BRIDGE_DIR")"
    local os arch archive url
    os="$(uname -s)"
    arch="$(uname -m)"
    if [[ "$os" == "Darwin" ]]; then
      if [[ "$arch" == "arm64" ]]; then
        archive="flutter_macos_arm64_${FLUTTER_BRIDGE_VERSION}-stable.zip"
      else
        archive="flutter_macos_${FLUTTER_BRIDGE_VERSION}-stable.zip"
      fi
      url="https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/${archive}"
      curl -L "$url" -o "/tmp/${archive}"
      rm -rf "$FLUTTER_BRIDGE_DIR"
      unzip -q "/tmp/${archive}" -d "$(dirname "$FLUTTER_BRIDGE_DIR")"
      mv "$(dirname "$FLUTTER_BRIDGE_DIR")/flutter" "$FLUTTER_BRIDGE_DIR"
    else
      archive="flutter_linux_${FLUTTER_BRIDGE_VERSION}-stable.tar.xz"
      url="https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/${archive}"
      curl -L "$url" -o "/tmp/${archive}"
      rm -rf "$FLUTTER_BRIDGE_DIR"
      tar xf "/tmp/${archive}" -C "$(dirname "$FLUTTER_BRIDGE_DIR")"
      mv "$(dirname "$FLUTTER_BRIDGE_DIR")/flutter" "$FLUTTER_BRIDGE_DIR"
    fi
    "$FLUTTER_BRIDGE_DIR/bin/flutter" config --no-analytics
  fi
}

if [[ "$(uname -s)" == "Darwin" ]]; then
  if [[ -n "${FLUTTER_ROOT:-}" && -x "${FLUTTER_ROOT}/bin/flutter" ]]; then
    export PATH="${FLUTTER_ROOT}/bin:$PATH"
    FLUTTER_BRIDGE_DIR="$FLUTTER_ROOT"
    log "usando Flutter já configurado: $FLUTTER_ROOT"
  else
    # shellcheck source=/dev/null
    source "$ROOT/scripts/setup-flutter-macos.sh"
    FLUTTER_BRIDGE_DIR="$FLUTTER_ROOT"
  fi
else
  if ! command -v flutter >/dev/null 2>&1; then
    echo "[bridge] ERRO: flutter não encontrado no PATH"
    exit 1
  fi
fi

if ! command -v flutter_rust_bridge_codegen &>/dev/null; then
  cargo install flutter_rust_bridge_codegen --version 1.80.1 --features "uuid" --locked
fi

log "resolvendo dependências Dart (flutter pub get)..."
(
  export PATH="${FLUTTER_BRIDGE_DIR}/bin:$PATH"
  cd "$ROOT/flutter"
  flutter pub get
)

log "gerando bridge (Rust + Dart, sem build_runner)..."
flutter_rust_bridge_codegen --no-build-runner \
  --rust-input ./src/flutter_ffi.rs \
  --dart-output ./flutter/lib/generated_bridge.dart \
  --c-output ./flutter/macos/Runner/bridge_generated.h

cp ./flutter/macos/Runner/bridge_generated.h ./flutter/ios/Runner/bridge_generated.h

if [[ "$(uname -s)" != "Darwin" ]]; then
  setup_bridge_flutter
fi
log "gerando generated_bridge.freezed.dart..."
(
  export PATH="$FLUTTER_BRIDGE_DIR/bin:$PATH"
  cd "$ROOT/flutter"
  flutter pub run build_runner build --delete-conflicting-outputs
)

log "bridge gerado com sucesso"
