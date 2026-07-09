#!/usr/bin/env bash
# Flutter SDK stable 3.44.6 para builds macOS locais (./build.sh).
#
# Uso:
#   source scripts/setup-flutter-macos.sh
#   # ou
#   ./scripts/setup-flutter-macos.sh
#
# Variáveis:
#   FLUTTER_MACOS_DIR      diretório do SDK (padrão: ~/dev/flutter-3.44.6)
#   FLUTTER_MACOS_VERSION  versão (padrão: 3.44.6)
#   FLUTTER_UPDATE         se "1", remove e rebaixa o SDK (--flutter no build.sh)
#   FLUTTER_SKIP_VERIFY    se "1", não aborta em verify_flutter_macos

set -euo pipefail

FLUTTER_MACOS_VERSION="${FLUTTER_MACOS_VERSION:-3.44.6}"
FLUTTER_MACOS_DIR="${FLUTTER_MACOS_DIR:-$HOME/dev/flutter-${FLUTTER_MACOS_VERSION}}"
FLUTTER_MACOS_DIR="${FLUTTER_MACOS_DIR/#\~/$HOME}"
FLUTTER_UPDATE="${FLUTTER_UPDATE:-0}"

log() { echo "[flutter-macos] $*"; }
die() { log "ERRO: $*"; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "setup-flutter-macos.sh é apenas para macOS"

FLUTTER_VERSION_FILE="$FLUTTER_MACOS_DIR/.bgdesk-flutter-version"
FLUTTER_PRECACHE_FILE="$FLUTTER_MACOS_DIR/.bgdesk-precache-macos"

flutter_is_installed() {
  [[ -f "$FLUTTER_MACOS_DIR/bin/flutter" ]] || return 1
  [[ -f "$FLUTTER_VERSION_FILE" ]] || return 1
  [[ "$(<"$FLUTTER_VERSION_FILE")" == "$FLUTTER_MACOS_VERSION" ]] || return 1
  "$FLUTTER_MACOS_DIR/bin/flutter" --version 2>/dev/null \
    | grep -qF "Flutter ${FLUTTER_MACOS_VERSION}"
}

reuse_flutter_if_ready() {
  if [[ "${BGDESK_FLUTTER_READY:-}" == "1" ]] && flutter_is_installed; then
    export FLUTTER_ROOT="$FLUTTER_MACOS_DIR"
    export PATH="$FLUTTER_MACOS_DIR/bin:$PATH"
    log "reutilizando Flutter já configurado em $FLUTTER_MACOS_DIR"
    return 0
  fi
  if [[ -n "${FLUTTER_ROOT:-}" && "$FLUTTER_ROOT" == "$FLUTTER_MACOS_DIR" ]] \
    && flutter_is_installed; then
    export PATH="$FLUTTER_MACOS_DIR/bin:$PATH"
    log "reutilizando Flutter em $FLUTTER_MACOS_DIR"
    export BGDESK_FLUTTER_READY=1
    return 0
  fi
  return 1
}

remove_flutter_install() {
  if [[ -e "$FLUTTER_MACOS_DIR" ]]; then
    log "removendo instalação existente em $FLUTTER_MACOS_DIR..."
    rm -rf "$FLUTTER_MACOS_DIR"
  fi
}

download_flutter() {
  local arch archive url tmp_dir tmp_zip extract_root extracted expected_size actual_size
  arch="$(uname -m)"
  if [[ "$arch" == "arm64" ]]; then
    archive="flutter_macos_arm64_${FLUTTER_MACOS_VERSION}-stable.zip"
  else
    archive="flutter_macos_${FLUTTER_MACOS_VERSION}-stable.zip"
  fi
  url="https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/${archive}"
  tmp_dir="$(mktemp -d)"
  tmp_zip="$tmp_dir/$archive"
  extract_root="$tmp_dir/extract"

  expected_size="$(
    curl -fsI "$url" | awk 'tolower($1) == "content-length:" { print $2; exit }' | tr -d '\r'
  )"

  log "baixando Flutter ${FLUTTER_MACOS_VERSION} ($arch)..."
  if ! curl -fL --retry 3 --retry-delay 2 "$url" -o "$tmp_zip"; then
    rm -rf "$tmp_dir"
    die "falha ao baixar $url"
  fi

  actual_size="$(wc -c <"$tmp_zip" | tr -d ' ')"
  if [[ -n "$expected_size" && "$actual_size" != "$expected_size" ]]; then
    rm -rf "$tmp_dir"
    die "download incompleto ($actual_size bytes, esperado $expected_size). Tente novamente."
  fi

  if ! unzip -t "$tmp_zip" >/dev/null 2>&1; then
    rm -rf "$tmp_dir"
    die "arquivo baixado está corrompido. Tente novamente com: ./build.sh mac --flutter"
  fi

  log "extraindo Flutter ${FLUTTER_MACOS_VERSION}..."
  mkdir -p "$extract_root"
  unzip -q "$tmp_zip" -d "$extract_root"
  extracted="$extract_root/flutter"
  [[ -f "$extracted/bin/flutter" ]] || {
    rm -rf "$tmp_dir"
    die "pacote Flutter inválido (bin/flutter ausente após extração)"
  }

  remove_flutter_install
  mkdir -p "$(dirname "$FLUTTER_MACOS_DIR")"
  mv "$extracted" "$FLUTTER_MACOS_DIR"
  echo "$FLUTTER_MACOS_VERSION" > "$FLUTTER_VERSION_FILE"
  rm -f "$FLUTTER_PRECACHE_FILE"
  rm -rf "$tmp_dir"
  log "Flutter ${FLUTTER_MACOS_VERSION} instalado em $FLUTTER_MACOS_DIR"
  export BGDESK_FLUTTER_READY=1
  export FLUTTER_UPDATE=0
}

