# Build e publicação pelo GitHub Actions

O workflow de distribuição é `.github/workflows/release.yml`, **BGDesk - Build and
publish**. Cada push na `main` compila cliente e suporte do alvo selecionado. A variável
`BGDESK_RELEASE_TARGET` controla o alvo temporário de validação; ausente ou
`all`, ativa as seis máquinas. Durante a validação individual
o deploy R2 fica desativado. Também pode executar
manualmente, escolhendo todas as plataformas ou apenas uma, com `publish=false`
para testar sem publicar. Publicação é permitida somente a partir da `main`.

A matriz mantém seis máquinas e exige 28 pacotes internos das duas edições. A release pública
tem 24 pacotes: dois APKs universais e 22 instaladores desktop; os quatro EXEs Windows são somente Setup (32/64 bits). Um conjunto
incompleto não substitui o `latest.json`.

O bridge Flutter–Rust é gerado uma vez, num job Ubuntu anterior às compilações.
O resultado fica em cache, pela hash de `src/flutter_ffi.rs`, do pubspec e do
gerador, e também como artefato `flutter-bridge`. Cada plataforma baixa esse
artefato e recusa recompilar se ele não estiver presente. Os arquivos gerados
são os mesmos para macOS, Windows, Linux e Android.

São seis jobs paralelos, em máquinas nativas do GitHub. Cada job prepara o
ambiente uma vez e compila primeiro o cliente, depois o suporte, na mesma máquina:

- macOS Apple Silicon e Intel: DMGs assinados, notarizados e verificados pelo
  mesmo `build.sh` / `package-macos.sh` usado no Mac local.
- Windows x64 e x86, na mesma máquina: instalador Inno Setup e um executável separado para atualização,
  que aceita `--update`. Ambos recebem assinatura Authenticode; o aplicativo
  interno também é assinado antes de empacotar.
- Linux x64 e ARM64: `.deb`, `.rpm` e AppImage, pelas imagens Docker do projeto.
  O x64 também gera `.pkg.tar.zst` para Arch Linux e derivados, reaproveitando
  o bundle já compilado, sem outra compilação ou runner.
  ARM64 continua usando o Flutter eLinux 3.29.3 compatível com esse ambiente.

- Android: APK universal para ARM64 (`arm64-v8a`), ARMv7 (`armeabi-v7a`) e
  x86_64. O cliente usa `incoming-only` no Rust e o ID
  `br.com.boagestao.bgdeskcliente`; o suporte preserva
  `br.com.boagestao.bgdesksuporte`. As edições compartilham a keystore existente.
  Antes de salvar o artefato, o CI verifica os quatro `.so` de cada ABI,
  versão `1.5.1`, versionCode `68`, application ID e certificado de assinatura.
  O workflow Android antigo foi substituído pelo alvo `android` do `release.yml`.
  O `uni_links` fixado já usa o embedding v2; `scripts/patch-android-plugins.py`
  remove somente seu método estático legado `registerWith(Registrar)`, incompatível
  com o Flutter atual, depois do `pub get`. Os handlers v2 de engine, activity e
  deep links são preservados. O patch é idempotente e recusa alterações inesperadas
  no método legado. As dependências vcpkg/Gradle são salvas em cache mesmo se uma
  etapa posterior de empacotamento falhar; chaves e `key.properties` ficam fora dele.
  O Gradle usa heap de 4 GiB e até dois workers, com Kotlin no mesmo processo.
  Jetifier fica desativado: o app e os plugins Android já usam AndroidX. Isso evita
  transformar os grandes JARs nativos do engine, que esgotavam o heap de 2 GiB.

O Rust está fixado em `1.98.0`, usado na validação local. Mac, Windows e Android leem o pin
de `scripts/flutter-stable-version`. Os geradores do bridge usam um SDK de
ferramentas separado para manter compatibilidade com o analyzer do Freezed.
Há cache de dependências nativas e de camadas Docker; o primeiro build é mais lento.
Rust, Flutter, vcpkg e as ferramentas de assinatura são preparados uma vez por
plataforma e arquitetura. As duas edições compartilham downloads e dependências
compiladas do Cargo; no Linux também usam a mesma imagem e os mesmos volumes
Docker. Os artefatos de cada edição são guardados separadamente antes de iniciar
a próxima, sem apagar o cache de compilação entre elas. A publicação continua
exigindo os 28 arquivos internos das duas edições em todas as plataformas.

