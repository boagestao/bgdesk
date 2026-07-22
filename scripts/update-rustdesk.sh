#!/usr/bin/env bash
# Atualização BGDesk ← RustDesk upstream
# Baseado em AUALIZACAO.md — integração semi-automática preservando branding BGDesk.
#
# Uso:
#   ./scripts/update-rustdesk.sh              # menu interativo
#   ./scripts/update-rustdesk.sh --phase 0    # fase específica
#   ./scripts/update-rustdesk.sh --all        # fases automatizáveis (0–7)
#   ./scripts/update-rustdesk.sh --dry-run --phase 2
#
# Variáveis de ambiente:
#   BGDESK_DIR      caminho do repo BGDesk (padrão: raiz do projeto)
#   RUSTDESK_DIR    caminho do RustDesk upstream (padrão: ~/dev/rustdesk)
#   RUSTDESK_TAG    tag upstream (padrão: 1.4.8)
#   TARGET_VERSION  versão alvo BGDesk (padrão: 1.4.8)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BGDESK_DIR="${BGDESK_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
RUSTDESK_DIR="${RUSTDESK_DIR:-$HOME/dev/rustdesk}"
RUSTDESK_TAG="${RUSTDESK_TAG:-1.4.8}"
TARGET_VERSION="${TARGET_VERSION:-1.4.8}"
UPDATE_BRANCH="update/rustdesk-${TARGET_VERSION}"
DRY_RUN=false
FORCE_COPY=false
PHASE=""
RUN_ALL=false

# Arquivos/diretórios BGDesk que NUNCA devem ser sobrescritos pelo upstream
PRESERVE_PATHS=(
  build.sh build-deb.sh build-bridge.sh sign.sh install-vcpkg.sh md5.py
  certs docker installers scripts .vscode
  res/setup.nsi res/mac-icon.icns
  src/custom_server.rs
  AUALIZACAO.md
)

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

log()  { echo "[update] $*"; }
warn() { echo "[update] ⚠️  $*" >&2; }
die()  { echo "[update] ❌ $*" >&2; exit 1; }

usage() {
  cat <<EOF
Atualização BGDesk ← RustDesk (ver AUALIZACAO.md)

Uso: $0 [opções]

Opções:
  --phase N       Executa apenas a fase N (0–10)
  --all           Executa fases automatizáveis 0–7 em sequência
  --dry-run       Mostra ações sem executar
  --force-copy    Copia arquivos modificados do upstream (com backup .bgdesk.bak)
  -h, --help      Esta ajuda

Fases:
  0  Preparação (branch, tag backup, verificar upstream)
  1  Submodule hbb_common (instruções + atualização opcional)
  2  Código Rust (src/) — copia novos arquivos, lista merges manuais
  3  Bibliotecas (libs/) — copia novos, lista merges manuais
  4  Flutter — copia novos arquivos, lista merges manuais
  5  Recursos (res/, flatpak/, appimage/) — preserva arquivos BGDesk
  6  CI/scripts — apenas relatório (scripts BGDesk preservados)
  7  Traduções — copia novos idiomas, verifica RustDesk em lang/
  8  Compilação (cargo + bridge + flutter)
  9  Testes (cargo test + flutter test)
  10 Finalização (verificação de branding + checklist)

Ordem recomendada (AUALIZACAO.md §9):
  0 → 1 → 2 → 3 → 8.1 → 4 → 8.3 → 5 → 6 → 7 → 8.4 → 9 → 10
EOF
}

run() {
  if $DRY_RUN; then
    echo "[dry-run] $*"
  else
    log "exec: $*"
    "$@"
  fi
}

is_preserved() {
  local rel="$1"
  for p in "${PRESERVE_PATHS[@]}"; do
    [[ "$rel" == "$p" || "$rel" == "$p/"* ]] && return 0
  done
  return 1
}

upstream_path() {
  local rel="$1"
  echo "$RUSTDESK_DIR/$rel"
}

bgdesk_path() {
  local rel="$1"
  echo "$BGDESK_DIR/$rel"
}

