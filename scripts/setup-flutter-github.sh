#!/usr/bin/env bash
# Flutter SDK a partir de commit fixo do GitHub (flutter/flutter, branch master).
# Uso exclusivo: build manual macOS via ./build.sh (CI usa Flutter stable 3.24.5).
#
# Uso:
#   source scripts/setup-flutter-github.sh
#   # ou
#   ./scripts/setup-flutter-github.sh
#
# Variáveis:
#   FLUTTER_GITHUB_DIR     diretório do clone (padrão: ~/dev/flutter-github)
#   FLUTTER_REPO           repositório git (padrão: github.com/flutter/flutter)
#   FLUTTER_GITHUB_COMMIT  sobrescreve o commit em scripts/flutter-github-commit
#   FLUTTER_SKIP_VERIFY    se "1", não aborta em verify_flutter_github (não recomendado)
#   FLUTTER_UPDATE         se "1", fetch + checkout do commit fixo (./build.sh --flutter)

set -euo pipefail

FLUTTER_GITHUB_DIR="${FLUTTER_GITHUB_DIR:-$HOME/dev/flutter-github}"
FLUTTER_REPO="${FLUTTER_REPO:-https://github.com/flutter/flutter.git}"

log() { echo "[flutter-github] $*"; }
die() { log "ERRO: $*"; exit 1; }

read_flutter_github_commit() {
  local pin_file line
  if [[ -n "${FLUTTER_GITHUB_COMMIT:-}" ]]; then
    echo "$FLUTTER_GITHUB_COMMIT"
    return 0
  fi
  pin_file="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/flutter-github-commit"
  [[ -f "$pin_file" ]] || die "arquivo de pin não encontrado: $pin_file"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line//[[:space:]]/}"
    [[ -z "$line" ]] && continue
    echo "$line"
    return 0
  done < "$pin_file"
  die "nenhum commit definido em $pin_file"
}

FLUTTER_GITHUB_COMMIT="$(read_flutter_github_commit)"
export FLUTTER_GITHUB_COMMIT

# Git hooks do engine usam vpython3 (depot_tools); não são necessários para build do app.
flutter_git() {
  git -C "$FLUTTER_GITHUB_DIR" -c core.hooksPath=/dev/null "$@"
}

FLUTTER_UPDATE="${FLUTTER_UPDATE:-1}"

ensure_flutter_github_clone() {
  if [[ ! -d "$FLUTTER_GITHUB_DIR/.git" ]]; then
    log "clonando $FLUTTER_REPO em $FLUTTER_GITHUB_DIR"
    mkdir -p "$(dirname "$FLUTTER_GITHUB_DIR")"
    git clone "$FLUTTER_REPO" "$FLUTTER_GITHUB_DIR"
  fi
}

checkout_flutter_github_commit() {
  local current

  ensure_flutter_github_clone

  if [[ "$FLUTTER_UPDATE" == "1" ]]; then
    log "sincronizando clone com commit fixo ${FLUTTER_GITHUB_COMMIT:0:12}..."
    flutter_git fetch origin "$FLUTTER_GITHUB_COMMIT" --depth=1 2>/dev/null \
      || flutter_git fetch origin --tags --prune
  else
    [[ -d "$FLUTTER_GITHUB_DIR/.git" ]] || \
      die "clone Flutter não encontrado em $FLUTTER_GITHUB_DIR. Execute: ./build.sh mac --flutter"
    log "usando Flutter local em $FLUTTER_GITHUB_DIR (commit ${FLUTTER_GITHUB_COMMIT:0:12}; use --flutter para re-sincronizar)"
  fi

  current="$(flutter_git rev-parse HEAD 2>/dev/null || true)"
  if [[ "$current" != "$FLUTTER_GITHUB_COMMIT" ]]; then
    log "checkout ${FLUTTER_GITHUB_COMMIT:0:12} (atual: ${current:0:12})"
    if ! flutter_git checkout --force "$FLUTTER_GITHUB_COMMIT" 2>/dev/null; then
      [[ "$FLUTTER_UPDATE" == "1" ]] || die "commit ${FLUTTER_GITHUB_COMMIT:0:12} indisponível localmente. Rode: ./build.sh mac --flutter"
      flutter_git fetch origin "$FLUTTER_GITHUB_COMMIT" --depth=1 \
        || flutter_git fetch origin --tags --prune
      flutter_git checkout --force "$FLUTTER_GITHUB_COMMIT"
    fi
  fi

  current="$(flutter_git rev-parse HEAD)"
  [[ "$current" == "$FLUTTER_GITHUB_COMMIT" ]] || \
    die "checkout falhou: HEAD=${current:0:12}, esperado=${FLUTTER_GITHUB_COMMIT:0:12}"
}

checkout_flutter_github_commit

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

# Patch macOS occlusion-resume (flutter#155977, d70a0d3) — idempotente após checkout.
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
  local flutter_bin expected current
  expected="$FLUTTER_GITHUB_DIR/bin/flutter"
  flutter_bin="$(command -v flutter || true)"

  if [[ ! -x "$expected" ]]; then
    die "Flutter não encontrado em $expected"
  fi

  if [[ "$flutter_bin" != "$expected" ]]; then
    die "flutter no PATH não é o do GitHub.
  esperado: $expected
  encontrado: ${flutter_bin:-<nenhum>}
  Remova outras instalações do PATH ou use apenas ./build.sh"
  fi

  current="$(flutter_git rev-parse HEAD)"
  if [[ "$current" != "$FLUTTER_GITHUB_COMMIT" ]]; then
    die "Flutter não está no commit fixo:
  esperado: $FLUTTER_GITHUB_COMMIT
  atual:    $current"
  fi

  local version_line
  version_line="$(flutter --version 2>/dev/null | head -1 || true)"

  if ! flutter --version 2>&1 | grep -q "channel master"; then
    die "Flutter não está no channel master:
$(flutter --version 2>&1 | head -3)"
  fi

  if ! flutter --version 2>&1 | grep -q "github.com/flutter/flutter"; then
    die "Flutter não parece ser o clone oficial do GitHub"
  fi

  log "OK — $version_line"
  log "     commit: $FLUTTER_GITHUB_COMMIT"
  log "     dir: $FLUTTER_GITHUB_DIR"
}

if [[ "${FLUTTER_SKIP_VERIFY:-}" != "1" ]]; then
  verify_flutter_github
fi

log "FLUTTER_ROOT=$FLUTTER_ROOT"
log "FLUTTER_GITHUB_COMMIT=$FLUTTER_GITHUB_COMMIT"
log "use: export PATH=\"$FLUTTER_GITHUB_DIR/bin:\$PATH\""