No macOS, cada edição guarda um checkpoint fora do diretório temporário do DMG:
`app.tar` do app compilado (links simbólicos e permissões preservados), o DMG
assinado antes da notarização, o resultado com ID e status, e os hashes junto
de versão, edição, arquitetura e commit de origem. Esse diretório é publicado
como `checkpoint-macos-<arch>-<edição>` assim que a edição termina, inclusive
quando uma fase posterior falha. O workflow manual **BGDesk - Resume macOS
packaging** baixa esse artefato de um run anterior e executa só uma etapa:
empacotar e assinar, notarizar ou retomar a submissão, anexar o ticket, ou
validar assinatura, ticket, Gatekeeper e o app dentro do DMG. Notarização já
aceita não é reenviada. A validação não instala Rust, Flutter nem vcpkg e não
recompila; o log fica no artefato da execução.

## Salvar as credenciais

O certificado `.p12` não é uma chave SSH. Ele fica num Secret, codificado em
Base64; sua senha fica em outro Secret. O runner decodifica o certificado fora
do checkout, importa em um Keychain temporário e remove os temporários ao fim.
O `.env` local é ignorado pelo Git. Use [.env.example](../.env.example) como
referência de campos; não substitua seu `.env` preenchido por esse exemplo.

O comando abaixo mostra somente os nomes que estão disponíveis para envio:

```sh
python3 scripts/ci/setup-github-secrets.py
```

Com GitHub CLI autenticado e permissão para administrar Secrets:

```sh
python3 scripts/ci/setup-github-secrets.py --checkout-config --apply
```

Os valores vão por stdin ao `gh`, sem aparecer nos argumentos ou no terminal.
O certificado é lido do caminho já definido em `MACOS_P12_FILE`. A chave de
assinatura de updates é lida de `~/.config/bgdesk/update-signing.json`.
O comando pode ser repetido para atualizar Secrets depois de editar o `.env`.

Secrets utilizados:

- `MACOS_P12_BASE64`, `MACOS_P12_PASSWORD`: certificado Developer ID Application
  e sua senha; o script gera o Base64 automaticamente.
- `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_PASSWORD`: Apple ID e **senha específica
  de app** para notarização. O perfil local `MACOS_NOTARY_PROFILE` do Keychain
  não existe nos runners. A verificação `bash scripts/package-macos.sh --check`
  confirma autenticação e certificado antes de compilar.
  A checagem também assina e verifica um executável mínimo para confirmar acesso
  à chave privada. O Keychain temporário entra na lista de busca durante a
  assinatura; a lista original é restaurada ao final, inclusive em caso de erro.
- `ANDROID_SIGNING_KEY`, `ANDROID_ALIAS`, `ANDROID_KEY_STORE_PASSWORD`,
  `ANDROID_KEY_PASSWORD`: keystore existente em Base64, alias e as duas senhas.
  Para validar e enviar somente esses quatro Secrets, execute
  `python3 scripts/ci/setup-github-secrets.py --android-only --apply` com JDK 17
  no PATH. A verificação importa a chave privada temporariamente para confirmar
  as duas senhas. O runner grava keystore e `key.properties` com modo `0600`,
  remove ambos mesmo se o build falhar e não os inclui nos artefatos ou caches.
