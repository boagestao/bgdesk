#!/usr/bin/env bash
# Nomenclatura de pastas de artefatos em build/ (source, não execute diretamente).
#
# Exemplos:
#   build/linux-aarch64-cliente/
#   build/macOS-aarch64-suporte/
#   build/windows-x86_64-suporte/          (instalador .exe)
#   build/windows-x86_64-suporte/extracted/ (app compilado)

bgdesk_build_mode() {
  if [[ "${BGDESK_CLIENTE:-0}" == "1" ]]; then
    echo cliente
  else
    echo suporte
  fi
}

# Uso: bgdesk_build_out_dir <plataforma> [arch]
# plataforma: linux | macOS | windows | android
bgdesk_build_out_dir() {
  local platform="$1"
  local arch="${2:-${BUILD_PATH:-$(uname -m)}}"
  case "$arch" in
    arm64) arch=aarch64 ;;
  esac
  local mode
  mode="$(bgdesk_build_mode)"
  echo "build/${platform}-${arch}-${mode}"
}

bgdesk_prepare_build_out_dir() {
  local out_dir="$1"
  rm -rf "$out_dir"
  mkdir -p "$out_dir"
}

# Uso: bgdesk_windows_app_dir [arch]
# Retorna build/windows-<arch>-<modo>/extracted (binários do app Windows).
bgdesk_windows_app_dir() {
  local arch="${1:-x86_64}"
  echo "$(bgdesk_build_out_dir windows "$arch")/extracted"
}
