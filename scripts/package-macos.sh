#!/usr/bin/env bash
# Final signing, notarization and DMG validation, after all bundle mutations.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
local_build=0
check_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) local_build=1; shift ;;
    --check) check_only=1; shift ;;
    --help|-h)
      echo "Usage: $0 [--local] [--check | app.app output.dmg]"
      echo "See docs/macos-signing.md for Developer ID and Keychain setup."
      exit 0 ;;
    --*) echo "Unknown option: $1" >&2; exit 1 ;;
    *) break ;;
  esac
done

fail() { echo "[macOS] ERRO: $*" >&2; exit 1; }
[[ "$(uname -s)" == "Darwin" ]] || fail "Execute no macOS."
stage="${BGDESK_PACKAGE_STAGE:-full}"
case "$stage" in
  full|package|notarize|staple) expected_args=2 ;;
  validate) expected_args=1 ;;
  *) fail "Etapa desconhecida: $stage" ;;
esac
if [[ "$check_only" == "1" ]]; then
  [[ $# == 0 ]] || fail "--check não aceita caminhos."
elif [[ $# != "$expected_args" ]]; then
  fail "Uso: $0 [--local] app.app output.dmg"
fi

tmp_keychain=""
tmp_keychain_dir=""
work_dir=""
mounted=0
original_keychains=()
keychain_search_changed=0

cleanup() {
  if [[ "$mounted" == "1" ]]; then
    if ! hdiutil detach "$mount_point" -quiet; then
      echo "[macOS] Não foi possível desmontar $mount_point; temporários preservados." >&2
    else
      mounted=0
    fi
  fi
  if [[ "$mounted" == "0" && -n "$work_dir" ]]; then
    rm -rf "$work_dir"
  fi
  if [[ -n "$tmp_keychain" ]]; then
    if [[ "$keychain_search_changed" == "1" ]]; then
      security list-keychains -d user -s ${original_keychains[@]+"${original_keychains[@]}"} >/dev/null 2>&1 || \
        echo "[macOS] Não foi possível restaurar a lista de Keychains." >&2
      keychain_search_changed=0
    fi
    security delete-keychain "$tmp_keychain" >/dev/null 2>&1 || true
    tmp_keychain=""
  fi
  if [[ -n "$tmp_keychain_dir" ]]; then
    rm -rf "$tmp_keychain_dir"
    tmp_keychain_dir=""
  fi
}
trap cleanup EXIT

# Fill only variables that are not already set. Values are not printed.
load_dotenv() {
  local file="${BGDESK_DOTENV_FILE:-$ROOT/.env}" line key value quote
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -n "${!key+x}" ]] && continue
    if [[ ${#value} -ge 2 && ( "$value" == \"*\" || "$value" == \'*\' ) ]]; then
      quote="${value:0:1}"
      if [[ "${value: -1}" == "$quote" ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    printf -v "$key" '%s' "$value"
    export "$key"
  done <"$file"
}

realpath_of() {
  python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"
}

# Read the .p12 where it already lives. The password stays in the environment
# and is never written into the repository or echoed.
prepare_external_p12() {
  [[ -n "${MACOS_P12_FILE:-}" ]] || return 0
  [[ -n "${MACOS_P12_PASSWORD:-}" ]] || \
    fail "Defina MACOS_P12_PASSWORD no .env da raiz. Esse arquivo é ignorado pelo Git."
  local p12_real root_real parent parent_real keychain_password keychain keychain_list
  p12_real="$(realpath_of "$MACOS_P12_FILE")"
  root_real="$(realpath_of "$ROOT")"
  case "$p12_real" in
    "$root_real"|"$root_real"/*)
      fail "MACOS_P12_FILE está dentro do projeto. O .p12 permanece fora do repositório e não é copiado."
      ;;
  esac
  [[ -f "$p12_real" ]] || fail "Certificado não encontrado: $MACOS_P12_FILE"
  parent="${TMPDIR:-/tmp}"
  parent_real="$(realpath_of "$parent")"
  case "$parent_real" in
    "$root_real"|"$root_real"/*) parent="/tmp" ;;
  esac
  tmp_keychain_dir="$(mktemp -d "$parent/bgdesk-signing.XXXXXX")"
  tmp_keychain="$tmp_keychain_dir/signing.keychain-db"
  keychain_list="$(security list-keychains -d user)"
  while IFS= read -r keychain; do
    [[ -z "$keychain" ]] || original_keychains+=("$keychain")
  done < <(printf '%s\n' "$keychain_list" | python3 -c 'import shlex, sys; print("\n".join(shlex.split(sys.stdin.read())))')
  keychain_password="$(openssl rand -base64 32)"
  security create-keychain -p "$keychain_password" "$tmp_keychain"
  security set-keychain-settings -lut 21600 "$tmp_keychain"
  security unlock-keychain -p "$keychain_password" "$tmp_keychain"
  # Register the imported keychain for codesign's identity/private-key lookup,
  # as required on fresh CI runners. Preserve the user's existing search list.
  keychain_search_changed=1
  security list-keychains -d user -s "$tmp_keychain" ${original_keychains[@]+"${original_keychains[@]}"}
  if ! security import "$p12_real" -k "$tmp_keychain" -P "$MACOS_P12_PASSWORD" \
      -T /usr/bin/codesign -T /usr/bin/security >/dev/null; then
    fail "Não foi possível abrir o .p12. Confira MACOS_P12_PASSWORD. O arquivo não foi copiado nem movido."
  fi
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
    -k "$keychain_password" "$tmp_keychain" >/dev/null
  unset keychain_password
  export MACOS_CODESIGN_KEYCHAIN="$tmp_keychain"
  echo "[macOS] Certificado lido no lugar, sem cópia: $p12_real"
}

checkpoint() {
  [[ -n "${BGDESK_CHECKPOINT_DIR:-}" ]] || return 0
  python3 "$ROOT/scripts/ci/macos_checkpoint.py" --dir "$BGDESK_CHECKPOINT_DIR" "$@"
}

save_compiled_app() {
  [[ -n "${BGDESK_CHECKPOINT_DIR:-}" ]] || return 0
  mkdir -p "$BGDESK_CHECKPOINT_DIR"
  checkpoint ensure --version "${BGDESK_VERSION:-}" --edition "${BGDESK_EDITION:-}" \
    --arch "${BGDESK_ARCH:-}" --origin "${BGDESK_CHECKPOINT_ORIGIN:-local}"
  COPYFILE_DISABLE=1 tar -cf "$BGDESK_CHECKPOINT_DIR/app.tar" \
    -C "$(dirname "$app_path")" "$(basename "$app_path")"
  checkpoint add-file --name app.tar --stage compiled
}

save_signed_dmg() {
  [[ -n "${BGDESK_CHECKPOINT_DIR:-}" ]] || return 0
  cp -p "$work_dir/final.dmg" "$BGDESK_CHECKPOINT_DIR/signed.dmg"
  checkpoint add-file --name signed.dmg --stage signed
}

save_delivered_dmg() {
  [[ -n "${BGDESK_CHECKPOINT_DIR:-}" ]] || return 0
  cp -p "$work_dir/final.dmg" "$BGDESK_CHECKPOINT_DIR/delivered.dmg"
  checkpoint add-file --name delivered.dmg --stage validated
}

assert_installer_layout() {
  local mount="$1"
  [[ -L "$mount/Applications" && "$(readlink "$mount/Applications")" == /Applications ]] || \
    fail "Atalho para Aplicativos ausente no DMG."
  [[ -f "$mount/.VolumeIcon.icns" ]] || fail "Ícone de volume ausente no DMG."
  [[ -e "$mount/.background/background.tiff" || -e "$mount/.background/background.png" ]] || \
    fail "Arte de instalação ausente no DMG."
  if command -v GetFileInfo >/dev/null; then
    [[ "$(GetFileInfo -aC "$mount")" == 1 ]] || fail "O DMG não usa o ícone de volume."
  fi
}

validate_distribution_image() {
  local image="$1" mount app
  [[ -f "$image" ]] || fail "DMG não encontrado: $image"
  hdiutil verify "$image"
  codesign --verify --strict --verbose=2 "$image"
  xcrun stapler validate "$image"
  spctl --assess --type open --context context:primary-signature --verbose=4 "$image"
  mount="$(mktemp -d "${TMPDIR:-/tmp}/bgdesk-validate.XXXXXX")"
  mount_point="$mount"
  mounted=1
  hdiutil attach -readonly -nobrowse -mountpoint "$mount" "$image"
  app="$(find "$mount" -maxdepth 1 -name '*.app' -print -quit)"
  [[ -n "$app" && -d "$app" ]] || fail "App ausente no DMG."
  codesign --verify --deep --strict --verbose=2 "$app"
  assert_installer_layout "$mount"
  spctl --assess --type execute --verbose=4 "$app"
  hdiutil detach "$mount" -quiet
  mounted=0
  rm -rf "$mount"
  echo "[macOS] DMG validado: $image"
}

if [[ "$stage" == "validate" ]]; then
  validate_distribution_image "$1"
  exit 0
fi

load_dotenv

team_id="${MACOS_TEAM_ID:-3Z7C3Q7NMT}"
[[ "$team_id" =~ ^[A-Z0-9]{10}$ ]] || fail "MACOS_TEAM_ID inválido."
profile="${MACOS_NOTARY_PROFILE:-bgdesk-notary}"
identity="${MACOS_CODESIGN_IDENTITY:-}"

if [[ "$identity" == "-" && "$local_build" == "1" ]]; then
  echo "[macOS] Assinatura ad hoc para testes locais."
else
  prepare_external_p12
  if [[ -n "$tmp_keychain" ]]; then
    identities=$(security find-identity -v -p codesigning "$tmp_keychain")
  else
    identities=$(security find-identity -v -p codesigning)
  fi
  # Select a valid identity with a private key; never fall back to development
  # signing for a distribution build. Names and SHA-1 fingerprints are accepted.
  identity=$(printf '%s\n' "$identities" | python3 -c '
import re, sys
requested, local, team = sys.argv[1:]
blob = sys.stdin.read()
identities = re.findall(r"\d+\) ([A-Fa-f0-9]{40}) \"([^\"]+)\"", blob)
prefix = "Apple Development:" if local == "1" else "Developer ID Application:"
matches = [(sha, name) for sha, name in identities
           if name.startswith(prefix)
           and (local == "1" or name.endswith("(" + team + ")"))
           and (not requested or requested == name or requested.upper() == sha.upper())]
if len(matches) != 1:
    extra = ""
    if any(name.startswith("Apple Distribution:") for _, name in identities):
        extra = " Apple Distribution não autoriza download pelo site; o .p12 precisa ser Developer ID Application."
    print("[macOS] ERRO: é necessária uma identidade " + prefix +
          " válida e com chave privada para a equipe " + team +
          ". Se houver várias, defina MACOS_CODESIGN_IDENTITY com o SHA-1. "
          "Consulte docs/macos-signing.md." + extra, file=sys.stderr)
    sys.exit(1)
print(matches[0][0])
' "$identity" "$local_build" "$team_id")
fi

if [[ -n "${MACOS_NOTARY_APPLE_ID:-}" && -n "${MACOS_NOTARY_PASSWORD:-}" ]]; then
  notary_args=(--apple-id "$MACOS_NOTARY_APPLE_ID" --password "$MACOS_NOTARY_PASSWORD" --team-id "$team_id")
  notary_label="conta Apple"
elif [[ -n "${MACOS_NOTARY_APPLE_ID:-}" || -n "${MACOS_NOTARY_PASSWORD:-}" ]]; then
  fail "Defina MACOS_NOTARY_APPLE_ID e MACOS_NOTARY_PASSWORD juntas no .env, ou use só MACOS_NOTARY_PROFILE."
else
  notary_args=(--keychain-profile "$profile")
  if [[ -n "${MACOS_NOTARY_KEYCHAIN:-}" ]]; then
    notary_args+=(--keychain "$MACOS_NOTARY_KEYCHAIN")
  fi
  notary_label="perfil '$profile'"
fi
if [[ "$local_build" == "0" && "$stage" != "package" ]]; then
  xcrun --find notarytool >/dev/null
  xcrun --find stapler >/dev/null
  if [[ -n "${MACOS_NOTARY_APPLE_ID:-}" && -n "${MACOS_NOTARY_PASSWORD:-}" ]]; then
    notary_hint="Não foi possível autenticar a notarização. Confira MACOS_NOTARY_APPLE_ID e MACOS_NOTARY_PASSWORD no .env."
  else
    notary_hint="Configure o perfil de notarização '$profile' conforme docs/macos-signing.md."
  fi
  xcrun notarytool history "${notary_args[@]}" --output-format json >/dev/null || \
    fail "$notary_hint"
fi
if [[ "$local_build" == "0" && "$identity" != "-" ]]; then
  echo "[macOS] Identidade: $identity; equipe: $team_id; notarização: $notary_label."
else
  echo "[macOS] Identidade: $identity; equipe: $team_id."
fi
if [[ "$check_only" == "1" ]]; then
  # Finding a certificate is insufficient: exercise private-key access before
  # spending time compiling the application on a fresh runner.
  work_dir="$(mktemp -d "${TMPDIR:-/tmp}/bgdesk-codesign-check.XXXXXX")"
  printf 'int main(void) { return 0; }\n' | xcrun clang -x c - -o "$work_dir/probe"
  probe_args=(--force --options runtime --sign "$identity")
  [[ -z "${MACOS_CODESIGN_KEYCHAIN:-}" ]] || probe_args+=(--keychain "$MACOS_CODESIGN_KEYCHAIN")
  [[ "$identity" == "-" ]] || probe_args+=(--timestamp)
  codesign "${probe_args[@]}" "$work_dir/probe"
  codesign --verify --strict "$work_dir/probe"
  echo "[macOS] Assinatura de teste validada."
  exit 0
fi

app_path=$1
if [[ "$stage" == "full" || "$stage" == "package" ]]; then
  [[ -d "$app_path/Contents/MacOS" ]] || fail "App não encontrado: $app_path"
else
  [[ -f "$app_path" ]] || fail "DMG assinado não encontrado: $app_path"
fi
app_path="$(cd "$(dirname "$app_path")" && pwd)/$(basename "$app_path")"
dmg_path=$2
[[ "$dmg_path" == *.dmg ]] || fail "A saída deve terminar em .dmg."
if [[ "$local_build" == "1" && "$dmg_path" != *-local.dmg ]]; then
  fail "O DMG de teste deve terminar em -local.dmg para não ser confundido com uma distribuição."
fi
mkdir -p "$(dirname "$dmg_path")"
dmg_path="$(cd "$(dirname "$dmg_path")" && pwd)/$(basename "$dmg_path")"
work_dir=$(mktemp -d "$(dirname "$dmg_path")/.macos-package.XXXXXX")
mount_point="$work_dir/mounted"

requirement="=anchor apple generic and certificate leaf[subject.OU] = \"$team_id\""
if [[ "$local_build" == "0" ]]; then
  requirement+=' and certificate leaf[field.1.2.840.113635.100.6.1.13] exists'
fi
verify_signature() {
  if [[ "$identity" == "-" ]]; then
    codesign --verify --deep --strict --verbose=2 "$1"
  else
    codesign --verify --deep --strict --verbose=2 -R "$requirement" "$1"
  fi
}

stapler_with_retry() {
  local action="$1" image="$2" attempt=1 delay=5 status
  while true; do
    if xcrun stapler "$action" "$image"; then
      return 0
    else
      status=$?
    fi
    # EX_NOHOST (68) includes lost CloudKit connections and unexpected service
    # responses. Retry only after Accepted; permanent ticket/disk errors fail.
    if [[ "$status" != 68 || "$attempt" -ge 5 ]]; then
      return "$status"
    fi
    echo "[macOS] stapler $action: serviço Apple indisponível (68); nova tentativa em ${delay}s ($attempt/5)." >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

# GitHub-hosted macOS runners drop CFNetwork connections to
# api.apple-cloudkit.com (NSURLError -1005, stapler 68) on every attempt.
# Repeating stapler does not change that path.
prefer_ipv4_for_cloudkit() {
  [[ "${GITHUB_ACTIONS:-}" == "true" ]] || return 0
  echo "[macOS] Desligando IPv6: neste runner o stapler perde a conexão com o CloudKit." >&2
  local service
  while IFS= read -r service; do
    case "$service" in
      ""|"An asterisk"*|\**) continue ;;
    esac
    sudo -n networksetup -setv6off "$service" || true
  done < <(networksetup -listallnetworkservices | tail -n +2)
}

BGDESK_STAPLED_WITH_RCODESIGN=0
staple_ticket() {
  local image="$1" status
  prefer_ipv4_for_cloudkit
  if [[ "${GITHUB_ACTIONS:-}" != "true" ]]; then
    stapler_with_retry staple "$image"
    return
  fi
  if xcrun stapler staple "$image"; then
    return 0
  else
    status=$?
  fi
  if [[ "$status" != 68 ]]; then
    return "$status"
  fi
  echo "[macOS] stapler não alcança o CloudKit (68). A notarização já foi Accepted; buscando o ticket com rcodesign." >&2
  if ! command -v rcodesign >/dev/null 2>&1; then
    HOMEBREW_NO_AUTO_UPDATE=1 brew install rcodesign
  fi
  rcodesign staple "$image"
  BGDESK_STAPLED_WITH_RCODESIGN=1
}

volumes_path_from_attach() {
  python3 -c '
import sys
for line in sys.stdin:
    index = line.find("/Volumes/")
    if index >= 0:
        print(line[index:].rstrip())
        break
'
}

detach_with_retry() {
  local target="$1" attempt=1 window
  window=$(basename "$target")
  osascript -e "tell application \"Finder\" to close (every window whose name is \"${window}\")" \
    >/dev/null 2>&1 || true
  while ! hdiutil detach "$target" -quiet; do
    if [[ "$attempt" -ge 8 ]]; then
      return 1
    fi
    sleep 2
    attempt=$((attempt + 1))
  done
}

apply_dmg_finder_layout() {
  local mount="$1" background_name="$2" app_name="$3"
  local disk_name script="$work_dir/dmg-layout.applescript" attempt=1 wait=0
  disk_name=$(basename "$mount")
  cat >"$script" <<EOF
tell application "Finder"
  tell disk "${disk_name}"
    open
    delay 1
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 1000, 520}
    set opts to the icon view options of container window
    tell opts
      set icon size to 128
      set text size to 16
      set arrangement to not arranged
    end tell
    set background picture of opts to file ".background:${background_name}"
    set position of item "${app_name}" to {200, 190}
    set position of item "Applications" to {600, 190}
    try
      set extension hidden of item "${app_name}" to true
    end try
    close
    open
    delay 1
    update without registering applications
    delay 2
  end tell
end tell
EOF
  open -a Finder >/dev/null 2>&1 || true
  # create-dmg waits here: Finder on GitHub-hosted Macs often answers -1728
  # ("Can't get disk") until the volume under /Volumes has been registered.
  echo "[macOS] Aguardando o Finder reconhecer $disk_name..."
  sleep 5
  while ! osascript "$script"; do
    if [[ "$attempt" -ge 5 ]]; then
      fail "Não foi possível aplicar o layout do Finder no DMG."
    fi
    echo "[macOS] Finder ainda não viu o volume; nova tentativa ($attempt/5)." >&2
    sleep 2
    attempt=$((attempt + 1))
  done
  while [[ ! -f "$mount/.DS_Store" ]]; do
    if [[ "$wait" -ge 15 ]]; then
      fail "O Finder não gravou o layout do DMG."
    fi
    sleep 1
    wait=$((wait + 1))
  done
}

create_installer_image() {
  local staging="$1" app_name="$2" output="$3"
  local assets="$ROOT/res/macos-dmg"
  local rw="$work_dir/rw.dmg" background_name min_mb size_mb

  [[ -f "$assets/volume-icon.icns" ]] || fail "Ícone de volume ausente: $assets/volume-icon.icns"
  [[ -f "$assets/background.png" ]] || fail "Arte do DMG ausente: $assets/background.png"
  [[ -f "$assets/background@2x.png" ]] || fail "Arte Retina do DMG ausente: $assets/background@2x.png"

  mkdir -p "$staging/.background"
  if command -v tiffutil >/dev/null; then
    tiffutil -cathidpicheck "$assets/background.png" "$assets/background@2x.png" \
      -out "$staging/.background/background.tiff"
    background_name="background.tiff"
  else
    cp "$assets/background.png" "$staging/.background/background.png"
    background_name="background.png"
  fi
  cp "$assets/volume-icon.icns" "$staging/.VolumeIcon.icns"
  if command -v SetFile >/dev/null; then
    SetFile -c icnC "$staging/.VolumeIcon.icns"
  fi

  rm -f "$rw"
  hdiutil create -volname BGDesk -fs HFS+ -fsargs "-c c=64,a=16,e=16" \
    -format UDRW -srcfolder "$staging" "$rw"
  min_mb=$(hdiutil resize -limits "$rw" | awk 'NR==1 {print int($1/2048)+1}')
  size_mb=$((min_mb + 20))
  hdiutil resize -size "${size_mb}m" "$rw"

  # Finder only sees volumes under /Volumes. A custom mountpoint makes
  # `tell disk` fail with -1728 on GitHub-hosted macOS runners.
  local attach_info
  attach_info=$(hdiutil attach -readwrite -noverify -noautoopen -nobrowse "$rw")
  mount_point=$(printf '%s\n' "$attach_info" | volumes_path_from_attach)
  [[ -n "$mount_point" && -d "$mount_point" ]] || fail "Não foi possível montar o DMG em /Volumes."
  mounted=1
  if command -v SetFile >/dev/null; then
    SetFile -c icnC "$mount_point/.VolumeIcon.icns"
  fi
  apply_dmg_finder_layout "$mount_point" "$background_name" "$app_name"
  if command -v SetFile >/dev/null; then
    SetFile -a C "$mount_point"
  else
    xattr -wx com.apple.FinderInfo \
      0000000000000000040000000000000000000000000000000000000000000000 \
      "$mount_point"
  fi
  rm -rf "$mount_point/.fseventsd" || true
  chmod -Rf -P go-w "$mount_point" >/dev/null 2>&1 || true
  detach_with_retry "$mount_point" || fail "Não foi possível desmontar o DMG temporário."
  mounted=0

  rm -f "$output"
  # Compressed read-only UDIF keeps the signed framework symlinks.
  hdiutil convert "$rw" -format UDZO -imagekey zlib-level=9 -o "$output"
  rm -f "$rw"
}

if [[ "$stage" == "full" || "$stage" == "package" ]]; then
  save_compiled_app
  bash "$ROOT/.github/scripts/sign-macos-app.sh" "$app_path" "$identity" \
    "$ROOT/flutter/macos/Runner/Release.entitlements"
  verify_signature "$app_path"

  staging="$work_dir/staging"
  mkdir -p "$staging"
  ditto "$app_path" "$staging/$(basename "$app_path")"
  ln -s /Applications "$staging/Applications"
  create_installer_image "$staging" "$(basename "$app_path")" "$work_dir/final.dmg"
else
  [[ -f "$app_path" ]] || fail "DMG assinado não encontrado: $app_path"
  cp -p "$app_path" "$work_dir/final.dmg"
  verify_signature "$work_dir/final.dmg"
fi
if [[ "$stage" == "full" || "$stage" == "package" ]]; then
  bundle_id=$(plutil -extract CFBundleIdentifier raw "$app_path/Contents/Info.plist")
  dmg_sign_args=(--force --sign "$identity" --identifier "$bundle_id.diskimage")
  if [[ -n "${MACOS_CODESIGN_KEYCHAIN:-}" ]]; then
    dmg_sign_args+=(--keychain "$MACOS_CODESIGN_KEYCHAIN")
  fi
  if [[ "$identity" != "-" ]]; then
    dmg_sign_args+=(--timestamp)
  fi
  codesign "${dmg_sign_args[@]}" "$work_dir/final.dmg"
  verify_signature "$work_dir/final.dmg"
  save_signed_dmg
fi
if [[ "$stage" == "package" ]]; then
  cp -p "$work_dir/final.dmg" "$dmg_path"
  echo "[macOS] DMG assinado, sem notarização: $dmg_path"
  exit 0
fi

if [[ "$local_build" == "0" ]]; then
  # Notarize the outermost container, including the signed app within it.
  result_path="${dmg_path%.dmg}.notary-result.json"
  notary_action="submit"
  if [[ "$stage" != "full" && -n "${BGDESK_CHECKPOINT_DIR:-}" ]]; then
    notary_action="$(python3 "$ROOT/scripts/ci/macos_checkpoint.py" --dir "$BGDESK_CHECKPOINT_DIR" action)"
  fi
  if [[ "$notary_action" == "submit" && "$stage" == "staple" ]]; then
    fail "A notarização deste checkpoint ainda não foi aceita. Não vou reenviar o DMG."
  fi
  if [[ "$notary_action" == "submit" ]]; then
    if ! xcrun notarytool submit "$work_dir/final.dmg" "${notary_args[@]}" \
        --wait --timeout 30m --output-format json >"$result_path"; then
      echo "[macOS] Consulte o resultado em $result_path" >&2
      exit 1
    fi
  else
    submission_id="$(python3 "$ROOT/scripts/ci/macos_checkpoint.py" --dir "$BGDESK_CHECKPOINT_DIR" field --key notarization.id)"
    if [[ "$notary_action" == "wait" ]]; then
      xcrun notarytool wait "$submission_id" "${notary_args[@]}" --timeout 30m
    fi
    xcrun notarytool info "$submission_id" "${notary_args[@]}" --output-format json >"$result_path"
  fi
  status=$(plutil -extract status raw "$result_path")
  submission_id=$(plutil -extract id raw "$result_path")
  if [[ -n "${BGDESK_CHECKPOINT_DIR:-}" ]]; then
    cp -p "$result_path" "$BGDESK_CHECKPOINT_DIR/notary-result.json"
    checkpoint notarization --id "$submission_id" --status "$status" --stage notarized
  fi
  if [[ "$status" != "Accepted" ]]; then
    log_path="${dmg_path%.dmg}.notary-log.json"
    xcrun notarytool log "$submission_id" "${notary_args[@]}" "$log_path" || true
    fail "Notarização $status ($submission_id). Consulte $result_path e $log_path."
  fi
  if [[ "$stage" == "notarize" ]]; then
    cp -p "$work_dir/final.dmg" "$dmg_path"
    echo "[macOS] Notarização aceita ($submission_id). O ticket ainda não foi anexado: $dmg_path"
    exit 0
  fi
  staple_ticket "$work_dir/final.dmg"
  if ! stapler_with_retry validate "$work_dir/final.dmg"; then
    status=$?
    if [[ "$status" != 68 || "$BGDESK_STAPLED_WITH_RCODESIGN" != 1 ]]; then
      exit "$status"
    fi
    echo "[macOS] stapler validate também não alcança o CloudKit. O ticket foi anexado; Gatekeeper confirma em seguida." >&2
  fi
  verify_signature "$work_dir/final.dmg"
  spctl --assess --type open --context context:primary-signature --verbose=4 "$work_dir/final.dmg"
fi

# Mount the actual delivered image read-only and validate its app and shortcut.
hdiutil verify "$work_dir/final.dmg"
mkdir -p "$mount_point"
mounted=1
hdiutil attach -readonly -nobrowse -mountpoint "$mount_point" "$work_dir/final.dmg"
if [[ "$stage" == "full" ]]; then
  delivered_app="$mount_point/$(basename "$app_path")"
else
  delivered_app="$(find "$mount_point" -maxdepth 1 -name '*.app' -print -quit)"
fi
verify_signature "$delivered_app"
assert_installer_layout "$mount_point"
if [[ "$local_build" == "0" ]]; then
  spctl --assess --type execute --verbose=4 "$delivered_app"
else
  echo "[macOS] Build LOCAL: sem notarização; não distribuir para outros Macs."
fi
hdiutil detach "$mount_point" -quiet
mounted=0
save_delivered_dmg
mv -f "$work_dir/final.dmg" "$dmg_path"
echo "[macOS] DMG validado: $dmg_path"
