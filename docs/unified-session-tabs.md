# Abas de sessão e revisões do BGDesk

Esta personalização começa em **1.5.1-1**, com base no RustDesk **1.5.1**.
O commit upstream continua registrado em `.upstream-rustdesk.json`: incrementar
uma revisão BGDesk não significa integrar outra versão RustDesk.

## Comportamento e plataformas

No suporte Flutter (Windows x64, macOS e Linux), uma janela contém Início,
Configurações e abas de acesso remoto, transferência, câmera, terminal e túnel TCP/RDP. As sessões continuam
ativas em segundo plano. Reconectar ao mesmo destino/tipo seleciona sua aba;
acesso remoto e arquivos do mesmo destino têm identidades distintas.

O Windows x86 usa Sciter e passa a ser distribuído **somente como cliente**.
Não portar estas mudanças de Flutter para Sciter, nem reativar suporte x86 ao
atualizar a matriz upstream. Os demais clientes conservam a interface recebida.
Todos esses tipos usam a janela principal do suporte, inclusive quando iniciados
pelo menu da sessão ou links. As edições cliente preservam seus fluxos anteriores.

A primeira entrega não permite destacar uma aba remota nem abrir monitores em
janelas independentes: selecionar um monitor atualiza a mesma sessão.
A barra de abas continua acessível em tela cheia. Ctrl+Tab e Ctrl+Shift+Tab
navegam pelas abas locais; a sessão preserva seus atalhos configuráveis.
Fechar uma aba encerra somente sua sessão. Fechar a janela principal (botão
vermelho no macOS, Fechar no Windows/Linux) confirma se houver duas ou mais
abas de sessão, oculta a janela imediatamente e só então encerra as conexões.
Uma única aba de sessão não pede confirmação. Cancelar preserva janela e
sessões. Início e Configurações não entram nessa contagem. Abas em conexão
também contam, e duas abas de terminal contam separadamente mesmo compartilhando
uma FFI. Minimizar o aplicativo mantém as sessões. A saída explícita pelo
sistema também oculta primeiro e preserva a auditoria cancelável antes de
encerrar. A barra de abas não inclui um botão Sair.
A barra flutuante remota tem um botão direto de transferência de arquivos,
imediatamente antes do chat; o menu de controles não repete essa opção.
O botão preserva o token da conexão e abre/seleciona a aba de arquivos do destino.
O botão `+` do suporte seleciona Início, limpa o ID de destino e foca o campo
para uma nova conexão. Ele também libera a captura da aba anterior. Uma resposta
atrasada que carrega o último ID não pode preencher novamente o campo limpo.

## Responsabilidades e diferenças do upstream

- `desktop_tab_page.dart` é o host das sessões no suporte. Cria páginas existentes
  `RemotePage`, `FileManagerPage`, `ViewCameraPage`, `TerminalPage` e
  `PortForwardPage`. As chaves são `remote:<peer>`, `file:<peer>`, `camera:<peer>`,
  `terminal:<peer>_<terminalId>`, `tcp:<peer>` e `rdp:<peer>`.
  O UUID da FFI continua sendo a identidade de uma sessão em execução.
  O botão `+` seleciona Início antes de chamar `prepareNewConnection` na
  `ConnectionPage`, via chave passada pela `DesktopHomePage`. O foco é solicitado
  após a navegação; preservar a limpeza dos dois controllers do ID e a proteção
  contra a restauração assíncrona do último destino.
- `multi_window_manager.dart` encaminha todos os tipos de sessão ao host por callback.
  Aguarda seu registro antes de tratar deep links recebidos no primeiro frame.
  O host não substitui o handler IPC da página Início.
- `DesktopTabController` desativa a aba anterior **antes** de mudar a seleção.
  Remover uma aba em segundo plano preserva a aba selecionada. Saltos de página
  atrasados verificam novamente a chave e o índice desejados.