if reuse_flutter_if_ready; then
  :
elif [[ "$FLUTTER_UPDATE" == "1" ]]; then
  remove_flutter_install
  download_flutter
elif flutter_is_installed; then
  log "usando Flutter existente em $FLUTTER_MACOS_DIR (use --flutter para reinstalar)"
  export BGDESK_FLUTTER_READY=1
  export FLUTTER_UPDATE=0
elif [[ -e "$FLUTTER_MACOS_DIR" ]]; then
  log "instalação incompleta ou inválida em $FLUTTER_MACOS_DIR — reinstalando..."
  remove_flutter_install
  download_flutter
else
  log "Flutter ${FLUTTER_MACOS_VERSION} não encontrado — baixando..."
  download_flutter
fi

export FLUTTER_ROOT="$FLUTTER_MACOS_DIR"
export PATH="$FLUTTER_MACOS_DIR/bin:$PATH"
unset FLUTTER_ENGINE FLUTTER_LOCAL_ENGINE FLUTTER_LOCAL_ENGINE_HOST FLUTTER_ENGINE_PATCH_APPLIED

if [[ "$FLUTTER_UPDATE" == "1" || ! -f "$FLUTTER_PRECACHE_FILE" ]]; then
  log "configurando Flutter (precache macOS)..."
  flutter config --no-analytics --no-enable-web 2>/dev/null || flutter config --no-analytics
  flutter precache --macos --no-android --no-ios --no-web 2>/dev/null || flutter precache --macos
  touch "$FLUTTER_PRECACHE_FILE"
fi

export FLUTTER_MACOS_REV="$("$FLUTTER_MACOS_DIR/bin/flutter" --version 2>/dev/null | sed -n '2p' | awk '{print $2}' || true)"
export FLUTTER_MACOS_VERSION="$FLUTTER_MACOS_VERSION"

verify_flutter_macos() {
  local flutter_bin expected version_out
  expected="$FLUTTER_MACOS_DIR/bin/flutter"
  flutter_bin="$(command -v flutter || true)"

  [[ -x "$expected" ]] || die "Flutter não encontrado em $expected"

  if [[ "$flutter_bin" != "$expected" ]]; then
    die "flutter no PATH não é o SDK macOS esperado.
  esperado: $expected
  encontrado: ${flutter_bin:-<nenhum>}
  Remova outras instalações do PATH ou use apenas ./build.sh"
  fi

  version_out="$(flutter --version 2>&1 || true)"
  if ! grep -q "channel stable" <<< "$version_out"; then
    die "Flutter não está no channel stable:
$(flutter --version 2>&1 | head -3)"
  fi

  if ! grep -qF "Flutter ${FLUTTER_MACOS_VERSION}" <<< "$version_out"; then
    die "Flutter instalado não é a versão ${FLUTTER_MACOS_VERSION}:
$(flutter --version 2>&1 | head -3)
Use: ./build.sh mac --flutter"
  fi

  log "OK — $(flutter --version 2>/dev/null | head -1)"
  log "     rev: ${FLUTTER_MACOS_REV:-?} ($FLUTTER_MACOS_DIR)"
}

if [[ "${FLUTTER_SKIP_VERIFY:-}" != "1" ]]; then
  verify_flutter_macos
fi

log "FLUTTER_ROOT=$FLUTTER_ROOT"
