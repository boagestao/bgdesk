#!/bin/bash
set -euo pipefail

abort() {
  printf "%s\n" "$@" >&2
  exit 1
}

[[ "$(uname -s)" == Darwin ]] || abort "Essa instalação só suporta macOS."

echo "Bem-vindo ao instalador BGDesk..."
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/bgdesk-install.XXXXXX")
mount_point="$work_dir/mounted"
mounted=0
cleanup() {
  if [[ "$mounted" == 1 ]]; then
    if ! hdiutil detach "$mount_point" -quiet; then
      echo "Não foi possível desmontar $mount_point; temporários preservados." >&2
      return
    fi
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT

requirement='=anchor apple generic and certificate leaf[subject.OU] = "3Z7C3Q7NMT" and certificate leaf[field.1.2.840.113635.100.6.1.13] exists'
dmg="$work_dir/BGDesk.dmg"
echo "Baixando o BGDesk..."
curl --fail --location --retry 3 \
  "https://boagestao.com.br/bgdesk/bgdesk-cliente-darwin.dmg" --output "$dmg"

echo "Validando a assinatura do DMG..."
codesign --verify --strict -R "$requirement" "$dmg"
spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg"
mkdir -p "$mount_point"
mounted=1
hdiutil attach -readonly -nobrowse -mountpoint "$mount_point" "$dmg"
app="$mount_point/BGDesk.app"
[[ -d "$app" ]] || abort "BGDesk.app não encontrado no DMG."
codesign --verify --deep --strict -R "$requirement" "$app"
spctl --assess --type execute --verbose=2 "$app"

echo "Instalando o BGDesk..."
sudo rm -rf /Applications/BGDesk.app
sudo ditto "$app" /Applications/BGDesk.app
codesign --verify --deep --strict -R "$requirement" /Applications/BGDesk.app
hdiutil detach "$mount_point" -quiet
mounted=0

echo "O BGDesk foi instalado com sucesso!"
open /Applications/BGDesk.app
