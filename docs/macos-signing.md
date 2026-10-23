# Assinatura e distribuição no macOS

`./build.sh mac` (e `./build.sh cliente mac`) gera uma distribuição assinada com
Developer ID Application, notarizada pela Apple e validada pelo Gatekeeper.
O build verifica as credenciais antes de compilar. Se faltar certificado,
credencial ou aprovação da Apple, ele falha sem gerar um novo DMG de distribuição.

A saída é `bgdesk-suporte-darwin.dmg` (ou `bgdesk-cliente-darwin.dmg`) em
`build/macOS-<arch>-<modo>/`. O DMG monta com o ícone de volume do BGDesk
(`res/macos-dmg/volume-icon.icns`) e abre uma janela do Finder com a arte
de arrastar o app para Aplicativos. Esse é o arquivo para disponibilizar
no site.
Os scripts `installers/install.sh` e `installers/install-client.sh` baixam esses
DMGs de `https://boagestao.com.br/bgdesk/`, validam a equipe e o Gatekeeper da
imagem e do app e só então copiam o app para Aplicativos.

## Configuração da conta Apple

1. Na conta participante do Apple Developer Program, crie um certificado
   **Developer ID Application** da equipe `3Z7C3Q7NMT`. No Xcode, use
   Settings → Accounts → sua conta → Manage Certificates → + → Developer ID
   Application. Também é possível criar pelo portal Apple Developer. A Apple
   exige o papel Account Holder para criar esse certificado.
2. Deixe o `.p12` onde ele já está. O build só lê esse arquivo; não copia
   e não move. Na raiz do repositório, o `.env` (ignorado pelo Git) guarda
   o caminho do arquivo e a senha:

   ```sh
   MACOS_P12_FILE="/caminho/DeveloperId.p12"
   MACOS_P12_PASSWORD="senha-do-p12"
   MACOS_NOTARY_PROFILE="dev"
   ```

   `Apple Development` e `Apple Distribution` não substituem **Developer ID
   Application**. Uma variável já definida no ambiente tem prioridade sobre o `.env`.

3. Crie uma senha específica de app em sua conta Apple e armazene as credenciais
   de notarização no Keychain, ou grave no mesmo `.env` as variáveis
   `MACOS_NOTARY_APPLE_ID` e `MACOS_NOTARY_PASSWORD`. O comando do Keychain
   solicita a senha de forma interativa:

   ```sh
   xcrun notarytool store-credentials dev \
     --apple-id belizariogr@gmail.com \
     --team-id 3Z7C3Q7NMT
   ```

   O primeiro argumento é o nome do perfil. Ele tem de ser o mesmo valor de
   `MACOS_NOTARY_PROFILE` no `.env`. O padrão, se a variável não existir, é
   `bgdesk-notary`.

   Também é possível usar uma chave da API App Store Connect com
   `notarytool store-credentials --key ... --key-id ... --issuer ...`.
   Não commite o `.env`, senhas, chaves privadas nem arquivos `.p12`.

4. Verifique a configuração e compile:

   ```sh
   bash scripts/package-macos.sh --check
   ./build.sh mac
   # Ou a versão cliente:
   ./build.sh cliente mac
   ```

Variáveis no `.env` ou no ambiente:

- `MACOS_P12_FILE`: caminho do `.p12`. O arquivo permanece nesse caminho.
- `MACOS_P12_PASSWORD`: senha desse `.p12`.
- `MACOS_CODESIGN_IDENTITY`: nome exato ou SHA-1 da identidade; obrigatório se
  houver mais de um certificado válido correspondente.
- `MACOS_TEAM_ID`: equipe esperada (padrão `3Z7C3Q7NMT`).
- `MACOS_NOTARY_PROFILE`: perfil do `notarytool` (padrão `bgdesk-notary`).
- `MACOS_NOTARY_KEYCHAIN`: Keychain que contém esse perfil, caso não seja o padrão.
- `MACOS_NOTARY_APPLE_ID` e `MACOS_NOTARY_PASSWORD`: alternativa ao perfil do Keychain.

## Ordem de empacotamento e verificações

O Flutter compila sem assinatura final. O build inclui o executável `service`
e o arquivo `flutter-build-stamp.txt` antes de assinar. Em seguida, assina os
binários e frameworks de dentro para fora, com Hardened Runtime, timestamp
seguro e os entitlements de Release, sem `get-task-allow`.

