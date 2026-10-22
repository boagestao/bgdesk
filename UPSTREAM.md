# Sincronização BGDesk / RustDesk

A versão 1.5.1 do código foi integrada de `rustdesk/rustdesk`, branch `master`,
commit `53996e3c404ea5083df0775057e4149e49102084` (16/10/2026). As referências completas estão em
[.upstream-rustdesk.json](.upstream-rustdesk.json).

O histórico inicial do BGDesk contém um snapshot da versão 1.4.8. Esta integração
usou essa versão como base de comparação de três vias e registra o commit real
do RustDesk como segundo pai do merge, mantendo também o histórico do BGDesk.

## Personalizações mantidas

- Janela unificada do suporte Flutter para remoto, arquivos, câmera, terminal e
  túneis, fechamento macOS com confirmação por quantidade de sessões e liberação
  de captura ao trocar de aba,
  revisões numéricas BGDesk e Windows x86 somente cliente. Antes de integrar novos
  commits, ler [o guia de preservação e testes](docs/unified-session-tabs.md).
- Classe/ID Linux próprio do gerenciador de conexões recebidas (`--cm`), com
  valor `bgdesk.connection-manager`, para regras do Hyprland/gerenciador de janelas.

- Identidade BGDesk, identificadores de aplicativo, recursos e nomes dos pacotes.
- Submódulo privado `config`, geração das configurações no build e proteção das
  opções de servidor na interface/IPC.
- Validação de licença e edição `incoming-only`.
- Scripts e pipelines próprios de build, assinatura e instalação.
- Flutter stable 3.47.2 no macOS, codegen com Freezed no Flutter 3.44.4 e ajustes
  de ciclo de vida das janelas de sessão.

## Bibliotecas e atualizações futuras

O upstream mantém `libs/hbb_common` como submódulo. No BGDesk esse diretório
continua versionado diretamente, pois contém a integração com a configuração
privada. O novo `libs/base` contém código e protocolos transferidos do
`hbb_common`; preserve essa divisão ao atualizar as bibliotecas e a ponte FFI.
Não adicione um segundo submódulo em `libs/hbb_common`.

Para a próxima sincronização, execute `git fetch upstream master --tags`,
compare com o commit registrado no manifesto e obtenha também o commit de
`hbb_common` apontado pelo upstream. Compare essa biblioteca como arquivos
versionados, usando o commit anterior do manifesto como base. Resolva os
conflitos mantendo as personalizações acima e atualize o manifesto.
`scripts/update-rustdesk.sh` é um auxiliar de cópia e relatório; seus avisos de
merge manual devem ser resolvidos antes de finalizar uma atualização.
O script de branding preserva versões. A base upstream é 1.5.1, enquanto a
revisão do aplicativo é 1.5.1-1 (Flutter 1.5.1-1+69); não redefinir a revisão
nem os locks ao reaplicar branding. A primeira migração é manual.

## Atualizador assinado

As URLs de atualização aceitam somente releases de `boagestao/bgdesk`, e o
identificador de pacote público é `bgdesk`. O formato de metadados e o contexto
criptográfico continuam compatíveis com as ferramentas de `res/update`.

As chaves oficiais de assinatura do RustDesk foram removidas da lista de
confiança do BGDesk. Antes de habilitar atualizações assinadas, configure as
chaves públicas próprias em `src/update_metadata.rs` e publique metadados
`bgdesk-update.json` e sua assinatura. Para atualização offline de um cliente
personalizado, use seu bundle ID como `--package-id`. A verificação automática
permanece desabilitada para clientes personalizados, como anteriormente.

## Validação local

```sh
source "$HOME/.cargo/env"
export VCPKG_ROOT="$HOME/.bin/vcpkg"
cargo check --release --features flutter
cargo check --release --features flutter,incoming-only
cargo test --release -p hbb_common --lib config::tests -- --test-threads=1
cargo test --release --features flutter --lib update_metadata
bash scripts/check-linux-build-paths.sh
cd flutter
flutter pub get
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
cd ..
bash scripts/patch-flutter-web-deps.sh
cd flutter
flutter test --platform chrome test/floating_mouse_hold_test.dart
```

Regere a ponte após mudanças em `src/flutter_ffi.rs` com
`bash scripts/generate-bridge.sh` antes de compilar ou testar o Flutter.

Validação da integração em macOS arm64: checagens Rust das edições padrão e
`incoming-only`, 30 testes de configuração, 9 de metadados assinados, 6 de
URLs/atualização manual, 4 do leitor portátil, 14 das ferramentas Python,
117 testes Flutter nativos, 3 testes Flutter no Chrome e 83 verificações de
empacotamento passaram. A análise Flutter não encontrou erros; ainda aponta
avisos de lint e APIs depreciadas. Builds completos para distribuição e testes
em Windows, Linux, Android e iOS não foram executados nesta sincronização.