- `RemotePage` escuta os eventos da janela principal via `window_manager`;
  janelas legadas ainda recebem `desktop_multi_window`. Foco e tela cheia não
  podem ser inferidos exclusivamente pelo tipo global `DesktopType.remote`.
- O host trata solicitações canceláveis de saída do sistema com
  `WidgetsBindingObserver.didRequestAppExit`. No macOS, `AppDelegate` restaura a
  janela oculta ao reabrir pelo Dock, em vez de terminar suas sessões.
- `closeConnection(sessionId: ...)` e `FFI.closeTab()` vinculam erros, cancelamentos
  e diálogos ao UUID de origem. Um UUID já removido não pode fechar a aba atual.
  Callbacks de sessões devem sempre fornecer sua identidade, inclusive após await.
  Erros da FFI compartilhada do terminal fecham todas as suas abas irmãs e
  preservam as de outros peers/tipos.
- `TerminalTabsMixin`, em `terminal_tab_page.dart`, compartilha persistência,
  atalhos, menu de abas e consentimento de clipboard entre host e janela legada.
  No host, não registra outro handler IPC nem restaura dimensões da janela legada.
  A restauração de terminais persistentes usa callback local e verifica se a FFI
  de origem ainda existe. Atalhos de terminal só interceptam teclas quando uma
  aba terminal está selecionada. Desativar a aba desfoca seu campo de entrada.
- `FFI.sharedStateId` separa o estado visual da câmera (`camera:<peer>`) do acesso
  remoto ao mesmo peer, mantendo `FFI.id` como destino real do protocolo.
  Preservar esse namespace nos modelos, toolbar e renderização de texturas;
  fechar câmera não pode apagar nem modificar o estado de um acesso remoto.
  Câmera não adquire captura nativa de teclado.
- `closeMainSessionTabs` / `prepareCloseMainSessionTabs` decidem confirmação
  antes de qualquer encerramento. `DesktopTab` oculta a janela e só depois
  chama `onWindowHidden` para encerrar as sessões. `FFI.close` é idempotente por ciclo `start`/`close`;
  o host aguarda a desmontagem das páginas e os fechamentos nativos. Arquivos
  aguardam `FileModel.close` antes da FFI; terminais encerram shells não
  persistentes antes de liberar a conexão compartilhada. Preservar essas ordens.

## Identificação do gerenciador de conexões no Linux

A janela de permissões/chat de quem recebe um acesso é o gerenciador de
conexões (`--cm`), separado da janela principal. Em `flutter/linux/my_application.cc`,
esse processo usa `bgdesk.connection-manager` como ID GTK/Wayland
e classe X11/XWayland, nas edições suporte e cliente.
A janela principal conserva sua identificação anterior.

O ID GTK e o nome GLib do processo (`g_set_prgname`, usado como `app_id` pelo
backend Wayland GTK 3) são definidos na criação da aplicação, e a classe GDK
antes de construir a janela. Não mover essa configuração para o Dart ou para
depois de exibir a janela: regras que usam a classe inicial precisam reconhecê-la
no primeiro map.
Preservar esse identificador ao integrar alterações no runner Flutter ou no branding.

No Hyprland, conferir `class`, `initialClass` e `xwayland` com `hyprctl clients -j`
após abrir a janela principal e receber uma conexão. A classe do gerenciador deve
ser o valor acima desde a abertura, independentemente do título/nome do usuário.
Usar esse valor no filtro de classe das regras; a sintaxe depende da versão do
Hyprland. Validar em Wayland nativo e XWayland, nas edições suporte e cliente.
Essa identificação distingue o tipo da janela, não o estado de autorização de
cada sessão. Não altera permissões, desconexão nem o ciclo de vida do gerenciador.

