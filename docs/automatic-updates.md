# Atualizações do BGDesk

O aplicativo consulta por HTTPS um único arquivo assinado para sua edição:

| Edição | Feed padrão | Identidade assinada |
| --- | --- | --- |
| Cliente (`incoming-only`) | `https://bgdesk.com/updates/cliente/latest.json` | `bgdesk-cliente` |
| Suporte | `https://bgdesk.com/updates/suporte/latest.json` | `bgdesk-suporte` |

O build Actions define `BGDESK_UPDATE_ORIGIN` usando `R2_PUBLIC_ORIGIN`, normalmente
`https://download.bgdesk.com`. Não há consulta ao GitHub para descobrir ou baixar
atualizações. Clientes personalizados continuam fora do canal público.

## Conteúdo do latest.json

Desde a revisão **1.5.1-3**, o próprio JSON contém a versão e todos os arquivos:

```json
{
  "schema_version": 1,
  "app": "rustdesk",
  "package_id": "bgdesk-suporte",
  "version": "1.5.1-3",
  "release_id": "v1.5.1-3",
  "published_at": "2026-10-23T12:00:00Z",
  "signature_key_id": "2026-ed25519-main",
  "artifacts": [
    {
      "platform": "windows",
      "arch": "x86_64",
      "format": "exe",
      "file_name": "bgdesk-suporte-update-win64.exe",
      "url": "https://download.bgdesk.com/bgdesk-suporte-update-win64.exe",
      "size": 123456,
      "sha256": "<SHA-256 do arquivo real>"
    }
  ],
  "signature": {
    "schema_version": 1,
    "algorithm": "ed25519",
    "key_id": "2026-ed25519-main",
    "signature": "<assinatura base64>"
  }
}
```

O exemplo é ilustrativo; a publicação calcula tamanho, hash e assinatura reais.
O identificador criptográfico `app: rustdesk` e o contexto de assinatura foram
preservados. A assinatura cobre o documento inteiro sem a propriedade
`signature`, em JSON UTF-8 compacto com chaves ordenadas recursivamente.

O aplicativo verifica a assinatura antes de confiar na versão ou nos arquivos.
Exige sua identidade de edição, versão/revisão válida, seletores únicos, nome,
origem HTTPS autorizada, SHA-256 e tamanho. A seleção do pacote e o download usam
a cópia verificada do mesmo feed; não há uma segunda busca por sidecars.
Arquivos alterados ou incompatíveis são recusados antes da instalação.

O comparador continua sendo o específico BGDesk:
`1.5.1 < 1.5.1-1 < 1.5.1-2 < 1.5.1-10 < 1.5.2`.
Cada componente cabe em u16; revisões são inteiros positivos sem zeros à esquerda.
Não usar a ordenação SemVer para revisões BGDesk nem mudar a negociação de peers.

Por instrução do usuário, não há compatibilidade online com o feed antigo
`{"url":".../v<versão>/"}`. Instale manualmente a primeira build com o formato
novo. Pastas e metadados históricos existentes não são reescritos nem apagados.

## Publicação e arquivos no R2

`res/update/website_release.py prepare` gera pacotes na raiz do diretório público
e somente `updates/<edição>/latest.json` para cada edição. Não cria pastas por
versão, páginas `index.html` ou arquivos de assinatura separados para o feed.
Cada pacote existe uma vez na raiz, compartilhado pelo site e pelo atualizador.
O canal Android segue o mesmo formato em `updates/android/<edição>/latest.json`.
Isso não implementa instalação automática no Android.

Os nomes estáveis incluem `bgdesk-cliente-aarch64.dmg`,
`bgdesk-suporte-update-win64.exe` (atualizador nativo) e
`bgdesk-suporte-win64.exe` (Inno Setup). O feed distingue `exe`, `msi` e `inno-exe`;
o Inno serve para instalação inicial, não como pacote de atualização nativo.
Windows x86 distribui somente cliente. Os demais alvos têm cliente e suporte.

