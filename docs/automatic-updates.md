# Atualizações pelo bgdesk.com

O aplicativo consulta por HTTPS, com `GET`, um arquivo estático do site:

| Compilação | Arquivo consultado | Identidade assinada |
| --- | --- | --- |
| Cliente (`incoming-only`) | `https://bgdesk.com/updates/cliente/latest.json` | `bgdesk-cliente` |
| Suporte (sem `incoming-only`) | `https://bgdesk.com/updates/suporte/latest.json` | `bgdesk-suporte` |

O endereço antigo `https://bgdesk.boagestao.net/version/latest`, definido no
submódulo de configuração, deixou de ser usado pelo atualizador deste aplicativo.
Não há mais consulta ao GitHub para descobrir ou baixar atualizações.

O workflow do GitHub Actions pode compilar outro domínio público do mesmo serviço
usando `BGDESK_UPDATE_ORIGIN`, obtido de `R2_PUBLIC_ORIGIN`; no R2, o padrão é
`https://download.bgdesk.com`. Consulte [github-actions.md](github-actions.md)
para publicação automática, Secrets e os endereços efetivamente compilados.

## O que identifica uma nova versão

O `latest.json` aponta para uma release da mesma edição:

```json
{"url":"https://bgdesk.com/updates/suporte/v1.5.1-1/"}
```

O aplicativo compara a versão canônica completa com a compilada em Cargo.
Aceita `MAJOR.MINOR.PATCH` e `MAJOR.MINOR.PATCH-REVISAO`, com revisão numérica
positiva, sem zeros à esquerda, até 65535. A ordem é
`1.5.1 < 1.5.1-1 < 1.5.1-2 < 1.5.1-10 < 1.5.2`.
A pasta aceita prefixo `v` opcional; não usar `latest`, `nightly`, sufixos
alfabéticos, `-0` nem quatro componentes na versão canônica.
`{"url":""}` significa que nenhuma atualização está publicada.

**A migração inicial para 1.5.1-1 é manual.** O atualizador anterior rejeita URLs
com sufixo. Depois dessa instalação, as revisões seguintes são detectadas
automaticamente. Mudar apenas o contador Flutter não publica uma nova revisão.
Consulte [o guia de revisões e integração upstream](unified-session-tabs.md)
para os formatos nativos e os testes de migração.

No preparo manual legado, dentro da pasta da release ficam os instaladores, `bgdesk-update.json`,
`bgdesk-update.json.sig` e uma página de download `index.html`. O manifesto informa
versão, edição, sistema, arquitetura, formato, URL, tamanho e SHA-256 de cada
instalador. Sua assinatura Ed25519 é verificada antes de confiar nesses dados;
o instalador também tem tamanho e hash verificados antes da instalação.

## Chave de assinatura

A chave desta instalação foi criada em:

```text
~/.config/bgdesk/update-signing.json
```

Ela tem permissão `0600`, contém a chave privada e **não deve ser enviada ao site
nem incluída no Git**. Faça backup seguro: novas releases precisam ser assinadas
com essa mesma chave para que os aplicativos já distribuídos as aceitem.
A chave pública correspondente está em `src/update_metadata.rs`.

Em outra máquina de publicação, restaure esse arquivo e passe `--key-file` se
usar outro caminho. O comando verifica se a chave privada corresponde à chave
pública compilada no aplicativo. Não execute `init-key` novamente para releases
normais; ele recusa substituir uma chave já configurada. Rotação exige planejar
uma versão intermediária que confie na nova chave antes de usá-la.

## Preparar uma release

No repositório do aplicativo, prepare uma virtualenv de publicação (Python 3.10+):

```sh
python3 -m venv .tools/update-signing
.tools/update-signing/bin/pip install 'cryptography==50.0.0'
```

Compile os instaladores com a nova versão. No macOS, use os DMGs finais assinados
e notarizados, produzidos pelo fluxo descrito em [macos-signing.md](macos-signing.md).
Não publique o DMG `-local`. No Windows, use os instaladores finais do build.
Inclua apenas binários da edição indicada; o script não inspeciona o código interno
do instalador para determinar se ele é cliente ou suporte.

Exemplo para suporte, substituindo os caminhos pelos arquivos reais:

