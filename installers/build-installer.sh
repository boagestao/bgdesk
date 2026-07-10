#!/usr/bin/env bash
# Compila instalador Windows (.exe) com Inno Setup.
#
# Uso:
#   ./installers/build-installer.sh suporte
#   ./installers/build-installer.sh cliente
#
# Entrada: build/windows-x86_64-*/extracted/ (app compilado)
# Saída:   build/windows-x86_64-suporte/bgdesk-suporte-win64.exe
#          build/windows-x86_64-cliente/bgdesk-cliente-win64.exe
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/build-out-dir.sh
source "$ROOT/scripts/build-out-dir.sh"

MODE="${1:-}"
if [[ "$MODE" != "suporte" && "$MODE" != "cliente" ]]; then
  echo "[installer] Uso: $0 suporte|cliente" >&2
  exit 1
fi

if [[ "$MODE" == "cliente" ]]; then
  export BGDESK_CLIENTE=1
else
  export BGDESK_CLIENTE=0
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
WIN_OUT_DIR="$ROOT/$(bgdesk_build_out_dir windows x86_64)"
WIN_APP_DIR="$ROOT/$(bgdesk_windows_app_dir x86_64)"
INSTALLER_BASE="bgdesk-${MODE}-win64"
INSTALLER_OUT="$WIN_OUT_DIR/${INSTALLER_BASE}.exe"

if [[ ! -f "$ISS_FILE" ]]; then
  echo "[installer] ERRO: script não encontrado: $ISS_FILE" >&2
  exit 1
fi
if [[ ! -f "$WIN_APP_DIR/bgdesk.exe" ]]; then
  echo "[installer] ERRO: build não encontrado: $WIN_APP_DIR/bgdesk.exe" >&2
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
  warn "Instalador não gerado; artefatos em $(bgdesk_build_out_dir windows x86_64)/"
  exit 0
fi

mkdir -p "$WIN_OUT_DIR"
log "compilando $INSTALLER_BASE.exe ..."
"$ISCC" "$ISS_FILE"

if [[ ! -f "$INSTALLER_OUT" ]]; then
  echo "[installer] ERRO: saída esperada não encontrada: $INSTALLER_OUT" >&2
  exit 1
fi

bash "$ROOT/scripts/sign-pe.sh" "$INSTALLER_OUT"

log "instalador: $INSTALLER_OUT"
ls -lh "$INSTALLER_OUT"