copy_new_file() {
  local rel="$1"
  if is_preserved "$rel"; then
    warn "preservado (não copiado): $rel"
    return 0
  fi
  local src dst
  src="$(upstream_path "$rel")"
  dst="$(bgdesk_path "$rel")"
  if [[ ! -e "$src" ]]; then
    warn "ausente no upstream: $rel"
    return 0
  fi
  if [[ -e "$dst" ]]; then
    if $FORCE_COPY; then
      run cp -a "$dst" "${dst}.bgdesk.bak"
      run cp -a "$src" "$dst"
      log "sobrescrito (backup .bgdesk.bak): $rel"
    else
      warn "já existe (merge manual): $rel"
    fi
  else
    run mkdir -p "$(dirname "$dst")"
    run cp -a "$src" "$dst"
    log "copiado (novo): $rel"
  fi
}

copy_new_dir() {
  local rel="$1"
  if is_preserved "$rel"; then
    warn "preservado (não copiado): $rel"
    return 0
  fi
  local src dst
  src="$(upstream_path "$rel")"
  dst="$(bgdesk_path "$rel")"
  if [[ ! -d "$src" ]]; then
    warn "diretório ausente no upstream: $rel"
    return 0
  fi
  if [[ -d "$dst" ]]; then
    if $FORCE_COPY; then
      run cp -a "$dst" "${dst}.bgdesk.bak"
      run rm -rf "$dst"
      run cp -a "$src" "$dst"
      log "diretório sobrescrito (backup .bgdesk.bak): $rel"
    else
      warn "diretório já existe (merge manual): $rel"
    fi
  else
    run mkdir -p "$(dirname "$dst")"
    run cp -a "$src" "$dst"
    log "copiado (novo diretório): $rel"
  fi
}

list_modified() {
  local dir="$1"
  local upstream="$RUSTDESK_DIR/$dir"
  local bgdesk="$BGDESK_DIR/$dir"
  [[ -d "$upstream" ]] || return 0
  find "$upstream" -type f | while read -r up_file; do
    local rel="${up_file#$upstream/}"
  rel="$dir/$rel"
    if is_preserved "$rel"; then
      continue
    fi
    local bg_file="$BGDESK_DIR/$rel"
    if [[ -f "$bg_file" ]] && ! diff -q "$up_file" "$bg_file" &>/dev/null; then
      echo "$rel"
    fi
  done
}

require_upstream() {
  [[ -d "$RUSTDESK_DIR" ]] || die "RustDesk upstream não encontrado em: $RUSTDESK_DIR"
  [[ -d "$BGDESK_DIR/.git" ]] || die "BGDesk não é um repositório git: $BGDESK_DIR"
}

checkout_upstream_tag() {
  if $DRY_RUN; then
    echo "[dry-run] git -C $RUSTDESK_DIR checkout $RUSTDESK_TAG"
    return 0
  fi
  local current
  current="$(git -C "$RUSTDESK_DIR" describe --tags --exact-match 2>/dev/null || git -C "$RUSTDESK_DIR" rev-parse --short HEAD)"
  if [[ "$current" == "$RUSTDESK_TAG" ]]; then
    log "upstream já em $RUSTDESK_TAG"
  else
    log "checkout upstream tag $RUSTDESK_TAG em $RUSTDESK_DIR"
    git -C "$RUSTDESK_DIR" fetch --tags origin 2>/dev/null || git -C "$RUSTDESK_DIR" fetch --tags 2>/dev/null || true
    git -C "$RUSTDESK_DIR" checkout "$RUSTDESK_TAG"
  fi
}

# ---------------------------------------------------------------------------
# Fases
# ---------------------------------------------------------------------------

