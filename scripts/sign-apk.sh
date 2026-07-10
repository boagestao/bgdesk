#!/usr/bin/env bash
# Assina APKs com a keystore do submodule config (credenciais em android-key.properties).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROPS="$ROOT/config/android-key.properties"
KS_DEFAULT="$ROOT/config/android-key.jks"

if [[ ! -f "$PROPS" ]]; then
  echo "ERRO: $PROPS não encontrado (submodule config)."
  exit 1
fi

store_password=""
key_password=""
key_alias=""
store_file="android-key.jks"
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  key="${line%%=*}"
  value="${line#*=}"
  case "$key" in
    storePassword) store_password="$value" ;;
    keyPassword) key_password="$value" ;;
    keyAlias) key_alias="$value" ;;
    storeFile) store_file="$value" ;;
  esac
done < "$PROPS"

if [[ "$store_file" != /* ]]; then
  store_file="$ROOT/config/$store_file"
fi
[[ -f "$store_file" ]] || store_file="$KS_DEFAULT"

APKSIGNER="$(find "${ANDROID_HOME:-$HOME/Library/Android/sdk}/build-tools" -name apksigner -type f 2>/dev/null | sort | tail -1)"
if [[ -z "$APKSIGNER" || ! -x "$APKSIGNER" ]]; then
  echo "ERRO: apksigner não encontrado (Android SDK build-tools)."
  exit 1
fi

sign_one() {
  local apk="$1"
  [[ -f "$apk" ]] || { echo "APK não encontrado: $apk"; exit 1; }
  "$APKSIGNER" sign \
    --ks "$store_file" \
    --key-pass "pass:${key_password}" \
    --ks-key-alias "$key_alias" \
    --ks-pass "pass:${store_password}" \
    "$apk"
  echo "Assinado: $apk"
}

sign_one "${1:-$ROOT/build/android-universal-suporte/bgdesk-suporte-universal.apk}"
if [[ -n "${2:-}" ]]; then
  sign_one "$2"
elif [[ -f "$ROOT/build/android-universal-cliente/bgdesk-cliente-universal.apk" ]]; then
  sign_one "$ROOT/build/android-universal-cliente/bgdesk-cliente-universal.apk"
fi
