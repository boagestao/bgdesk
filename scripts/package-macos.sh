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
if [[ "$check_only" == "1" ]]; then
  [[ $# == 0 ]] || fail "--check não aceita caminhos."
else
  [[ $# == 2 ]] || fail "Uso: $0 [--local] app.app output.dmg"
fi

tmp_keychain=""
tmp_keychain_dir=""
work_dir=""
mounted=0

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
  local p12_real root_real parent parent_real keychain_password
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
  keychain_password="$(openssl rand -base64 32)"
  security create-keychain -p "$keychain_password" "$tmp_keychain"
  security set-keychain-settings -lut 21600 "$tmp_keychain"
  security unlock-keychain -p "$keychain_password" "$tmp_keychain"
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
if [[ "$local_build" == "0" ]]; then
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
[[ "$check_only" == "0" ]] || exit 0

app_path=$1
[[ -d "$app_path/Contents/MacOS" ]] || fail "App não encontrado: $app_path"
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

bash "$ROOT/.github/scripts/sign-macos-app.sh" "$app_path" "$identity" \
  "$ROOT/flutter/macos/Runner/Release.entitlements"
verify_signature "$app_path"

staging="$work_dir/staging"
mkdir -p "$staging"
ditto "$app_path" "$staging/$(basename "$app_path")"
ln -s /Applications "$staging/Applications"
# A compressed, read-only UDIF image preserves the signed framework symlinks.
hdiutil create -volname BGDesk -fs HFS+ -format UDZO -srcfolder "$staging" \
  "$work_dir/final.dmg"
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

if [[ "$local_build" == "0" ]]; then
  # Notarize the outermost container, including the signed app within it.
  result_path="${dmg_path%.dmg}.notary-result.json"
  if ! xcrun notarytool submit "$work_dir/final.dmg" "${notary_args[@]}" \
      --wait --timeout 30m --output-format json >"$result_path"; then
    echo "[macOS] Consulte o resultado em $result_path" >&2
    exit 1
  fi
  status=$(plutil -extract status raw "$result_path")
  submission_id=$(plutil -extract id raw "$result_path")
  if [[ "$status" != "Accepted" ]]; then
    log_path="${dmg_path%.dmg}.notary-log.json"
    xcrun notarytool log "$submission_id" "${notary_args[@]}" "$log_path" || true
    fail "Notarização $status ($submission_id). Consulte $result_path e $log_path."
  fi
  xcrun stapler staple "$work_dir/final.dmg"
  xcrun stapler validate "$work_dir/final.dmg"
  verify_signature "$work_dir/final.dmg"
  spctl --assess --type open --context context:primary-signature --verbose=4 "$work_dir/final.dmg"
fi

# Mount the actual delivered image read-only and validate its app and shortcut.
hdiutil verify "$work_dir/final.dmg"
mkdir -p "$mount_point"
mounted=1
hdiutil attach -readonly -nobrowse -mountpoint "$mount_point" "$work_dir/final.dmg"
delivered_app="$mount_point/$(basename "$app_path")"
verify_signature "$delivered_app"
[[ -L "$mount_point/Applications" && "$(readlink "$mount_point/Applications")" == /Applications ]] || \
  fail "Atalho para Aplicativos ausente no DMG."
if [[ "$local_build" == "0" ]]; then
  spctl --assess --type execute --verbose=4 "$delivered_app"
else
  echo "[macOS] Build LOCAL: sem notarização; não distribuir para outros Macs."
fi
hdiutil detach "$mount_point" -quiet
mounted=0
mv -f "$work_dir/final.dmg" "$dmg_path"
echo "[macOS] DMG validado: $dmg_path"