phase0_prepare() {
  log "=== Fase 0 — Preparação ==="
  require_upstream

  if ! $DRY_RUN; then
    if [[ -n "$(git -C "$BGDESK_DIR" status --porcelain)" ]]; then
      die "working tree não está limpa. Commit ou stash antes de continuar."
    fi
  else
    warn "dry-run: pulando verificação de working tree limpa"
  fi

  if $DRY_RUN; then
    echo "[dry-run] git -C $BGDESK_DIR checkout -b $UPDATE_BRANCH"
    echo "[dry-run] git -C $BGDESK_DIR tag backup-pre-$TARGET_VERSION"
  else
    if git -C "$BGDESK_DIR" rev-parse --verify "$UPDATE_BRANCH" &>/dev/null; then
      log "branch $UPDATE_BRANCH já existe — fazendo checkout"
      git -C "$BGDESK_DIR" checkout "$UPDATE_BRANCH"
    else
      git -C "$BGDESK_DIR" checkout -b "$UPDATE_BRANCH"
    fi
    if ! git -C "$BGDESK_DIR" rev-parse --verify "backup-pre-$TARGET_VERSION" &>/dev/null; then
      git -C "$BGDESK_DIR" tag "backup-pre-$TARGET_VERSION"
      log "tag backup-pre-$TARGET_VERSION criada"
    else
      log "tag backup-pre-$TARGET_VERSION já existe"
    fi
  fi

  checkout_upstream_tag

  log "toolchain atual:"
  run rustc --version 2>/dev/null || warn "rustc não encontrado"
  run cargo --version 2>/dev/null || true
  run flutter --version 2>/dev/null | head -1 || warn "flutter não encontrado"
  log "Fase 0 concluída"
}

phase1_submodule() {
  log "=== Fase 1 — Submodule hbb_common ==="
  require_upstream

  local hbb_upstream_commit
  hbb_upstream_commit="$(git -C "$RUSTDESK_DIR" ls-tree HEAD libs/hbb_common | awk '{print $3}')"
  log "commit hbb_common no upstream $RUSTDESK_TAG: ${hbb_upstream_commit:-desconhecido}"

  cat <<EOF

Ação MANUAL necessária no fork bgdesk-config:
  1. Criar branch update/hbb_common-$TARGET_VERSION
  2. Merge/rebase de rustdesk/hbb_common (commit $hbb_upstream_commit)
  3. Reaplicar patches BGDesk:
     - APP_NAME = "BGDesk"
     - ORG = "br.com.boagestao"
     - RENDEZVOUS_SERVERS = ["bgdesk.boagestao.net"]
     - VER_TYPE → bgdesk-client / bgdesk-server
     - version check → https://bgdesk.boagestao.net/version/latest
     - platform/mod.rs → "BGDesk"
     - message.proto → scheme bgdesk://
  4. Commit + push do bgdesk-config
  5. Atualizar referência aqui com: HBB_COMMON_COMMIT=<hash> $0 --phase 1

EOF

  if [[ -n "${HBB_COMMON_COMMIT:-}" ]]; then
    log "atualizando submodule para $HBB_COMMON_COMMIT"
    if $DRY_RUN; then
      echo "[dry-run] git -C $BGDESK_DIR/libs/hbb_common fetch && checkout $HBB_COMMON_COMMIT"
      echo "[dry-run] git -C $BGDESK_DIR add libs/hbb_common"
    else
      git -C "$BGDESK_DIR/libs/hbb_common" fetch origin
      git -C "$BGDESK_DIR/libs/hbb_common" checkout "$HBB_COMMON_COMMIT"
      git -C "$BGDESK_DIR" add libs/hbb_common
      log "submodule atualizado e staged"
    fi
  else
    warn "defina HBB_COMMON_COMMIT=<hash> para atualizar automaticamente após o merge no bgdesk-config"
  fi
}

phase2_rust() {
  log "=== Fase 2 — Código Rust (src/) ==="
  require_upstream
  checkout_upstream_tag

  local new_files=(
    src/updater.rs
    src/kcp_stream.rs
    src/server/terminal_service.rs
    src/server/terminal_helper.rs
    src/server/login_failure_check.rs
    src/privacy_mode/macos.rs
    src/platform/privileges_scripts/update.scpt
    src/hbbs_http/downloader.rs
    src/lang/fi.rs
    src/lang/gu.rs
    src/lang/hi.rs
    src/lang/ml.rs
    src/lang/vi.rs
  )
  local new_dirs=(
    src/platform/windows
    src/whiteboard
    src/ipc
    tests
  )

  for f in "${new_files[@]}"; do copy_new_file "$f"; done
  for d in "${new_dirs[@]}"; do copy_new_dir "$d"; done

  # Remover vn.rs se upstream usa vi.rs
  if [[ -f "$(upstream_path src/lang/vi.rs)" ]] && [[ -f "$(bgdesk_path src/lang/vn.rs)" ]]; then
    if $DRY_RUN; then
      echo "[dry-run] rm $(bgdesk_path src/lang/vn.rs)  # upstream usa vi.rs"
    else
      warn "removendo src/lang/vn.rs (upstream usa vi.rs) — verifique src/lang.rs"
      rm -f "$(bgdesk_path src/lang/vn.rs)"
    fi
  fi

  # Arquivos de configuração — copiar com backup se --force-copy
  for f in Cargo.toml Cargo.lock build.rs vcpkg.json; do
    copy_new_file "$f"
  done

  log "arquivos modificados em src/ (merge manual recomendado):"
  list_modified "src" | head -80
  local count
  count="$(list_modified "src" | wc -l | tr -d ' ')"
  [[ "$count" -gt 80 ]] && warn "... e mais $((count - 80)) arquivos"

  warn "prioridade de merge: lib.rs, main.rs, core_main.rs, server/, client/, platform/, flutter_ffi.rs"
  warn "preservar: get_api_server() → bgdesk.boagestao.net, custom_server.rs, strings BGDesk"
  log "Fase 2 concluída"
}

