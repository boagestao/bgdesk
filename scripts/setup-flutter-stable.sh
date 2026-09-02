#!/usr/bin/env bash
# Flutter SDK estável oficial (artefatos pré-compilados). Sem engine local.
#
# Uso:
#   source scripts/setup-flutter-stable.sh
#   ./scripts/setup-flutter-stable.sh
#
# Variáveis:
#   FLUTTER_STABLE_DIR      diretório do SDK (padrão: <repo>/.tools/flutter-stable)
#   FLUTTER_STABLE_VERSION  sobrescreve scripts/flutter-stable-version
#   FLUTTER_UPDATE          se "1", reinstala o SDK da versão pinada

set -euo pipefail

_BGDESK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_STABLE_DIR="${FLUTTER_STABLE_DIR:-$_BGDESK_ROOT/.tools/flutter-stable}"

log() { echo "[flutter-stable] $*"; }
die() { log "ERRO: $*"; exit 1; }

read_flutter_stable_version() {
  local pin_file line
  if [[ -n "${FLUTTER_STABLE_VERSION:-}" ]]; then
    echo "$FLUTTER_STABLE_VERSION"
    return 0
  fi
  pin_file="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/flutter-stable-version"
  [[ -f "$pin_file" ]] || die "arquivo de pin não encontrado: $pin_file"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line//[[:space:]]/}"
    [[ -z "$line" ]] && continue
    echo "$line"
    return 0
  done < "$pin_file"
  die "nenhuma versão definida em $pin_file"
}

FLUTTER_STABLE_VERSION="$(read_flutter_stable_version)"
export FLUTTER_STABLE_VERSION

flutter_stable_archive_name() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os" in
    Darwin)
      if [[ "$arch" == "arm64" || "$arch" == "aarch64" ]]; then
        echo "flutter_macos_arm64_${FLUTTER_STABLE_VERSION}-stable.zip"
      else
        echo "flutter_macos_${FLUTTER_STABLE_VERSION}-stable.zip"
      fi
      ;;
    Linux)
      echo "flutter_linux_${FLUTTER_STABLE_VERSION}-stable.tar.xz"
      ;;
    *)
      die "plataforma não suportada para Flutter stable: $os"
      ;;
  esac
}

flutter_stable_installed_ok() {
  local bin ver
  bin="$FLUTTER_STABLE_DIR/bin/flutter"
  [[ -x "$bin" ]] || return 1
  ver="$("$bin" --version 2>/dev/null | head -1 || true)"
  [[ "$ver" == *"$FLUTTER_STABLE_VERSION"* ]] || return 1
  [[ "$ver" == *"channel stable"* ]] || return 1
}

install_flutter_stable() {
  local archive url tmp parent extracted
  archive="$(flutter_stable_archive_name)"
  case "$(uname -s)" in
    Darwin) url="https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/${archive}" ;;
    Linux)  url="https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/${archive}" ;;
  esac
  parent="$(dirname "$FLUTTER_STABLE_DIR")"
  mkdir -p "$parent" "$_BGDESK_ROOT/.tools/tmp"
  tmp="$_BGDESK_ROOT/.tools/tmp/$archive"
  log "baixando Flutter $FLUTTER_STABLE_VERSION ($archive)..."
  curl -fL "$url" -o "$tmp"
  log "instalando em $FLUTTER_STABLE_DIR ..."
  rm -rf "$FLUTTER_STABLE_DIR"
  extracted="$parent/flutter"
  rm -rf "$extracted"
  case "$archive" in
    *.zip) unzip -q "$tmp" -d "$parent" ;;
    *)     tar xf "$tmp" -C "$parent" ;;
  esac
  [[ -d "$extracted" ]] || die "arquivo Flutter não extraiu para $extracted"
  mv "$extracted" "$FLUTTER_STABLE_DIR"
  rm -f "$tmp"
}

ensure_flutter_stable() {
  FLUTTER_UPDATE="${FLUTTER_UPDATE:-0}"
  if [[ "$FLUTTER_UPDATE" == "1" ]] || ! flutter_stable_installed_ok; then
    if [[ -x "$FLUTTER_STABLE_DIR/bin/flutter" ]] && [[ "$FLUTTER_UPDATE" != "1" ]]; then
      log "Flutter em $FLUTTER_STABLE_DIR não é $FLUTTER_STABLE_VERSION stable — reinstalando..."
    fi
    install_flutter_stable
  else
    log "usando Flutter $FLUTTER_STABLE_VERSION em $FLUTTER_STABLE_DIR"
  fi
  [[ -x "$FLUTTER_STABLE_DIR/bin/flutter" ]] || die "Flutter não encontrado em $FLUTTER_STABLE_DIR"
}

ensure_flutter_stable

export FLUTTER_ROOT="$FLUTTER_STABLE_DIR"
export BGDESK_FLUTTER_STABLE=1
unset BGDESK_FLUTTER_GITHUB
unset FLUTTER_ENGINE FLUTTER_LOCAL_ENGINE FLUTTER_LOCAL_ENGINE_HOST
unset FLUTTER_ENGINE_PATCH_APPLIED

_clean_path="$FLUTTER_STABLE_DIR/bin"
IFS=':' read -r -a _path_parts <<< "${PATH:-}"
for _p in "${_path_parts[@]}"; do
  [[ -z "$_p" || "$_p" == *depot_tools* || "$_p" == "$FLUTTER_STABLE_DIR/bin" ]] && continue
  _clean_path+=":$_p"
done
export PATH="$_clean_path"

log "configurando Flutter..."
flutter config --no-analytics --no-enable-web 2>/dev/null || flutter config --no-analytics

OS="$(uname -s)"
case "$OS" in
  Darwin)  flutter precache --macos --no-android --no-ios --no-web 2>/dev/null || flutter precache --macos ;;
  Linux)   flutter precache --linux ;;
esac

verify_flutter_stable() {
  local flutter_bin expected version_out version_line
  expected="$FLUTTER_STABLE_DIR/bin/flutter"
  flutter_bin="$(command -v flutter || true)"

  [[ -x "$expected" ]] || die "Flutter não encontrado em $expected"
  if [[ "$flutter_bin" != "$expected" ]]; then
    die "flutter no PATH não é o SDK stable.
  esperado: $expected
  encontrado: ${flutter_bin:-<nenhum>}"
  fi

  version_out="$(flutter --version 2>&1 || true)"
  version_line="$(echo "$version_out" | head -1)"
  grep -q "$FLUTTER_STABLE_VERSION" <<< "$version_out" || \
    die "Flutter não é $FLUTTER_STABLE_VERSION:
$version_out"
  grep -q "channel stable" <<< "$version_out" || \
    die "Flutter não está no channel stable:
$version_out"

  log "OK — $version_line"
  log "     dir: $FLUTTER_STABLE_DIR"
}

if [[ "${FLUTTER_SKIP_VERIFY:-}" != "1" ]]; then
  verify_flutter_stable
fi

log "FLUTTER_ROOT=$FLUTTER_ROOT"
log "FLUTTER_STABLE_VERSION=$FLUTTER_STABLE_VERSION"
log "use: export PATH=\"$FLUTTER_STABLE_DIR/bin:\$PATH\""
