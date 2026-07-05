#!/usr/bin/env bash
# Compila instalador Windows (.exe) com Inno Setup.
#
# Uso:
#   ./installers/build-installer.sh suporte
#   ./installers/build-installer.sh cliente
#
# Saída: build/bgdesk-suporte-win64.exe ou build/bgdesk-cliente-win64.exe
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"
if [[ "$MODE" != "suporte" && "$MODE" != "cliente" ]]; then
  echo "[installer] Uso: $0 suporte|cliente" >&2
  exit 1
fi

log() { echo "[installer] $*"; }
warn() { echo "[installer] AVISO: $*" >&2; }

find_iscc() {
  if [[ -n "${INNO_SETUP_DIR:-}" && -x "${INNO_SETUP_DIR}/ISCC.exe" ]]; then
    echo "${INNO_SETUP_DIR}/ISCC.exe"
    return 0
  fi
  local candidate
  for candidate in \
    "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
    "/c/Program Files/Inno Setup 6/ISCC.exe"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  if command -v ISCC.exe >/dev/null 2>&1; then
    command -v ISCC.exe
    return 0
  fi
  if command -v iscc >/dev/null 2>&1; then
    command -v iscc
    return 0
  fi
  return 1
}

ISS_FILE="$ROOT/installers/${MODE}.iss"
WIN_OUT_DIR="$ROOT/build/windows-${MODE}"
INSTALLER_BASE="bgdesk-${MODE}-win64"
INSTALLER_OUT="$ROOT/build/${INSTALLER_BASE}.exe"

if [[ ! -f "$ISS_FILE" ]]; then
  echo "[installer] ERRO: script não encontrado: $ISS_FILE" >&2
  exit 1
fi
if [[ ! -f "$WIN_OUT_DIR/bgdesk.exe" ]]; then
  echo "[installer] ERRO: build não encontrado: $WIN_OUT_DIR/bgdesk.exe" >&2
  echo "[installer] Rode ./build.sh primeiro." >&2
  exit 1
fi
if [[ ! -f "$ROOT/config/certs/ca.crt" ]]; then
  echo "[installer] ERRO: certificado ausente: config/certs/ca.crt" >&2
  exit 1
fi

ISCC=""
if ! ISCC="$(find_iscc)"; then
  warn "Inno Setup (ISCC) não encontrado."
  warn "Instale em https://jrsoftware.org/isinfo.php"
  warn "Ou defina INNO_SETUP_DIR apontando para a pasta do Inno Setup 6."
  warn "Instalador não gerado; artefatos em build/windows-${MODE}/"
  exit 0
fi

mkdir -p "$ROOT/build"
log "compilando $INSTALLER_BASE.exe ..."
"$ISCC" "$ISS_FILE"

if [[ ! -f "$INSTALLER_OUT" ]]; then
  echo "[installer] ERRO: saída esperada não encontrada: $INSTALLER_OUT" >&2
  exit 1
fi

bash "$ROOT/scripts/sign-pe.sh" "$INSTALLER_OUT"

log "instalador: $INSTALLER_OUT"
ls -lh "$INSTALLER_OUT"