- `BGDESK_UPDATE_SIGNING_KEY`: conteúdo JSON da chave privada Ed25519 existente.
  O preflight confere se corresponde à chave pública do código.
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`: credenciais S3 do R2, com permissão
  **Object Read & Write**, restritas ao bucket de distribuição.
- `BGDESK_CONFIG_ARCHIVE`: arquivo compactado com `settings.toml`, `certs/ca.crt`,
  `certs/sign.crt` e `certs/sign.key`, exportados do commit exato do submódulo.
  O runner restaura esses quatro arquivos com permissões restritas, depois de
  conferir o commit e os caminhos. A chave raiz da CA, as chaves de servidor e
  os arquivos Android ficam fora desse pacote desktop.

O parâmetro `--checkout-config` faz um checkout temporário do repositório privado
`boagestao/bgdesk-config`, exporta os arquivos e remove esse checkout após o envio.
Sem esse parâmetro, o helper exporta o commit a partir do submódulo local.
O arquivo compactado cabe no limite de 48 KiB de um Secret; esse limite é
verificado antes do envio. Nenhum conteúdo privado é acrescentado ao repositório
público do aplicativo ou a um artefato de download do Actions.

Esse fluxo não precisa de um token adicional para o `bgdesk-config` nem de uma
deploy key, que está bloqueada pela política atual do repositório. Se o commit do
submódulo mudar, execute o comando de configuração novamente para atualizar o
Secret; o preflight recusa um pacote de outro commit.

Como alternativa, o workflow aceita `BGDESK_CONFIG_TOKEN` com **Contents: Read-only**
no repositório privado ou `BGDESK_CONFIG_SSH_KEY` onde a política permitir.
Use `--skip-config-archive` para escolher essa alternativa. O parâmetro opcional
`--register-config-key` registra uma deploy key somente onde isso é permitido.
O token usado localmente pelo `gh` não é copiado automaticamente para o Actions.

## Configuração do R2

O helper aceita os campos que já existem no `.env`:

```dotenv
STORAGE_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com/NOME_DO_BUCKET
STORAGE_ACCESS_KEY=...
STORAGE_SECRET=...
```

Ele extrai Account ID e bucket de `STORAGE_URL`, mapeia as duas credenciais para
os Secrets `R2_*` e salva as variáveis de repositório:

- `R2_ACCOUNT_ID`: ID da conta Cloudflare.
- `R2_BUCKET`: nome do bucket.
- `R2_PUBLIC_ORIGIN`: domínio público HTTPS do bucket; o padrão usado pelo
  helper é `https://download.bgdesk.com`, já usado pelo site. Pode definir esse
  campo explicitamente no `.env`, sem barra final e sem caminho.

O endpoint S3 contém o Account ID e é usado somente para upload autenticado.
O domínio público é usado pelos aplicativos e precisa servir os objetos sem
autenticação, desafio de navegador ou fallback de SPA.

O Actions compila `BGDESK_UPDATE_ORIGIN` com o valor de `R2_PUBLIC_ORIGIN`.
Assim os canais ficam, por exemplo, em
`https://download.bgdesk.com/updates/cliente/latest.json` e
`https://download.bgdesk.com/updates/suporte/latest.json`.
O build local continua usando `https://bgdesk.com` por padrão; para gerar
localmente o mesmo canal do Actions, exporte `BGDESK_UPDATE_ORIGIN` antes do
build. Depois de distribuir aplicativos, preserve esse endereço nas próximas
releases. Mudar de domínio exige manter os canais anteriores acessíveis.

## Como uma versão é publicada

1. Atualize a versão em `Cargo.toml`, `flutter/pubspec.yaml` (preservando ou
   aumentando o número após `+`) e `libs/portable/Cargo.toml`.
2. Faça push na `main`. Todos os builds precisam terminar com sucesso.
3. O job de publicação confere os 28 artefatos internos esperados, seus tamanhos e
   hashes. O manifesto seleciona o pacote Windows nativo para atualização;
   o Inno Setup fica identificado como `inno-exe`, para download inicial.
4. Assina os manifestos das duas edições e envia cada pacote uma única vez para
   a raiz do R2, nos mesmos endereços usados pelos downloads do site. O pacote
   de atualização Windows (`bgdesk-<edição>-update-win64.exe`) é diferente do
   instalador Inno (`bgdesk-<edição>-win64.exe`); ambos são necessários, não são
   cópias do mesmo executável. Win32 usa os sufixos correspondentes `win32`.
5. Verifica os pacotes na raiz e publica somente JSON, assinatura e página de
   download nas pastas `updates/<edição>/v<versão>/`. Não envia uma segunda
   cópia dos pacotes para essas pastas. Atualiza os scripts de instalação Mac
   e, por último, os dois `latest.json` com `no-store`.

O site usa os scripts do bucket para instalar o DMG correto para Intel ou Apple
Silicon. Esses scripts verificam a equipe Apple, a assinatura e o Gatekeeper.
O workflow não sobrescreve o restante do site nem exige publicar uma nova build
React a cada versão. As alterações iniciais do site ainda precisam do deploy
normal do repositório `bgdesk-webpage`.

Os manifestos assinados e a identidade de cada versão publicada são imutáveis;
o histórico de binários fica no GitHub Releases. No R2 os pacotes na raiz são
substituídos pela nova versão, com `no-store`, sem acumular cópias por versão.
Se um push não altera uma versão já publicada,
os builds continuam rodando, mas o envio da release é pulado. Para disponibilizar
uma correção aos usuários, aumente a versão; editar o mesmo `latest.json` não faz
um aplicativo baixar novamente uma versão igual à instalada.

