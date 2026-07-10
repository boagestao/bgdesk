#!/usr/bin/env bash
# Prepara uma máquina Windows limpa para compilar com ./build.sh (somente Windows).
#
# Uso (Git Bash):
#   ./scripts/setup-windows-build.sh
#   ./scripts/setup-windows-build.sh --help
#
# Depois, abra um novo terminal Git Bash e rode:
#   ./build.sh
#
# Instala/configura: Git, Python 3, Rust, Visual Studio Build Tools (C++),
# vcpkg + dependências do projeto, Flutter 3.44.x e PATH no ~/.bashrc.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Alinhado com build.sh / CI (.github/workflows/flutter-build.yml)
VCPKG_COMMIT_ID="${VCPKG_COMMIT_ID:-120deac3062162151622ca4860575a33844ba10b}"
FLUTTER_VERSION="${FLUTTER_VERSION:-3.44.4}"
VCPKG_TRIPLET="${VCPKG_TRIPLET:-x64-windows-static}"
VCPKG_ROOT="${VCPKG_ROOT:-$HOME/.bin/vcpkg}"
FLUTTER_DIR="${FLUTTER_DIR:-$HOME/flutter}"
TEMP_DIR="${TEMP_DIR:-$ROOT/.temp}"
BASHRC_MARKER="# bgdesk-setup-windows-build.sh"

SKIP_VCPKG_DEPS=0
SKIP_VS=0
REINSTALL_FLUTTER=0
SHOW_HELP=0

usage() {
  cat <<'EOF'
Uso: ./scripts/setup-windows-build.sh [opções]

Prepara o ambiente de build Windows para ./build.sh.

Opções:
  --skip-vcpkg-deps     Não roda install-vcpkg.sh (vcpkg já instalado).
  --skip-vs             Não tenta instalar Visual Studio Build Tools.
  --reinstall-flutter   Baixa Flutter de novo mesmo se já existir.
  --help, -h            Mostra esta ajuda.

Requisitos:
  - Windows 10/11, Git Bash
  - winget (App Installer) para instalar pacotes base
  - Conexão com a internet (downloads grandes: Flutter ~1.8 GB, vcpkg ~30+ min)

Após concluir, abra um NOVO terminal Git Bash e execute ./build.sh
EOF
}

for arg in "$@"; do
  case "$arg" in
    --skip-vcpkg-deps) SKIP_VCPKG_DEPS=1 ;;
    --skip-vs) SKIP_VS=1 ;;
    --reinstall-flutter) REINSTALL_FLUTTER=1 ;;
    --help|-h|help) SHOW_HELP=1 ;;
    *) echo "[setup] opção desconhecida: $arg" >&2; usage; exit 1 ;;
  esac
done

if [[ "$SHOW_HELP" == "1" ]]; then
  usage
  exit 0
fi

if [[ "$(uname -s)" != MINGW* ]] && [[ "$(uname -s)" != MSYS* ]] && [[ "$(uname -s)" != CYGWIN* ]]; then
  echo "[setup] ERRO: este script é somente para Windows (Git Bash / MSYS)." >&2
  exit 1
fi

log() { echo "[setup] $*"; }
die() { echo "[setup] ERRO: $*" >&2; exit 1; }

win_home_path() {
  if [[ -n "${USERPROFILE:-}" ]]; then
    echo "${USERPROFILE//\\//}"
  else
    echo "${HOME//\\//}"
  fi
}

to_windows_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  else
    local p="${1//\//\\}"
    if [[ "$p" =~ ^\\ ]]; then
      echo "$p"
    elif [[ "$p" =~ ^[A-Za-z]: ]]; then
      echo "$p"
    else
      echo "$p"
    fi
  fi
}

ensure_winget() {
  if command -v winget >/dev/null 2>&1; then
    return 0
  fi
  die "winget não encontrado. Instale 'App Installer' pela Microsoft Store."
}