```sh
.tools/update-signing/bin/python res/update/website_release.py prepare \
  --edition suporte \
  --version 1.5.2 \
  --site-public ../bgdesk-webpage/public \
  --artifact macos aarch64 dmg build/macOS-aarch64-suporte/bgdesk-suporte-1.5.2-aarch64.dmg \
  --artifact macos x86_64 dmg /caminho/bgdesk-suporte-1.5.2-x86_64.dmg \
  --artifact windows x86_64 exe /caminho/bgdesk-suporte-1.5.2-win64.exe
```

Execute novamente com `--edition cliente` e os instaladores cliente para publicar
essa edição. Pode publicar as edições em versões diferentes. Cada combinação de
sistema, arquitetura e formato deve ocorrer uma única vez. Arquiteturas aceitas:
`aarch64` e `x86_64` no macOS; `x86`, `x86_64` e `aarch64` no Windows.
Linux aceita `deb`, `rpm` e `AppImage` em `x86_64`/`aarch64` para download manual.
O formato Windows `inno-exe` oferece o instalador inicial sem usá-lo como
atualização; o formato `exe` deve conter o pacote nativo que aceita `--update`. Para instalações
MSI, inclua também `--artifact windows x86_64 msi /caminho/instalador.msi`.
Inclua todos os sistemas/arquiteturas que pretende atualizar: uma combinação
ausente é recusada pelo cliente, sem tentar instalar um binário incompatível.

O comando copia os instaladores, calcula hashes, assina e verifica tudo, cria
`public/updates/<edição>/v<versão>/` e só depois troca o `latest.json` local.
Releases existentes não são sobrescritas; para corrigir uma versão já publicada,
gere uma versão maior. O script não faz upload nem deploy.

## Publicar no servidor

1. Envie a pasta completa `updates/<edição>/v<versão>/` para a raiz pública do
   bgdesk.com. Preserve releases anteriores.
2. Verifique que os instaladores e os dois arquivos de assinatura respondem com
   HTTP 200 e os bytes originais. Não podem cair no HTML de fallback da SPA.
3. Só então envie `updates/<edição>/latest.json`. Essa troca anuncia a versão.

O build do site (`bun run prod`) copia `public/updates` para `dist/updates`.
Os instaladores ficam ignorados pelo Git, mas precisam estar no diretório público
da máquina que faz o build ou ser enviados diretamente ao servidor. Em deploys
que substituem toda a raiz, restaure/preserve a árvore de releases para não apagar
downloads em andamento ou releases antigas.

