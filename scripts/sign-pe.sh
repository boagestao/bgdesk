#!/usr/bin/env bash
# Assina PE (exe/dll) com osslsigncode, se possível.
# Uso: ./scripts/sign-pe.sh <arquivo>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-}"

if [[ -z "$TARGET" ]]; then
  echo "[sign] Uso: $0 <arquivo>" >&2
  exit 1
fi
if [[ ! -f "$TARGET" ]]; then
  echo "[sign] ERRO: arquivo não encontrado: $TARGET" >&2
  exit 1
fi

if ! command -v osslsigncode >/dev/null 2>&1; then
  echo "[sign] AVISO: osslsigncode ausente — $(basename "$TARGET") não assinado"
  exit 0
fi
if [[ ! -f "$ROOT/config/certs/sign.crt" || ! -f "$ROOT/config/certs/sign.key" ]]; then
  echo "[sign] AVISO: config/certs/sign.crt ou config/certs/sign.key ausentes — $(basename "$TARGET") não assinado"
  exit 0
fi

echo "[sign] assinando $(basename "$TARGET") ..."
if ! bash "$ROOT/sign.sh" "$TARGET"; then
  if [[ -f "${TARGET}_unsigned" ]]; then
    mv -f "${TARGET}_unsigned" "$TARGET"
  fi
  echo "[sign] AVISO: falha ao assinar $(basename "$TARGET") — build continua"
fi