O job valida o lote completo, envia e verifica todos os pacotes antes de ativar
os feeds das duas edições. Pacotes e feeds usam `no-store, max-age=0`; o JSON usa
`Content-Type: application/json`. Não aplicar fallback de SPA nesses endereços.
Durante a troca dos pacotes, uma tentativa com o feed anterior pode falhar no
hash; a tentativa seguinte deve consultar o feed atualizado.

A publicação registra a identidade concluída em `updates/releases/v<versão>.json`.
Esse registro interno é imutável e não é consultado pelo aplicativo. A repetição
da mesma versão exige os mesmos bytes; uma alteração funcional exige revisão
superior. O histórico de binários fica no GitHub Releases. Reaproveitamento de
builds por versão completa/alvo e preservação de commit/run continuam obrigatórios.
Consulte [github-actions.md](github-actions.md).

## Preparação local

Use a virtualenv de assinatura e a chave existente:

```sh
.tools/update-signing/bin/python res/update/website_release.py prepare \
  --edition suporte \
  --version 1.5.1-3 \
  --site-public /caminho/site-public \
  --artifact macos aarch64 dmg /caminho/bgdesk-suporte-aarch64.dmg \
  --artifact windows x86_64 exe /caminho/bgdesk-suporte-update-win64.exe \
  --artifact windows x86_64 inno-exe /caminho/bgdesk-suporte-win64.exe
```

Repita para cliente com os respectivos pacotes. A chave privada padrão fica em
`~/.config/bgdesk/update-signing.json`, com permissão `0600`, fora do diretório
público e do Git. O preparo confere sua correspondência com a chave pública
compilada em `src/update_metadata.rs`. Não execute `init-key` para uma publicação
normal nem imprima a chave. O preparo local não faz upload.

## Comportamento e erros

A opção `enable-check-update` controla a consulta e o aviso. A instalação
automática exige `allow-auto-update`, serviço/instalação compatível e ausência
de sessões ativas. O serviço verifica após cerca de 30 segundos e depois a cada
24 horas, com repetição em cerca de 30 minutos após falha ou sessão ativa.
No Linux, o botão Atualizar baixa o pacote correto e instala pelo próprio
aplicativo, com autorização gráfica quando necessária. Dispositivos móveis
continuam usando download/gerenciador de pacotes.

No Windows, ausência da chave de desinstalação ou do valor `WindowsInstaller`
indica instalação por EXE, sem provocar `os error 2` ao selecionar o pacote.
Permissões negadas e tipos inválidos no Registro continuam sendo reportados.
Os botões dos diálogos de erro abrem **https://bgdesk.com**. O botão usa **Abrir o website** em pt-BR/pt-PT, **Open website** em inglês e
**Abrir el sitio web** em espanhol, com traduções em todos os idiomas disponíveis.

O fluxo offline conserva `bgdesk-update.json` e `bgdesk-update.json.sig`, com
verificação de assinatura, identidade, hash e tamanho. A mudança do feed online
não altera os mapeamentos de pacotes nativos nem o formato de atualização offline.

Antes da distribuição, validar a troca real entre revisões nas duas edições de
Windows/macOS, incluindo reinício do serviço, adiamento com sessão ativa e
isolamento de clientes personalizados. Testes automatizados não substituem esse
upgrade em cada plataforma.

## Windows x86

O Windows de 32 bits distribui somente cliente, com interface Sciter. O Setup
Inno é `bgdesk-cliente-win32.exe`; o pacote nativo de atualização é
`bgdesk-cliente-update-win32.exe`. O atualizador seleciona `windows/x86/exe` no
feed assinado, sem confundir o Setup `inno-exe` ou o pacote x64.

A detecção de MSI é compartilhada com x64: a ausência de `WindowsInstaller`
significa instalação por EXE, sem provocar `os error 2`. A atualização automática
roda no processo de serviço instalado, se habilitada e sem conexões ativas.
O botão da interface Sciter abre `https://bgdesk.com`; ele não usa o diálogo de
download/instalação do Flutter x64.

O CI confere PE32 do app/runtime/atualizador, a versão retornada pelo aplicativo
e a abertura da janela Sciter. Esses testes não executam uma instalação Inno
completa nem um upgrade real entre revisões. Essa validação ainda precisa ocorrer
em Windows; conferência de hashes, seletores e empacotamento não a substitui.