winget_install() {
  local id="$1"
  shift
  if winget list --id "$id" 2>/dev/null | grep -q "$id"; then
    log "já instalado (winget): $id"
    return 0
  fi
  log "instalando via winget: $id ..."
  winget install --id "$id" --accept-package-agreements --accept-source-agreements "$@" || true
}

ensure_git() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi
  ensure_winget
  winget_install Git.Git
  command -v git >/dev/null 2>&1 || die "git não encontrado após instalação"
}

ensure_python() {
  if command -v python3 >/dev/null 2>&1 && python3 -c "import sys; sys.exit(0)" 2>/dev/null; then
    return 0
  fi
  if command -v python >/dev/null 2>&1 && python -c "import sys; sys.exit(0)" 2>/dev/null; then
    return 0
  fi
  ensure_winget
  winget_install Python.Python.3.12
  local win_home
  win_home="$(win_home_path)"
  export PATH="$win_home/AppData/Local/Programs/Python/Python312:$win_home/AppData/Local/Programs/Python/Python312/Scripts:$PATH"
  command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 \
    || die "python não encontrado após instalação (reabra o terminal ou adicione ao PATH)"
}

ensure_cargo_path() {
  local win_home
  win_home="$(win_home_path)"
  if command -v cargo >/dev/null 2>&1; then
    return 0
  fi
  if [[ -f "$win_home/.cargo/env" ]]; then
    # shellcheck source=/dev/null
    . "$win_home/.cargo/env"
  fi
  if command -v cargo >/dev/null 2>&1; then
    return 0
  fi
  if [[ -x "$win_home/.cargo/bin/cargo.exe" ]]; then
    export PATH="$win_home/.cargo/bin:$PATH"
    return 0
  fi
  return 1
}

install_rust() {
  if ensure_cargo_path; then
    log "Rust: $(cargo --version 2>/dev/null || true)"
    return 0
  fi

  ensure_winget
  log "instalando Rust (rustup)..."
  winget_install Rustlang.Rustup

  if ! ensure_cargo_path; then
    mkdir -p "$TEMP_DIR"
    local installer="$TEMP_DIR/rustup-init.exe"
    curl --proto '=https' --tlsv1.2 -sSf https://win.rustup.rs/x86_64 -o "$installer"
    cmd //c "$(to_windows_path "$installer") -y --default-toolchain stable"
  fi

  ensure_cargo_path || die "cargo não encontrado após instalar Rust"
  log "Rust: $(cargo --version)"
}

vs_has_cpp_tools() {
  local vswhere="/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
  [[ -x "$vswhere" ]] || return 1
  "$vswhere" -latest \
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 \
    -property installationPath 2>/dev/null | grep -q .
}

install_visual_studio_build_tools() {
  if [[ "$SKIP_VS" == "1" ]]; then
    log "pulando instalação do Visual Studio (--skip-vs)"
    return 0
  fi
  if vs_has_cpp_tools; then
    log "Visual Studio Build Tools (C++) já presente"
    return 0
  fi
  ensure_winget
  log "instalando Visual Studio 2022 Build Tools (C++) — pode demorar..."
  winget install --id Microsoft.VisualStudio.2022.BuildTools \
    --accept-package-agreements --accept-source-agreements \
    --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended" \
    || true
  if ! vs_has_cpp_tools; then
    die "Visual Studio Build Tools (C++) não encontrado. Instale manualmente o workload 'Desktop development with C++'."
  fi
}

