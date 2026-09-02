#!/usr/bin/env bash
# Verifica se um BGDesk.app foi compilado com o Flutter stable pinado.
set -euo pipefail

APP="${1:-}"

if [[ -z "$APP" ]]; then
  if [[ -d "build/BGDesk.app" ]]; then
    APP="build/BGDesk.app"
  elif [[ -d "/Applications/BGDesk.app" ]]; then
    APP="/Applications/BGDesk.app"
  else
    echo "Uso: $0 [caminho/para/BGDesk.app]"
    exit 1
  fi
fi

STAMP="$APP/Contents/Resources/flutter-build-stamp.txt"
BUILD_STAMP="build/flutter-build-stamp.txt"

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
  echo "Este app NÃO foi gerado pelo pipeline atual (./build.sh com Flutter stable)."
  exit 1
fi

PIN_FILE="$(cd "$(dirname "$0")" && pwd)/flutter-stable-version"
PIN_VERSION=""
if [[ -f "$PIN_FILE" ]]; then
  PIN_VERSION="$(grep -v '^[[:space:]]*#' "$PIN_FILE" | grep -v '^[[:space:]]*$' | head -1 | tr -d '[:space:]')"
fi

if grep -q "channel stable" "$STAMP_FILE"; then
  if [[ -n "$PIN_VERSION" ]] && ! grep -qF "$PIN_VERSION" "$STAMP_FILE"; then
    echo "AVISO: stamp não corresponde ao Flutter stable em scripts/flutter-stable-version ($PIN_VERSION)."
  fi
  echo "OK — app compilado com Flutter stable (engine pré-compilado)."
  exit 0
fi

if grep -q "github.com/flutter/flutter" "$STAMP_FILE" && \
   grep -Eq 'channel (master|\[user-branch\])' "$STAMP_FILE"; then
  echo "AVISO: este app foi gerado com Flutter master/GitHub (pipeline antigo)."
  echo "O build macOS atual usa Flutter stable (scripts/flutter-stable-version)."
  exit 1
fi

echo "ERRO: stamp não indica Flutter stable."
exit 1