Se apenas a publicação falhar, use **Publish existing packages** para reaproveitar
os mesmos artefatos. Os manifestos usam a data do commit para permitir essa repetição.
Não associe um rebuild diferente à mesma versão: aumente a versão.
Builds que falham não ativam os canais. Jobs são serializados para
evitar uma execução antiga anunciar uma versão depois de outra mais recente.

Os artefatos ficam disponíveis na execução por 14 dias, inclusive nos testes
manuais sem publicação. O download Linux é publicado, mas a instalação automática
interna continua limitada a Windows/macOS, conforme o atualizador existente.
Os APKs são publicados na raiz do R2 como `bgdesk-cliente-universal.apk` e
`bgdesk-suporte-universal.apk`, compartilhados com os downloads do site. Os hashes
assinados ficam em `updates/android/<edição>/v1.5.1/`, sem duplicar APKs nesses
diretórios. Esse canal tem metadados próprios e preserva os metadados desktop já
assinados. A inclusão dos APKs na release estável GitHub também preserva o tag e
os bytes dos assets existentes. Isso não implementa instalação automática no Android.
Windows ARM64 e iOS continuam fora desta matriz de distribuição.

## Validar antes do primeiro push de distribuição

```sh
gh workflow run release.yml --ref main -f platforms=macos -f publish=false
gh workflow run release.yml --ref main -f platforms=windows -f publish=false
gh workflow run release.yml --ref main -f platforms=linux -f publish=false
gh workflow run release.yml --ref main -f platforms=android -f publish=false
```

Esses comandos exigem que o novo workflow e os scripts já tenham sido enviados
ao GitHub. O primeiro push na `main` inicia o fluxo automático; para testar antes,
envie uma branch de preparação e execute o workflow nessa branch com
`publish=false`, depois integre-a à `main`.

Validações locais não substituem a primeira execução em cada runner. Em especial,
Windows e Linux precisam dessa compilação real para confirmar SDKs, dependências
nativas, empacotadores e limites de disco do ambiente remoto. A publicação é
bloqueada até que todos passem.