phase3_libs() {
  log "=== Fase 3 — Bibliotecas (libs/) ==="
  require_upstream
  checkout_upstream_tag

  copy_new_dir "libs/libxdo-sys-stub"

  for lib in scrap clipboard enigo remote_printer portable virtual_display; do
    log "--- libs/$lib ---"
    list_modified "libs/$lib" | while read -r f; do
      if $FORCE_COPY; then
        copy_new_file "$f"
      else
        echo "  merge manual: $f"
      fi
    done
    # Copiar arquivos novos dentro de cada lib
    local lib_upstream="$RUSTDESK_DIR/libs/$lib"
    [[ -d "$lib_upstream" ]] || continue
    find "$lib_upstream" -type f | while read -r up_file; do
      local rel="libs/$lib/${up_file#$lib_upstream/}"
      [[ -f "$(bgdesk_path "$rel")" ]] || copy_new_file "$rel"
    done
  done

  warn "preservar referências BGDesk em libs/portable/main.rs e Cargo.toml"
  log "Fase 3 concluída"
}

phase4_flutter() {
  log "=== Fase 4 — Flutter ==="
  require_upstream
  checkout_upstream_tag

  local new_files=(
    flutter/lib/desktop/pages/terminal_page.dart
    flutter/lib/desktop/pages/terminal_tab_page.dart
    flutter/lib/desktop/screen/desktop_terminal_screen.dart
    flutter/lib/desktop/widgets/update_progress.dart
    flutter/lib/mobile/pages/terminal_page.dart
    flutter/lib/mobile/widgets/floating_mouse.dart
    flutter/lib/mobile/widgets/floating_mouse_widgets.dart
    flutter/lib/mobile/widgets/deploy_dialog.dart
    flutter/lib/mobile/widgets/custom_scale_widget.dart
    flutter/lib/models/terminal_model.dart
    flutter/lib/models/relative_mouse_model.dart
    flutter/lib/models/input_modifier_utils.dart
    flutter/lib/common/widgets/custom_scale_base.dart
    flutter/lib/utils/relative_mouse_accumulator.dart
    flutter/lib/utils/scale.dart
    flutter/assets/auth-microsoft.svg
    flutter/assets/display_switcher.svg
    flutter/assets/keyboard_mouse.svg
    flutter/pubspec.yaml
  )
  local new_dirs=(
    flutter/test
  )

  # Terminal pages — nomes podem variar; copiar qualquer terminal_*.dart novo
  find "$RUSTDESK_DIR/flutter/lib" -name 'terminal_*.dart' 2>/dev/null | while read -r f; do
    local rel="flutter/lib/${f#$RUSTDESK_DIR/flutter/lib/}"
    copy_new_file "$rel"
  done
  find "$RUSTDESK_DIR/flutter/lib" -name 'floating_mouse*.dart' 2>/dev/null | while read -r f; do
    local rel="flutter/lib/${f#$RUSTDESK_DIR/flutter/lib/}"
    copy_new_file "$rel"
  done

  for f in "${new_files[@]}"; do copy_new_file "$f"; done
  for d in "${new_dirs[@]}"; do copy_new_dir "$d"; done

  # Android/linux/windows novos
  for pattern in \
    "flutter/android/app/src/main/kotlin/**/MainApplication.kt" \
    "flutter/linux/bump_mouse*.cc" \
    "flutter/linux/bump_mouse*.h" \
    "flutter/linux/wayland_shortcuts_inhibit.*" \
    "flutter/windows/runner/win32_desktop.*"
  do
    for f in "$RUSTDESK_DIR"/$pattern; do
      [[ -e "$f" ]] || continue
      local rel="${f#$RUSTDESK_DIR/}"
      copy_new_file "$rel"
    done
  done

  log "arquivos Flutter modificados (merge manual — preservar branding):"
  list_modified "flutter/lib" | head -40

  warn "preservar: applicationId br.com.boagestao.bgdesksuporte, bundle ID br.com.boagestao.bgdesk"
  warn "preservar: desktop_setting_page.dart, settings_page.dart, common.dart, bridge.dart, home_page.dart"
  warn "após merge: executar fase 8.3 para regenerar bridge (./build-bridge.sh)"
  log "Fase 4 concluída"
}

