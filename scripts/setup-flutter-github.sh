#!/usr/bin/env bash
# DEPRECATED: builds macOS usam scripts/setup-flutter-macos.sh (Flutter stable 3.44.6).
# Mantido apenas para referência / engine local manual.
#
# Flutter SDK a partir do branch master do GitHub (não usa release estável).
# Uso exclusivo: build manual macOS via ./build.sh (CI usa Flutter stable 3.24.5).
#
# Uso:
#   source scripts/setup-flutter-github.sh
#   # ou
#   ./scripts/setup-flutter-github.sh
#
# Variáveis:
#   FLUTTER_GITHUB_DIR  diretório do clone (padrão: ~/dev/flutter-github)
#   FLUTTER_REPO        repositório git (padrão: github.com/flutter/flutter)
#   FLUTTER_BRANCH      branch (padrão: master)
#   FLUTTER_SKIP_VERIFY se "1", não aborta em verify_flutter_github (não recomendado)
#   FLUTTER_UPDATE      se "1", atualiza clone e precache (./build.sh --flutter); padrão "1"

set -euo pipefail

FLUTTER_GITHUB_DIR="${FLUTTER_GITHUB_DIR:-$HOME/dev/flutter-github}"
FLUTTER_REPO="${FLUTTER_REPO:-https://github.com/flutter/flutter.git}"
FLUTTER_BRANCH="${FLUTTER_BRANCH:-master}"

log() { echo "[flutter-github] $*"; }
die() { log "ERRO: $*"; exit 1; }

# Git hooks do engine usam vpython3 (depot_tools); não são necessários para build do app.
flutter_git() {
  git -C "$FLUTTER_GITHUB_DIR" -c core.hooksPath=/dev/null "$@"
}

FLUTTER_UPDATE="${FLUTTER_UPDATE:-1}"

if [[ "$FLUTTER_UPDATE" == "1" ]]; then
  if [[ ! -d "$FLUTTER_GITHUB_DIR/.git" ]]; then
    log "clonando $FLUTTER_REPO (branch $FLUTTER_BRANCH) em $FLUTTER_GITHUB_DIR"
    mkdir -p "$(dirname "$FLUTTER_GITHUB_DIR")"
    git clone --branch "$FLUTTER_BRANCH" --single-branch "$FLUTTER_REPO" "$FLUTTER_GITHUB_DIR"
  else
    log "atualizando clone em $FLUTTER_GITHUB_DIR"
    flutter_git fetch origin "$FLUTTER_BRANCH"
    flutter_git checkout "$FLUTTER_BRANCH"
    flutter_git pull --ff-only origin "$FLUTTER_BRANCH" || true
  fi
else
  [[ -d "$FLUTTER_GITHUB_DIR/.git" ]] || \
    die "clone Flutter não encontrado em $FLUTTER_GITHUB_DIR. Execute: ./build.sh --flutter"
  log "usando Flutter local em $FLUTTER_GITHUB_DIR (sem atualizar; use --flutter para atualizar)"
fi

export FLUTTER_ROOT="$FLUTTER_GITHUB_DIR"
# Flutter primeiro; depot_tools no PATH global quebra git hooks (vpython3).
_clean_path="$FLUTTER_GITHUB_DIR/bin"
IFS=':' read -r -a _path_parts <<< "${PATH:-}"
for _p in "${_path_parts[@]}"; do
  [[ -z "$_p" || "$_p" == *depot_tools* || "$_p" == "$FLUTTER_GITHUB_DIR/bin" ]] && continue
  _clean_path+=":$_p"
done
export PATH="$_clean_path"
export FLUTTER_GITHUB_REV="$(flutter_git rev-parse HEAD)"

# flutter precache/config não aceitam FLUTTER_ENGINE/FLUTTER_LOCAL_ENGINE no ambiente.
unset FLUTTER_ENGINE FLUTTER_LOCAL_ENGINE FLUTTER_LOCAL_ENGINE_HOST

# Patch macOS occlusion-resume (flutter#155977, d70a0d3) — idempotente após git pull.
BGDESK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$BGDESK_ROOT/scripts/apply-flutter-engine-patch.sh"

if [[ "$FLUTTER_UPDATE" == "1" ]]; then
  log "configurando Flutter..."
  flutter config --no-analytics --no-enable-web 2>/dev/null || flutter config --no-analytics

  OS="$(uname -s)"
  case "$OS" in
    Darwin)  flutter precache --macos --no-android --no-ios --no-web 2>/dev/null || flutter precache --macos ;;
    Linux)   flutter precache --linux ;;
    MINGW*|MSYS*|CYGWIN*) flutter precache --windows ;;
  esac
fi

verify_flutter_github() {
  local flutter_bin expected
  expected="$FLUTTER_GITHUB_DIR/bin/flutter"
  flutter_bin="$(command -v flutter || true)"

  if [[ ! -x "$expected" ]]; then
    die "Flutter não encontrado em $expected"
  fi

  if [[ "$flutter_bin" != "$expected" ]]; then
    die "flutter no PATH não é o do GitHub master.
  esperado: $expected
  encontrado: ${flutter_bin:-<nenhum>}
  Remova outras instalações do PATH ou use apenas ./build.sh"
  fi

  local version_line channel_line
  version_line="$(flutter --version 2>/dev/null | head -1 || true)"
  channel_line="$(flutter --version 2>/dev/null | sed -n '1p' || true)"

  if ! flutter --version 2>&1 | grep -q "channel master"; then
    die "Flutter não está no channel master:
$(flutter --version 2>&1 | head -3)"
  fi

  if ! flutter --version 2>&1 | grep -q "github.com/flutter/flutter"; then
    die "Flutter não parece ser o clone oficial do GitHub"
  fi

  log "OK — $version_line"
  log "     rev: ${FLUTTER_GITHUB_REV:0:12} ($FLUTTER_GITHUB_DIR)"
}

if [[ "${FLUTTER_SKIP_VERIFY:-}" != "1" ]]; then
  verify_flutter_github
fi

log "FLUTTER_ROOT=$FLUTTER_ROOT"
log "use: export PATH=\"$FLUTTER_GITHUB_DIR/bin:\$PATH\""