Sirva `latest.json` com `Content-Type: application/json` e
`Cache-Control: no-store, max-age=0`; use HTTPS com certificado válido. O arquivo
`public/_headers` configura isso em hosts compatíveis com esse formato
([documentação do Netlify](https://docs.netlify.com/manage/routing/headers/)). Em Nginx,
adapte ao `server` existente (a raiz já deve apontar para `dist`):

```nginx
location ~ ^/updates/(cliente|suporte)/latest\.json$ {
    default_type application/json;
    add_header Cache-Control "no-store, max-age=0" always;
    try_files $uri =404;
}
location /updates/ {
    index index.html;
    try_files $uri $uri/ =404;
}
```

Não reescreva esses arquivos para `index.html` da aplicação React. Não regenere,
reformate nem altere o manifesto após assiná-lo; a assinatura cobre seus bytes.
Para pausar anúncios, publique `{"url":""}` no `latest.json` da edição.

## Comportamento no aplicativo

O serviço verifica após cerca de 30 segundos e depois a cada 24 horas. Falhas são
repetidas após cerca de 30 minutos. A opção de atualização automática precisa
estar habilitada; o serviço evita instalar durante sessões remotas ativas.
Windows instalado e macOS com serviço instalado usam a instalação automática
existente. A interface também oferece o fluxo manual de atualização verificada.
Linux e dispositivos móveis continuam dependendo dos downloads/gerenciadores de
pacotes; este trabalho não acrescenta instalação automática nessas plataformas.
Clientes personalizados continuam fora do canal público.

As instalações já distribuídas precisam receber primeiro um build com este novo
endereço e a chave pública. Publicar o site sozinho não altera o atualizador que
já está instalado nas máquinas. Como a lista de chaves anterior estava vazia,
essa primeira migração deve ser feita pelo instalador, manualmente ou por sua
ferramenta de distribuição.

## Validação local

```sh
.tools/update-signing/bin/python -m unittest discover -s res/update -p 'test_*metadata*.py'
.tools/update-signing/bin/python -m unittest discover -s res/update -p 'test_website_release.py'
cargo test --release --lib update_
cargo test --release --lib --features incoming-only update_
```

## Política do canal público BGDesk

O canal público é uma política distinta de `is_custom_client()`. Essa função
legada compara o nome com RustDesk e continua sendo usada em personalização,
preferências, staging do Windows e outros fluxos. Ela não deve decidir se uma
distribuição pública BGDesk consulta as atualizações.

`common::uses_public_update_channel()` permite o canal somente com o nome exato
`BGDesk` e sem configuração personalizada assinada carregada. A configuração
personalizada é marcada após verificar assinatura e JSON, mesmo quando mantém o
nome BGDesk. Uma vez personalizada, a instância não entra no canal público.
Configurar um servidor de conexão ou registrar uma licença BGDesk não transforma
a distribuição pública em um cliente personalizado.

A mesma política controla a consulta de versões, os avisos e ajustes Flutter,
o cartão Sciter, o serviço macOS e a resolução de artefatos do feed público.
O Windows já consultava diretamente o feed em segundo plano; a correção também
protege esse caminho contra atualização de clientes personalizados pelo canal
público. Os mecanismos próprios de personalização e licenciamento não mudam.

`enable-check-update` controla a consulta e o aviso na abertura. A instalação
automática exige `allow-auto-update` efetivamente habilitado (`Y`), além de
instalação/serviço compatível. A política pública não força essas preferências.
No Linux o atualizador não instala pacotes automaticamente; use os downloads
ou o gestor de pacotes. Cliente e suporte usam feeds e identidades de pacote
separados; arquitetura e formato são selecionados no manifesto assinado.

### Migração e comprovação de upgrade

Publicar os pacotes e validar R2, assinatura Ed25519, SHA256 e tamanho comprova
a distribuição. Isso não comprova que uma versão instalada consulta o feed e
conclui a troca do aplicativo.

Versões anteriores que pulam a consulta por classificarem BGDesk como custom
precisam receber a primeira versão corrigida por instalação manual ou por uma
ferramenta de distribuição administrada. Um feed novo não corrige esse bloqueio
no binário antigo. No Windows o caminho automático em segundo plano não tinha
esse mesmo bloqueio, mas ainda depende da opção e do serviço efetivos.

Antes de considerar a atualização automática validada, executar em instalações
descartáveis das duas edições: instalar uma versão com a política corrigida,
habilitar as opções desejadas, disponibilizar uma versão superior assinada e
confirmar consulta, seleção da edição/arquitetura, download verificado, troca,
reinício do serviço e versão final. Repetir com uma conexão ativa para confirmar
adiamento e com configuração personalizada para confirmar isolamento. A migração
da versão antiga deve ser testada separadamente. Registrar versões de origem e
destino e os logs; testes de política não substituem esse upgrade real.

## Um pacote por alvo na raiz do R2

A publicação Actions usa `website_release.py prepare --root-artifacts`.
Os manifestos continuam versionados e assinados, mas a URL de cada pacote aponta
para o arquivo da raiz já usado pelo site, por exemplo
`https://download.bgdesk.com/bgdesk-cliente-aarch64.dmg` ou
`https://download.bgdesk.com/bgdesk-suporte-update-win64.exe`. Não são criadas
cópias de instaladores dentro de `updates/<edição>/v<versão>/` nas novas publicações.
O histórico de binários continua no GitHub Releases.

O aplicativo aceita a raiz do mesmo domínio HTTPS ou os caminhos antigos de
release. Exige manifesto assinado da própria edição, versão, arquitetura,
formato, tamanho e SHA-256; não baixa um arquivo arbitrário só porque está na raiz.
Os pacotes da raiz usam `no-store`, enquanto os metadados assinados por versão
são imutáveis. Durante uma substituição, um manifesto anterior pode encontrar
bytes da versão seguinte: a diferença de hash impede a instalação e a tentativa
seguinte deve consultar o feed atualizado. A publicação só anuncia o novo feed
depois de conferir todos os pacotes e metadados.

Os binários 1.5.1 ainda esperam URLs dentro da pasta de release; mesmo o caminho
automático Windows que já consultava o feed precisa receber primeiro um build
compatível com URLs da raiz por instalação manual ou distribuição administrada.
Não reescrever os manifestos assinados da 1.5.1 para simular compatibilidade.
As cópias antigas dessa versão ficam preservadas durante a transição; limpeza
remota deve ocorrer somente depois de validar o novo deploy e a migração.
