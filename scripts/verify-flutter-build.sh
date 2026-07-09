#!/usr/bin/env bash
# Verifica se um BGDesk.app foi compilado com Flutter stable 3.44.6 (build macOS local).
set -euo pipefail

APP="${1:-}"
FLUTTER_MACOS_VERSION="${FLUTTER_MACOS_VERSION:-3.44.6}"

if [[ -z "$APP" ]]; then
  shopt -s nullglob
  candidates=(build/macOS-*/BGDesk.app)
  if ((${#candidates[@]} > 0)); then
    APP="${candidates[0]}"
  elif [[ -d "build/BGDesk.app" ]]; then
    APP="build/BGDesk.app"
  elif [[ -d "/Applications/BGDesk.app" ]]; then
    APP="/Applications/BGDesk.app"
  else
    echo "Uso: $0 [caminho/para/BGDesk.app]"
    exit 1
  fi
fi

STAMP="$APP/Contents/Resources/flutter-build-stamp.txt"
BUILD_STAMP="$(dirname "$APP")/flutter-build-stamp.txt"

echo "App: $APP"
echo ""

STAMP_FILE=""
if [[ -f "$STAMP" ]]; then
  STAMP_FILE="$STAMP"
  echo "=== flutter-build-stamp.txt (dentro do app) ==="
  cat "$STAMP"
  echo ""
elif [[ -f "$BUILD_STAMP" ]]; then
  STAMP_FILE="$BUILD_STAMP"
  echo "=== flutter-build-stamp.txt (pasta build/) ==="
  cat "$BUILD_STAMP"
  echo ""
  echo "AVISO: o app não contém o stamp — provavelmente build antigo ou cópia manual."
else
  echo "ERRO: nenhum flutter-build-stamp.txt encontrado."
  echo "Este app NÃO foi gerado pelo pipeline atual (./build.sh com Flutter ${FLUTTER_MACOS_VERSION})."
  exit 1
fi

if ! grep -q "channel stable" "$STAMP_FILE"; then
  echo "ERRO: stamp não indica channel stable."
  exit 1
fi

if ! grep -qF "Flutter ${FLUTTER_MACOS_VERSION}" "$STAMP_FILE"; then
  echo "ERRO: stamp não indica Flutter ${FLUTTER_MACOS_VERSION}."
  exit 1
fi

echo "OK — app compilado com Flutter stable ${FLUTTER_MACOS_VERSION}."