## Atualizações Linux

O aviso de versão nova oferece **Atualizar** também no Linux. Depois da
verificação do feed e do download, o aplicativo instala o formato correspondente
à instalação em uso, sem exigir que o usuário abra um terminal:

- **Debian/Ubuntu (`.deb`):** APT instala o arquivo local e resolve dependências,
  preservando arquivos de configuração existentes e recusando remoções.
- **RPM (`.rpm`):** RPM atualiza o pacote local e mantém as verificações normais
  de dependências e assinaturas do sistema.
- **Arch (`.pkg.tar.zst`):** Pacman atualiza o pacote local sem pedir confirmação
  no terminal. A política de assinaturas configurada no sistema é preservada.
- **AppImage:** a nova versão substitui o arquivo do próprio usuário por uma
  troca atômica, conservando a permissão de execução. Não há chamada root nem
  solicitação de senha. Se o arquivo não pertencer ao usuário, não existir ou
  não puder ser substituído, o aplicativo orienta o download pelo site.

Para DEB/RPM/Arch, `pkexec --disable-internal-agent` solicita a autorização pelo
agente gráfico Polkit da sessão. A senha de administrador é tratada pelo sistema;
o BGDesk não a recebe nem a armazena. A dependência `pkexec`/`polkit` é declarada
nos pacotes. A sessão gráfica precisa ter um agente de autenticação ativo.
Não há fallback para um prompt textual ou para um terminal.

O executável elevado precisa ser a instalação protegida em
`/usr/share/bgdesk/bgdesk`. O formato é identificado pelo pacote que possui esse
arquivo nas bases DPKG/RPM/Pacman; a distribuição, sozinha, não decide o formato.
O helper valida novamente o `latest.json` assinado, a edição, a arquitetura e
uma versão superior à compilada. Ele copia o pacote para uma pasta root privada
e confere tamanho e SHA-256 dessa cópia antes de chamar o gerenciador. Os comandos
usam argumentos separados, sem shell e sem desabilitar verificações de pacotes.

A instalação é recusada enquanto houver sessões ativas ou seu estado não puder
ser confirmado por IPC. O helper é iniciado com o subcomando `linux-update`,
sem `--`, para sobreviver aos hooks que param processos `bgdesk --...` durante
a atualização do serviço. O código de saída do instalador e a versão retornada
pelo aplicativo instalado são conferidos antes de informar sucesso.

Cancelar a autorização encerra a tentativa sem instalar. Erros de detecção,
integridade, autorização ou instalação mostram uma mensagem traduzida orientando
o download manual, com **Abrir o website** apontando para `https://bgdesk.com`.
Depois do sucesso, uma mensagem pede para reiniciar o BGDesk e usar a nova versão.

Este fluxo é interativo: é iniciado no aplicativo e usa autorização do usuário.
O Linux não instala silenciosamente pelo serviço nem habilita uma política
Polkit sem senha. Também não configura repositórios APT, DNF/YUM ou Pacman.

Validação necessária em desktop Linux antes de distribuir: instalar e atualizar
cada formato, confirmar o diálogo Polkit, testar cancelamento/negação e ausência
do agente, sessão ativa, pacote alterado, AppImage sem permissão e reinício do
serviço. Os testes de componentes não substituem essa validação gráfica.

Verificação local desta implementação: 154 testes Flutter passaram (um caso de
navegador pulado), e a análise dos arquivos Flutter alterados não encontrou erros
nem avisos, somente sete informações de depreciação já existentes. Os testes
Rust passaram em macOS nas duas edições (42 por edição), incluindo assinatura
do feed, seleção do pacote e substituição do AppImage. O preflight passou:
14 testes de metadados, sete de publicação do site, 102 de CI (cinco pulados)
e 91 verificações de caminhos Linux.
Em contêiner Linux, 13 testes de componentes passaram para cada edição, como
root e como UID 1000; esse ambiente usa substitutos para IPC e carregamento do
feed e não executa a instalação real nem o diálogo Polkit. As traduções de erro,
sucesso e do botão do website estão preenchidas nos 53 idiomas disponíveis.