install_vcpkg() {
  mkdir -p "$(dirname "$VCPKG_ROOT")"
  if [[ ! -d "$VCPKG_ROOT/.git" ]]; then
    log "clonando vcpkg em $VCPKG_ROOT ..."
    git clone https://github.com/microsoft/vcpkg.git "$VCPKG_ROOT"
  fi
  local current_commit
  current_commit="$(git -C "$VCPKG_ROOT" rev-parse HEAD 2>/dev/null || echo "")"
  if [[ "$current_commit" != "$VCPKG_COMMIT_ID" ]]; then
    log "vcpkg: checkout $VCPKG_COMMIT_ID"
    git -C "$VCPKG_ROOT" fetch origin --tags
    git -C "$VCPKG_ROOT" checkout "$VCPKG_COMMIT_ID"
  fi
  if [[ ! -x "$VCPKG_ROOT/vcpkg.exe" ]]; then
    log "bootstrap vcpkg..."
    cmd //c "\"$(to_windows_path "$VCPKG_ROOT")\\bootstrap-vcpkg.bat\" -disableMetrics"
  fi
  [[ -x "$VCPKG_ROOT/vcpkg.exe" ]] || die "vcpkg.exe não encontrado em $VCPKG_ROOT"
}

install_vcpkg_dependencies() {
  if [[ "$SKIP_VCPKG_DEPS" == "1" ]]; then
    log "pulando dependências vcpkg (--skip-vcpkg-deps)"
    return 0
  fi
  local ffmpeg_hdr="$VCPKG_ROOT/installed/$VCPKG_TRIPLET/include/libavutil/attributes.h"
  if [[ -f "$ffmpeg_hdr" ]]; then
    log "dependências vcpkg já instaladas ($VCPKG_TRIPLET)"
    return 0
  fi
  log "instalando dependências vcpkg ($VCPKG_TRIPLET) — pode demorar 30+ min..."
  export VCPKG_ROOT VCPKG_TRIPLET
  export VCPKG_DEFAULT_HOST_TRIPLET="$VCPKG_TRIPLET"
  bash "$ROOT/install-vcpkg.sh"
}

flutter_installed_version_ok() {
  [[ -x "$FLUTTER_DIR/bin/flutter.bat" ]] || return 1
  local ver
  ver="$("$FLUTTER_DIR/bin/flutter.bat" --version 2>/dev/null | head -1 || true)"
  [[ "$ver" == *"$FLUTTER_VERSION"* ]]
}

install_flutter() {
  if [[ "$REINSTALL_FLUTTER" == "1" ]] || ! flutter_installed_version_ok; then
    if [[ -d "$FLUTTER_DIR" ]]; then
      log "removendo Flutter antigo em $FLUTTER_DIR ..."
      cmd //c "rmdir /s /q \"$(to_windows_path "$FLUTTER_DIR")\"" 2>/dev/null || rm -rf "$FLUTTER_DIR" || true
    fi
    mkdir -p "$TEMP_DIR"
    local archive="flutter_windows_${FLUTTER_VERSION}-stable.zip"
    local url="https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/${archive}"
    local zip="$TEMP_DIR/$archive"
    log "baixando Flutter $FLUTTER_VERSION ..."
    curl -L -o "$zip" "$url"
    mkdir -p "$(dirname "$FLUTTER_DIR")"
    unzip -q "$zip" -d "$(dirname "$FLUTTER_DIR")"
    if [[ -d "$(dirname "$FLUTTER_DIR")/flutter" && "$FLUTTER_DIR" != "$(dirname "$FLUTTER_DIR")/flutter" ]]; then
      mv "$(dirname "$FLUTTER_DIR")/flutter" "$FLUTTER_DIR"
    fi
  else
    log "Flutter $FLUTTER_VERSION já presente em $FLUTTER_DIR"
  fi
  [[ -x "$FLUTTER_DIR/bin/flutter.bat" ]] || die "Flutter não encontrado em $FLUTTER_DIR"
  export PATH="$FLUTTER_DIR/bin:$PATH"
  export FLUTTER_ROOT="$FLUTTER_DIR"
  "$FLUTTER_DIR/bin/flutter.bat" config --no-analytics
  log "flutter precache --windows ..."
  "$FLUTTER_DIR/bin/flutter.bat" precache --windows
  log "Flutter: $("$FLUTTER_DIR/bin/flutter.bat" --version 2>/dev/null | head -1)"
}

