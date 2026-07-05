#!/bin/bash

set -u

abort() {
  printf "%s\n" "$@" >&2
  exit 1
}

if [ -z "${BASH_VERSION:-}" ]
then
  abort "Bash is required to interpret this script."
fi

OS="$(uname)"
if [[ "${OS}" == "Darwin" ]]
then
  HOMEBREW_ON_MACOS=1
else
  abort "Essa instalação só suporta macOS."
fi

echo "Bemvindo ao instalador BGDesk..."
echo "Esse script irá instalar o BGDesk no seu computador."
echo

echo "Baixando o BGDesk..."
cd $HOME
mkdir -p .temp/bgdesk
cd .temp/bgdesk
rm -rf *


curl https://boagestao.com.br/bgdesk/bgdesk-cliente-darwin.zip -o bgdesk-cliente-darwin.zip


echo "Extraindo o BGDesk..."
unzip -qo bgdesk-cliente-darwin.zip

echo "Instalando o BGDesk..."
rm -rf /Applications/BGDesk.app
mv BGDesk.app /Applications/

xattr -c /Applications/BGDesk.app

echo "Removendo arquivos temporários..."
cd $HOME
rm -rf .temp/bgdesk

echo "O BGDesk foi instalado com sucesso!"
open /Applications/BGDesk.app