Referências: [classe X11 no GDK](https://docs.gtk.org/gdk3/func.set_program_class.html),
[app_id no backend Wayland GTK 3](https://github.com/GNOME/gtk/blob/gtk-3-24/gdk/wayland/gdkwindow-wayland.c)
e [regras do Hyprland 0.53](https://wiki.hypr.land/0.53.0/Configuring/Window-Rules/).
A verificação estática Linux passou (84 verificações). Esta alteração ainda não
foi compilada nem validada em um compositor Linux; o ambiente local é macOS.

## Invariantes de entrada

1. Sair de uma aba remota para **qualquer** outra aba libera teclado, mouse,
   modificadores e botões pressionados, desativa mouse relativo e cancela
   recuperações pendentes de foco/tela cheia. Não depender de `WindowBlur`:
   a janela permanece focada durante uma troca de aba.
2. Somente a aba selecionada pode adquirir entrada. O foco na área remota e os
   bloqueios de diálogos continuam necessários. Uma aba selecionada não recebe
   captura automaticamente apenas por possuir uma sessão conectada.
3. `InputModel` rejeita entrada/reativação de sessões não selecionadas.
   `ShortcutModel` verifica a seleção antes e depois de operações assíncronas.
4. Uma resposta atrasada ao habilitar mouse relativo não pode recuperar a captura
   depois da desativação. Preservar a geração das requisições e a propriedade do
   recurso nativo em `RelativeMouseModel`.
5. Preservar a filtragem Rust de transições antigas por UUID em
   `session_enter_or_leave`. Não substituir por um estado booleano global.
   A desativação explícita chama também `session_deactivate_input`, que libera
   imediatamente o proprietário correto, sem o debounce de foco do X11.
6. As teclas enviadas pelo Flutter são rastreadas por sessão, com o formato de
   soltura correspondente ao keydown (Legacy, Map ou Raw Map). A desativação
   libera essas teclas antes de descartar o foco, mesmo quando o keyup físico
   chega a outra aba. Não confundir resetar modificadores locais com enviar keyup.
7. A auditoria durante a saída usa o overlay global, pois o overlay de uma sessão
   pode estar fora da tela. Manter a associação por sessão e o cancelamento da saída.
8. Ajustes assíncronos da janela verificam seleção e geração de seleção após
   cada await, antes de alterar tela cheia, maximização, dimensões ou estado global.
   Voltar à mesma aba não torna válida uma operação anterior à sua desativação.
   A geração vem do controller de abas: eventos de foco causados pela própria
   saída da tela cheia não invalidam o ajuste solicitado pelo usuário.

Os testes de abas e atalhos estão em `flutter/test/unified_tabs_test.dart` e
`shortcut_model_test.dart`. `session_lifecycle_test.dart` verifica auditoria
global e cancelamento de ajustes atrasados; `keyboard::client::grab_owner_tests`
verifica liberação imediata, debounce de feedback e preservação do novo dono.
Eventos de uma sessão em segundo plano nunca devem
fechar outra aba, alterar sua seleção ou recuperar sua entrada.

## Versão-base, revisão e identificação de build

A versão canônica é `MAJOR.MINOR.PATCH[-REVISAO]`. Revisões são inteiros positivos,
sem zeros à esquerda, até 65535. Cada componente da base também cabe em u16.
Sem sufixo equivale a revisão zero; não publicar `-0`. Sufixos alfabéticos e um
quarto componente na versão canônica não são aceitos.

`1.5.1 < 1.5.1-1 < 1.5.1-2 < 1.5.1-10 < 1.5.2`.

As revisões são releases estáveis BGDesk, embora a sintaxe seja de prerelease
para ferramentas SemVer genéricas. Não usar ordenação SemVer para descobrir
atualizações. `src/update_source.rs` compara a tupla base/revisão; a contraparte
Python é `res/update/application_version.py`. Preservar os dois comportamentos.
Não alterar `hbb_common::get_version_number`: ele é usado na negociação de
capacidades com peers RustDesk e não é o comparador do atualizador BGDesk.

Representações para a primeira revisão:

- Cargo principal e portable, locks, CLI e metadados assinados: `1.5.1-1`.
- Flutter: `1.5.1-1+69`; `69` é o identificador de build, não a revisão.
- Windows Inno: AppVersion `1.5.1-1`, recurso numérico `1.5.1.1`.
  O recurso numérico do app Flutter mantém seu número de build.
- DEB: `1.5.1-1`. RPM e Arch: versão de pacote `1.5.1.1`;
  a transformação não muda a versão canônica do aplicativo ou manifesto.
- macOS: CFBundleShortVersionString `1.5.1`, CFBundleVersion `69` e
  BGDeskApplicationVersion `1.5.1-1`. `build.py` grava os campos antes de assinar.
  O atualizador verifica o campo completo para revisões; versões antigas sem
  revisão continuam verificando CFBundleShortVersionString. Não deixar o Flutter
  converter o sufixo em parte do patch (`1.5.11`).

A primeira migração para 1.5.1-1 é **manual**: o aplicativo anterior recusa URLs
com sufixo e não pode aprender a nova política antes de ser instalado. Depois,
revisões superiores podem ser oferecidas automaticamente. Validar o ciclo com
duas revisões; não publicar um pacote falso só para testar.

## Publicação e reaproveitamento

Tags e diretórios de metadados usam `v1.5.1-1`. O `latest.json` da mesma edição
aponta para esse diretório. Assinatura, seletores, tamanho, hash e origem mantêm
suas verificações. Pacotes permanecem uma única vez na raiz do R2.

Reutilizar por **versão canônica completa e alvo**, sem invalidar por commit:
1.5.1 e 1.5.1-1 não são a mesma build. Validar os arquivos reais de todas as
edições distribuídas naquele alvo, preservando commit/run de origem. No x86,
exigir somente cliente; em x64, ambas as edições.

`scripts/ci/distribution.py` define as edições por alvo. A matriz completa tem
13 conjuntos e 26 pacotes internos; o GitHub público tem 23 downloads, incluindo
três Setups Windows (cliente x86, cliente x64 e suporte x64). Não produzir
suporte x86. Releases históricas e bytes assinados existentes são preservados.

## Checklist para integrar novos commits RustDesk

1. Ler este documento, `UPSTREAM.md` e `AGENTS.md`; usar o manifesto upstream
   como base da comparação, sem interpretar a revisão BGDesk como versão RustDesk.
2. Revisar roteamento de todos os tipos, registro do host, controllers,
   namespaces câmera/remoto e identidades das abas. Não restaurar abertura automática de janelas do suporte Flutter.
3. Revisar foco, teclas/botões presos, mouse relativo, recuperação assíncrona de
   tela cheia, liberação por UUID e cancelamento/fechamento em segundo plano.
4. Conferir todos os manifests e locks. O script de branding não deve redefinir
   versões nem o contador Flutter. Manter a comparação de revisões fora da lógica
   de compatibilidade do protocolo.
5. Conferir mapeamentos de pacotes, metadados assinados, validações de CI e a
   exclusão de suporte x86. Não relaxar assinatura/origem para aceitar um sufixo.
6. Executar Flutter analyze/test, testes Rust de update_source/metadados/feed,
   `grab_owner_tests`, testes Python de atualização/publicação/reuso e
   verificações de empacotamento. Mudanças em `src/flutter_ffi.rs` exigem regenerar
   a ponte via `scripts/generate-bridge.sh` e compilar o núcleo junto com o Flutter.
7. Antes de distribuir, validar com sessões reais no suporte Windows x64,
   macOS e Linux: duas conexões e uma transferência; troca por clique/atalho;
   modificadores e botões pressionados; mouse relativo; minimizar/ocultar;
   tela cheia; desconexão/reconexão em segundo plano; fechar aba e sair.
   Verificar também os clientes, incluindo o x86 Sciter.

Testes automatizados não substituem a validação de hooks nativos com sessões
reais. Registrar resultados e limitações da validação da integração, sem marcar
plataformas não executadas como aprovadas.

## Validação da revisão inicial

Executado localmente em macOS ARM64:

- 132 testes Flutter passaram; um teste exclusivo de navegador foi pulado.
  `flutter analyze` não encontrou erros; continuam avisos de lint/depreciação.
- 34 testes Rust de teclado passaram, incluindo os três casos de propriedade da
  captura: desativação imediata com debounce pendente, callback antigo de outro
  dono e preservação do debounce para feedback de foco. A ponte foi regenerada.
  Os testes Flutter incluem soltura de tecla comum em Legacy/Map/Raw Map,
  auditoria global de aba oculta (confirmar/cancelar) e ajustes atrasados após
  trocar de aba, inclusive quando o usuário retorna à aba original.
- 28 testes Rust de atualização passaram, incluindo feed, revisão, assinatura,
  seletores e download verificado. A biblioteca Rust compilou em release;
  `cargo check --release --features flutter,incoming-only` também passou.
- 24 testes Python de metadados/atualização e 91 de CI/publicação passaram,
  com cinco casos dependentes de ferramentas/plataforma indisponíveis pulados.
- 26 testes de empacotamento macOS passaram, usando assinatura ad hoc real e
  respostas simuladas de notarização. As 84 verificações de caminhos Linux passaram.
- O app macOS ARM64 compilou com o core atualizado. CLI `--version` retornou
  `1.5.1-1`; os campos do bundle foram conferidos como base `1.5.1`, revisão
  `1.5.1-1` e build `69`. Após as correções do review, o suporte macOS ARM64 foi
  recompilado, assinado e notarizado (Accepted); assinatura, ticket anexado e
  Gatekeeper passaram. O bundle contém a nova API `session_deactivate_input`.

Não foram executados testes com duas conexões remotas reais e transferência,
nem instalação entre duas revisões, nem compilações nativas Windows/Linux.
Essas verificações continuam necessárias antes da distribuição. Nenhum pacote
foi instalado ou publicado durante esta implementação.

## Validação da extensão de tipos e fechamento macOS

Após incluir câmera, terminal e túnel na janela principal, o botão de arquivos
na barra flutuante e a regra de fechamento macOS, 151 testes Flutter passaram
localmente em macOS ARM64 (um caso exclusivo de navegador pulado). `flutter
analyze` não encontrou erros. O suporte macOS ARM64 foi recompilado, assinado
e notarizado (Accepted); o Gatekeeper aceitou o DMG e o app, e o stapler
anexou o ticket. O bundle continua `1.5.1` / build `69`. Nenhum pacote foi
instalado ou publicado nesta etapa.

Ainda pendente com sessões reais:

- Abrir remoto, arquivos, câmera, terminal e TCP pelo menu da sessão; verificar
  abas na mesma janela, inclusive duas abas de terminal e remoto/câmera do mesmo ID.
- Fechar a janela com zero e uma sessão de cada tipo: sem confirmação múltipla;
  a janela some imediatamente e a sessão única desconecta em seguida. Com várias
  (inclusive tipos mistos), cancelar mantém janela e sessões; confirmar oculta
  primeiro e encerra depois. Início/Configurações não contam.
- Repetir durante conexão inicial, reconexão, tela cheia e transferência ativa.
  Alternar para todas as abas e conferir soltura imediata de teclado/mouse/modificadores.
- Verificar persistência de terminal habilitada/desabilitada, restauração de
  shells, Ctrl/Cmd+T, Ctrl/Cmd+W, consentimento de clipboard e erros de uma FFI
  compartilhada sem afetar outros peers.
- Verificar botão Arquivos antes de Chat, sem item duplicado no menu, reutilizando
  autenticação/token e selecionando a aba existente do mesmo destino.