configure_shell_path() {
  local bashrc="${HOME}/.bashrc"
  touch "$bashrc"
  if grep -qF "$BASHRC_MARKER" "$bashrc" 2>/dev/null; then
    log "PATH já configurado em $bashrc"
  else
    log "adicionando PATH ao $bashrc ..."
    cat >>"$bashrc" <<EOF

$BASHRC_MARKER
_bgd_win_home="\${USERPROFILE//\\\\//}"
export PATH="\$_bgd_win_home/.cargo/bin:$FLUTTER_DIR/bin:\$_bgd_win_home/AppData/Local/Programs/Python/Python312:\$_bgd_win_home/AppData/Local/Programs/Python/Python312/Scripts:\$PATH"
[[ -f "\$_bgd_win_home/.cargo/env" ]] && . "\$_bgd_win_home/.cargo/env"
unset _bgd_win_home
EOF
  fi
  write_windows_build_env_local
}

write_windows_build_env_local() {
  local env_file="$ROOT/scripts/windows-build-env.local.sh"
  local win_home llvm_root llvm_bin
  win_home="$(win_home_path)"
  llvm_root="$VCPKG_ROOT/downloads/tools/clang/clang-15.0.6"
  llvm_bin="$llvm_root/bin"
  log "gravando $env_file ..."
  cat >"$env_file" <<EOF
# Gerado por scripts/setup-windows-build.sh
export FLUTTER_ROOT="$FLUTTER_DIR"
export VCPKG_ROOT="$VCPKG_ROOT"
export VCPKG_TRIPLET="$VCPKG_TRIPLET"
export VCPKG_DEFAULT_HOST_TRIPLET="$VCPKG_TRIPLET"
export LIBCLANG_PATH="$llvm_bin"
export BGDESK_LLVM_ROOT="$llvm_root"
export PATH="$win_home/.cargo/bin:$FLUTTER_DIR/bin:\$PATH"
EOF
}

verify_libclang() {
  local llvm_root="$VCPKG_ROOT/downloads/tools/clang/clang-15.0.6"
  local llvm_bin="$llvm_root/bin"
  if [[ -f "$llvm_bin/libclang.dll" ]]; then
    log "libclang: $llvm_bin"
    export LIBCLANG_PATH="$llvm_bin"
    export BGDESK_LLVM_ROOT="$llvm_root"
    return 0
  fi
  die "libclang não encontrado em $llvm_bin (rode sem --skip-vcpkg-deps)"
}

verify_setup() {
  local win_home
  win_home="$(win_home_path)"
  export PATH="$win_home/.cargo/bin:$FLUTTER_DIR/bin:$PATH"
  [[ -f "$win_home/.cargo/env" ]] && . "$win_home/.cargo/env"

  command -v cargo >/dev/null 2>&1 || die "cargo ausente"
  command -v git >/dev/null 2>&1 || die "git ausente"
  command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || die "python ausente"
  [[ -x "$VCPKG_ROOT/vcpkg.exe" ]] || die "vcpkg ausente em $VCPKG_ROOT"
  [[ -x "$FLUTTER_DIR/bin/flutter.bat" ]] || die "flutter ausente em $FLUTTER_DIR"
  verify_libclang

  log "verificação final: flutter doctor (resumo)"
  "$FLUTTER_DIR/bin/flutter.bat" doctor -v 2>&1 | head -30 || true
}

main() {
  log "preparando ambiente Windows para ./build.sh"
  log "repositório: $ROOT"
  mkdir -p "$TEMP_DIR"

  ensure_git
  ensure_python
  install_rust
  install_visual_studio_build_tools
  install_vcpkg
  install_vcpkg_dependencies
  install_flutter
  configure_shell_path
  verify_setup

  echo ""
  echo "=== Setup Windows concluído ==="
  echo "Abra um NOVO terminal Git Bash e rode:"
  echo "  cd \"$ROOT\""
  echo "  ./build.sh"
  echo ""
  echo "Variáveis usadas pelo build.sh:"
  echo "  VCPKG_ROOT=$VCPKG_ROOT"
  echo "  FLUTTER_ROOT=$FLUTTER_DIR"
}

main "$@"