Referências: [certificados no GitHub Actions](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications),
[runners disponíveis](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[tokens do R2](https://developers.cloudflare.com/r2/api/tokens/),
[domínios públicos do R2](https://developers.cloudflare.com/r2/buckets/public-buckets/).

## Linux: Wayland nos pacotes instaláveis

DEB, RPM e Arch incluem por padrão a captura DRM/KMS (`drm` e `drm-wake`),
para acesso unattended em sessões Wayland, e continuam atendendo sessões X11.
Isso vale para as edições cliente e suporte. Os nomes habituais dos pacotes são
mantidos; não é necessário escolher uma variante `unattended-wayland`.

O serviço `bgdesk.service` executa como root, captura pelo DRM e usa `/dev/uinput`
para teclado, mouse e despertar de telas apagadas por inatividade. A biblioteca
privada é instalada em `/usr/lib/bgdesk/libdrmtap.so.0`, com dependências de DRM,
EGL e GLES declaradas no pacote. O funcionamento depende do suporte da GPU/driver;
isso não cria um monitor virtual e não desperta um computador suspenso.

`build.py` habilita as features automaticamente no Linux. Os builds que compilam
Cargo separadamente devem consultar `--print-features`, inclusive antes de usar
`--skip-cargo`. O empacotamento rejeita um binário antigo sem DRM ou uma biblioteca
de captura incompatível. Para atualizar as imagens Docker existentes, use
`./build.sh linux-x86_64 --rebuild-image` ou a variante `linux-aarch64`.

O AppImage conserva suas receitas e configuração anteriores. Seu payload Rust é
compilado separadamente com `--no-drm`, sem a biblioteca de captura privilegiada.
A preparação do AppImage não altera o DEB distribuído nem o bundle usado por Arch.

## Arch Linux x86_64

Os pacotes `bgdesk-cliente` e `bgdesk-suporte` são alternativas que usam os mesmos
caminhos; instale somente uma edição. O runner Linux x64 usa `makepkg` numa imagem
Arch fixada por digest para empacotar o bundle existente. O pacote declara suas
dependências e inclui a unidade `/usr/lib/systemd/system/bgdesk.service`.

```sh
sudo pacman -U ./bgdesk-cliente-x86_64.pkg.tar.zst
systemctl status bgdesk.service
```

A instalação habilita o serviço no boot e o inicia para acesso unattended.
Em instalação offline, ele inicia no próximo boot. Atualizações reiniciam somente
um serviço que já estava ativo; remoção para e desabilita o serviço. Configuração,
senhas e regras de autenticação existentes são preservadas. O serviço não define
uma senha automaticamente: configure a autenticação de acesso no aplicativo.

Os downloads estáveis são `https://download.bgdesk.com/bgdesk-cliente-x86_64.pkg.tar.zst`
e `https://download.bgdesk.com/bgdesk-suporte-x86_64.pkg.tar.zst`. Ambos entram no
manifesto assinado e na verificação de completude dos 28 arquivos antes de ativar
os feeds. Arch Linux ARM não está incluído neste pacote x86_64.

## Validação individual e Releases imediatas

O seletor manual aceita `linux-x86_64`, `linux-aarch64`, `macos-aarch64`,
`macos-x86_64`, `windows-x86_64` e `windows-x86`, além dos grupos por sistema e `all`.
Cada alvo continua compilando cliente e suporte em sequência na mesma máquina.
Linux x64, Linux ARM, macOS Intel, macOS ARM e Windows x64 já passaram; o deploy
completo 1.5.1 foi validado, incluindo os 22 arquivos e feeds assinados.

`windows-x86` permite validar somente Win32, com `publish=false`. Flutter não
oferece Windows de 32 bits; esse alvo usa a interface Sciter existente, incluindo
a edição cliente com `incoming-only`. O runner usa Rust nightly-2026-09-01 e
`i686-pc-windows-msvc`, dependências `x86-windows-static`, binding Sciter fixado
no commit `674e07d3066ca9a92ced3816203ab6b652629d1e` e DLL fixada por commit e
SHA256. A troca do binding ocorre apenas no checkout descartável Win32 e mantém
todas as outras dependências do lockfile. O alvo isolado não instala Flutter.
Em `all`, o mesmo runner termina x64 cliente/suporte com Flutter e Rust estável,
depois prepara o target i686 com nightly e executa Win32 cliente/suporte.
As saídas e manifests ficam separados por plataforma, arquitetura e edição.

São produzidos `bgdesk-<edição>-win32.exe` (Inno com serviço unattended) e
`bgdesk-<edição>-update-win32.exe` (atualizador nativo), ambos assinados e com
timestamp. A arquitetura PE32, versão do executável e abertura de janela Sciter
são verificadas antes de salvar os artefatos e publicar a pré-release.
Win32 cliente e suporte passaram no run 39428395944, incluindo assinatura,
janela Sciter e conferência dos quatro pacotes. Win32 está integrado à matriz
`all` e à distribuição R2. A versão do aplicativo acompanha o RustDesk upstream
(atualmente 1.5.1); não deve ser incrementada para releases próprias do BGDesk.
A publicação existente da 1.5.1 é preservada pelo bloqueio de imutabilidade. São seis runners,
14 conjuntos de artefatos e 28 pacotes internos. O cache vcpkg é reconciliado
para cada target antes de compilar, sem confiar apenas no header FFmpeg host.

Antes de preparar os compiladores, o preflight consulta as últimas 100 execuções
encerradas de `release.yml` na main. Para cada plataforma/arquitetura, a versão
em `Cargo.toml` do commit original deve ser igual à versão solicitada. Conforme
política do projeto, diferenças de commit não invalidam uma build da mesma versão.
O job daquele alvo precisa ter passado por completo e os artefatos de cliente e
suporte precisam estar disponíveis e não expirados. Um erro em outro alvo ou na
publicação não invalida o alvo aprovado. Windows x64 e Win32 são procurados
separadamente, mas continuam no mesmo runner. Sem fonte aprovada, o alvo compila.
Antes de marcar o alvo como reaproveitável, o preflight baixa os arquivos das duas
edições e verifica os pacotes completos, incluindo hash e tamanho. No Windows,
também exige o conteúdo de um Setup Inno em cada edição: apenas o nome de um
artefato ou um EXE nativo não permite pular a compilação.

Os pacotes reaproveitados são baixados, validados por versão/seletores/SHA256/tamanho
e enviados como artefatos da execução atual com `build-source.json` registrando
commit e run originais. Reaproveitar esses pacotes não cria nem altera releases
ou tags: a publicação original continua como referência, sem duplicar os mesmos
binários em uma nova pré-release.
Se todos os alvos forem reaproveitados, até a geração do bridge é pulada.
A release estável e os feeds já publicados não são substituídos por esse mecanismo.
O job de publicação estável, entretanto, continua obrigatório mesmo quando todos
os pacotes forem reaproveitados e a versão já existir. O marcador de versão R2
controla somente a publicação de novos feeds/R2. No GitHub, a sincronização de
uma versão já publicada confere os 28 pacotes internos e os 24 downloads públicos,
envia os Setups ausentes de cliente/suporte x86/x64 e remove apenas os atualizadores
nativos correspondentes dos assets públicos. Verifica os bytes existentes antes
de qualquer alteração e mantém o tag/commit de destino original. Não reescreve
os feeds ou metadados assinados da versão já anunciada no R2.

Quando uma edição é compilada pela primeira vez, seu instalador é salvo como artefato do Actions
**e** enviado para uma pré-release GitHub da plataforma/arquitetura, com nome
`build-v<versão>-<plataforma>-<arquitetura>-<run>-<tentativa>`. A outra edição
acrescenta seus arquivos à mesma pré-release quando termina. Os nomes são únicos,
com manifests e SHA256SUMS separados por edição; hashes e tamanhos são verificados
antes do envio e arquivos existentes com bytes diferentes nunca são sobrescritos.
Essas pré-releases ficam visíveis em Releases mesmo se outro alvo falhar. Elas
não alteram o feed de atualização automática. Os EXEs nativos de atualização
ficam nos artefatos Actions e na raiz do R2, mas as pré-releases e a release
estável do GitHub expõem somente Setups Windows. Os manifests e checksums
públicos dessas pré-releases listam somente os arquivos expostos.
Após todos os 28 pacotes internos passarem e o R2 terminar, a release estável
`v<versão>` publica 24 arquivos, incluindo quatro Setups Windows e dois APKs universais.

A assinatura Windows informa separadamente exportação do certificado, confiança
na CA temporária, assinatura, timestamp RFC3161 e verificação Authenticode.
Cada comando tem prazo de 30 ou 120 segundos e recebe stdin fechado; falhas
informam a fase sem imprimir senhas. O teste de assinatura de um PE temporário
ocorre antes da compilação, evitando gastar um build inteiro com certificado ou
serviço de timestamp indisponível. Os binários continuam exigindo assinatura e
timestamp válidos.

A CA de assinatura é importada em `LocalMachine/Root` somente na VM Windows
descartável do GitHub, que executa com privilégios administrativos. O store
`CurrentUser/Root` abre uma confirmação CryptoAPI e falha em sessão sem interface
com `UI is not allowed in this operation`. Os limites de tempo e a verificação
de assinatura/timestamp continuam obrigatórios.

## Retomar somente a publicação

Se os seis builds passaram e apenas `publish` falhou, use **BGDesk - Publish
existing packages** (`publish-existing.yml`) e informe `source_run`. O workflow
confere que o run de origem é da `main`, deste repositório, que encerrou e que
todos os seis jobs, incluindo Windows x64+x86 e Android, preflight e bridge passaram.
Baixa os 14 conjuntos de artefatos e exige os mesmos 28 arquivos, com hashes e tamanhos válidos. Não instala
Rust, Flutter ou vcpkg nem recompila. Runs históricos completos anteriores à inclusão
do Android continuam permitindo recuperar somente seus pacotes desktop.

As ferramentas corrigidas de publicação vêm da `main`; versão, commit e data dos
binários continuam sendo os do run de origem. Assim uma tentativa posterior gera
os mesmos manifestos assinados e reaproveita objetos com hashes idênticos no R2.
Uma versão já anunciada só é aceita se os pacotes fornecidos forem idênticos aos
objetos existentes. A release estável aponta para o commit que produziu os builds.

A verificação pública se identifica como `BGDesk-Release/1.0` no `User-Agent`.
Isso evita a recusa do identificador padrão Python pelo Browser Integrity Check
(Cloudflare 1010). As verificações de HTTPS, conteúdo, tamanho e assinatura são
mantidas; respostas 403 continuam sendo falhas de publicação.