O script verifica a assinatura e a equipe, copia o app com `ditto` preservando
os links simbólicos dos frameworks, acrescenta o atalho para Aplicativos, o
ícone de volume e o fundo de instalação, posiciona os ícones no Finder e
converte a imagem HFS+ para UDZO somente leitura. Em seguida, assina o
DMG com Developer ID Application e timestamp seguro, envia essa imagem à Apple,
exige status `Accepted` e anexa o ticket ao DMG (`stapler`). A notarização do
contêiner também abrange o app dentro dele.

Depois do status `Accepted`, fora do GitHub Actions, `stapler staple` e
`validate` repetem erros 68 até cinco vezes, com intervalos de 5, 10, 20 e 40
segundos, sem reenviar a notarização. No runner do GitHub essa repetição não
resolve: a conexão com `api.apple-cloudkit.com` cai em todas as tentativas
(`NSURLError -1005`). O script desliga o IPv6 e, se o `stapler` ainda sair com
68, busca o mesmo ticket com `rcodesign`, que não usa o CFNetwork. Erros de
ticket inválido/revogado ou de gravação em disco encerram na hora e preservam
o arquivo de saída anterior.

O script verifica a assinatura, o ticket e o Gatekeeper da imagem final, monta
o DMG somente para leitura e valida a assinatura e o Gatekeeper do app incluído.
Somente após essas verificações desmonta a imagem e substitui o arquivo de saída.
Não é gerado ZIP.

O resultado da notarização fica ao lado do DMG, em `*.notary-result.json`.
Em caso de rejeição, o script também tenta salvar `*.notary-log.json`.
No GitHub Actions, os mesmos dados ficam no checkpoint da edição, publicado
mesmo se o stapler ou o Gatekeeper falharem depois. Uma execução manual pode
retomar só a etapa que falta, e uma notarização `Accepted` é reutilizada em
vez de enviar o DMG outra vez.
Se o tempo de espera de 30 minutos expirar, a Apple pode continuar processando;
use o ID registrado no resultado com `xcrun notarytool info` ou `wait` antes de
enviar novamente.

Não altere o conteúdo de `BGDesk.app` depois da assinatura. Para empacotar um
app já montado, sem recompilar:

```sh
bash scripts/package-macos.sh /caminho/BGDesk.app /caminho/bgdesk-suporte-darwin.dmg
```

Para conferir o DMG de distribuição:

```sh
codesign --verify --strict --verbose=2 /caminho/bgdesk-suporte-darwin.dmg
xcrun stapler validate /caminho/bgdesk-suporte-darwin.dmg
spctl --assess --type open --context context:primary-signature --verbose=4 /caminho/bgdesk-suporte-darwin.dmg
```

## Builds para desenvolvimento

`./build.sh mac --macos-local` usa Apple Development, não envia o app para a
Apple e gera `bgdesk-suporte-darwin-local.dmg`. Para testes ad hoc sem certificado:

```sh
MACOS_CODESIGN_IDENTITY=- ./build.sh mac --macos-local
```

Esses DMGs locais não atendem à distribuição via Gatekeeper em outros Macs.

Os testes de regressão rodam com `python3 scripts/test_macos_packaging.py` no
macOS. Eles verificam assinatura ad hoc, montagem e conteúdo do DMG com
ferramentas reais; as respostas de notarização e Gatekeeper são simuladas para
testar as condições de publicação.
Não substituem a validação final com certificado Developer ID e a Apple.

## GitHub Actions

O fluxo de distribuição é `release.yml`, que chama o mesmo `build.sh mac` ou
`build.sh cliente mac` validado localmente. Usa `MACOS_P12_BASE64`,
`MACOS_P12_PASSWORD`, `MACOS_NOTARY_APPLE_ID` e `MACOS_NOTARY_PASSWORD` dos GitHub
Secrets. A identidade e a equipe podem ser configuradas por Secrets opcionais.
O `.p12` é decodificado no diretório temporário do runner; o empacotador cria e
remove seu Keychain temporário. O perfil local do Keychain não é transferido.

Para salvar as credenciais do `.env` sem imprimir valores:

```sh
python3 scripts/ci/setup-github-secrets.py --apply
```

O [guia do GitHub Actions](github-actions.md) detalha a configuração, o acesso ao
submódulo privado e a publicação dos DMGs e manifestos assinados no Cloudflare R2.
O workflow legado `flutter-build.yml` não é usado pelo novo fluxo da `main`.

Referências: [Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/),
[Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution),
[Customizing the notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).
Veja também [Packaging Mac software for distribution](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution).