phase5_resources() {
  log "=== Fase 5 — Recursos (res/, flatpak/, appimage/) ==="
  require_upstream
  checkout_upstream_tag

  for dir in res flatpak appimage; do
    [[ -d "$RUSTDESK_DIR/$dir" ]] || continue
    find "$RUSTDESK_DIR/$dir" -type f | while read -r up_file; do
      local rel="${up_file#$RUSTDESK_DIR/}"
      if is_preserved "$rel"; then
        continue
      fi
      copy_new_file "$rel"
    done
  done

  warn "revisar manualmente: DEBIAN/postinst, rpm specs, .desktop, .wxl — manter nomes BGDesk"
  log "Fase 5 concluída"
}

phase6_ci() {
  log "=== Fase 6 — CI/CD e scripts de build ==="
  log "Scripts BGDesk preservados (não copiados do upstream):"
  printf '  %s\n' "${PRESERVE_PATHS[@]}"

  warn "merge seletivo de .github/workflows/ — NÃO copiar diretório inteiro"
  warn "incorporar manualmente: wf-cliprdr-ci.yml, flutter-nightly.yml, patches Flutter 3.44"

  if [[ -d "$RUSTDESK_DIR/.github/workflows" ]]; then
    log "workflows presentes no upstream mas ausentes no BGDesk (candidatos a incorporar):"
    comm -23 \
      <(find "$RUSTDESK_DIR/.github/workflows" -name '*.yml' -exec basename {} \; | sort) \
      <(find "$BGDESK_DIR/.github/workflows" -name '*.yml' -exec basename {} \; 2>/dev/null | sort) \
      | sed 's/^/  /' || true
  fi

  copy_new_file "build.py"
  copy_new_file ".gitignore"
  log "Fase 6 concluída"
}

