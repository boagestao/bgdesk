#!/usr/bin/env bash
# Verifica se um BGDesk.app foi compilado com Flutter master do GitHub.
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
  echo "Este app NÃO foi gerado pelo pipeline atual (./build.sh com Flutter GitHub master)."
  exit 1
fi

if ! grep -q "channel master" "$STAMP_FILE"; then
  echo "ERRO: stamp não indica channel master."
  exit 1
fi

if ! grep -q "github.com/flutter/flutter" "$STAMP_FILE"; then
  echo "ERRO: stamp não indica repositório GitHub oficial."
  exit 1
fi

PIN_FILE="$(cd "$(dirname "$0")" && pwd)/flutter-github-commit"
if [[ -f "$PIN_FILE" ]]; then
  PIN_COMMIT="$(grep -v '^[[:space:]]*#' "$PIN_FILE" | grep -v '^[[:space:]]*$' | head -1 | tr -d '[:space:]')"
  if [[ -n "$PIN_COMMIT" ]] && ! grep -qF "$PIN_COMMIT" "$STAMP_FILE"; then
    echo "AVISO: stamp não corresponde ao commit fixo em scripts/flutter-github-commit ($PIN_COMMIT)."
  fi
fi

echo "OK — app compilado com Flutter master do GitHub (commit fixo)."