phase7_translations() {
  log "=== Fase 7 — Traduções ==="
  require_upstream
  checkout_upstream_tag

  for f in "$RUSTDESK_DIR"/src/lang/*.rs; do
    [[ -f "$f" ]] || continue
    local rel="src/lang/$(basename "$f")"
    copy_new_file "$rel"
  done
  copy_new_file "src/lang.rs"

  log "verificando 'RustDesk' em src/lang/:"
  if grep -rl 'RustDesk' "$BGDESK_DIR/src/lang/" 2>/dev/null; then
    warn "substituir 'RustDesk' por 'BGDesk' nos arquivos acima"
  else
    log "nenhuma ocorrência de RustDesk em src/lang/"
  fi
  log "Fase 7 concluída"
}

phase8_build() {
  log "=== Fase 8 — Compilação ==="
  cd "$BGDESK_DIR"

  local step="${BUILD_STEP:-all}"

  build_rust() {
    log "8.1 — cargo build --release --features flutter"
    run cargo build --release --features flutter
  }

  build_bridge() {
    log "8.3 — regenerar bridge Flutter-Rust"
    if [[ -x "$BGDESK_DIR/build-bridge.sh" ]]; then
      run "$BGDESK_DIR/build-bridge.sh"
    else
      die "build-bridge.sh não encontrado"
    fi
    run bash -c "cd '$BGDESK_DIR/flutter' && flutter pub get"
    run python3 "$BGDESK_DIR/build.py" --flutter
  }

  build_platform() {
    log "8.4 — build por plataforma"
    if [[ -x "$BGDESK_DIR/build.sh" ]]; then
      run "$BGDESK_DIR/build.sh"
    fi
    if [[ -x "$BGDESK_DIR/build-deb.sh" ]]; then
      run "$BGDESK_DIR/build-deb.sh"
    fi
  }

  case "$step" in
    rust)    build_rust ;;
    bridge)  build_bridge ;;
    platform) build_platform ;;
    all)
      build_rust
      build_bridge
      ;;
    *)
      die "BUILD_STEP inválido: $step (use: rust, bridge, platform, all)"
      ;;
  esac
  log "Fase 8 concluída"
}

phase9_tests() {
  log "=== Fase 9 — Testes ==="
  cd "$BGDESK_DIR"

  log "9.1 — cargo test"
  run cargo test

  log "9.2 — flutter test"
  run bash -c "cd '$BGDESK_DIR/flutter' && flutter test"

  warn "testes funcionais manuais: P2P via bgdesk.boagestao.net, custom_server, UI branding, empacotamento"
  log "Fase 9 concluída"
}

phase10_finalize() {
  log "=== Fase 10 — Finalização ==="

  log "10.1 — verificar versão alvo $TARGET_VERSION em:"
  for f in Cargo.toml flutter/pubspec.yaml libs/portable/Cargo.toml; do
    if [[ -f "$BGDESK_DIR/$f" ]]; then
      grep -E 'version|Version' "$BGDESK_DIR/$f" | head -2 | sed "s/^/  $f: /" || true
    fi
  done
  warn "atualize versões manualmente se necessário (ou use res/bump.sh)"

  log "10.2 — verificação de branding"
  if $DRY_RUN; then
    echo "[dry-run] $SCRIPT_DIR/verify-branding.sh"
  else
    "$SCRIPT_DIR/verify-branding.sh" "$BGDESK_DIR" || warn "branding precisa revisão"
  fi

  cat <<EOF

10.3–10.5 — ações manuais finais:
  git add -A
  git commit -m "Update to RustDesk $TARGET_VERSION base, preserve BGDesk branding"
  git tag v$TARGET_VERSION
  git push -u origin $UPDATE_BRANCH
  git push origin v$TARGET_VERSION

EOF
  log "Fase 10 concluída"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)     PHASE="$2"; shift 2 ;;
    --all)       RUN_ALL=true; shift ;;
    --dry-run)   DRY_RUN=true; shift ;;
    --force-copy) FORCE_COPY=true; shift ;;
    -h|--help)   usage; exit 0 ;;
    *)           die "opção desconhecida: $1 (use --help)" ;;
  esac
done

run_phase() {
  case "$1" in
    0)  phase0_prepare ;;
    1)  phase1_submodule ;;
    2)  phase2_rust ;;
    3)  phase3_libs ;;
    4)  phase4_flutter ;;
    5)  phase5_resources ;;
    6)  phase6_ci ;;
    7)  phase7_translations ;;
    8)  phase8_build ;;
    9)  phase9_tests ;;
    10) phase10_finalize ;;
    *)  die "fase inválida: $1 (use 0–10)" ;;
  esac
}

if $RUN_ALL; then
  for p in 0 1 2 3 4 5 6 7; do
    run_phase "$p"
    echo
  done
  log "fases 0–7 concluídas. Próximo: BUILD_STEP=rust $0 --phase 8"
  exit 0
fi

if [[ -n "$PHASE" ]]; then
  run_phase "$PHASE"
  exit 0
fi

# Menu interativo
echo "Atualização BGDesk ← RustDesk $RUSTDESK_TAG"
echo "BGDesk:   $BGDESK_DIR"
echo "Upstream: $RUSTDESK_DIR"
echo
usage
echo
read -r -p "Fase a executar (0-10, ou 'all' para 0-7): " choice
if [[ "$choice" == "all" ]]; then
  RUN_ALL=true
  for p in 0 1 2 3 4 5 6 7; do run_phase "$p"; echo; done
else
  run_phase "$choice"
fi
