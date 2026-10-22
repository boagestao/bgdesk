# Instruções para agentes

## Versão do aplicativo

- A base do BGDesk acompanha o RustDesk upstream: atualmente **1.5.1**. Por instrução explícita do usuário, revisões funcionais BGDesk usam sufixo numérico: **1.5.1-1**, depois `1.5.1-2`, sem mudar a base.
- Não incremente a versão apenas para empacotamento, inclusão de plataformas ou nova tentativa de publicação. Mudanças funcionais podem incrementar a revisão numérica autorizada; a base só muda ao sincronizar o RustDesk, ou por instrução explícita do usuário.
- Mantenha `Cargo.toml`, `flutter/pubspec.yaml`, `libs/portable/Cargo.toml` e os respectivos `Cargo.lock` coerentes. O estado atual do Flutter é `1.5.1-1+69`.
- Diferencie versão do aplicativo de identificação de build/publicação (commit, run e tentativa). Não use uma versão fictícia do aplicativo para resolver colisões de artefatos. Não sobrescreva silenciosamente releases ou metadados assinados existentes com bytes diferentes.

## Reaproveitamento de builds

- Por pedido explícito do usuário, a decisão de reutilizar uma build aprovada é pela **versão do aplicativo e alvo (plataforma/arquitetura)**, sem invalidar por diferenças de commit ou arquivos. Mudanças funcionais devem incrementar a revisão BGDesk; compare a versão completa, incluindo sufixo, para reaproveitamento.
- Exija job completo aprovado no `release.yml` da main deste repositório, todas as edições distribuídas no alvo e artefatos Actions não expirados (Windows x86: somente cliente; demais alvos: cliente e suporte). Antes de decidir pular a compilação, baixe e valide os arquivos reais de cada edição exigida: versão, seletores, hashes e tamanhos. No Windows, cada edição exigida precisa conter um Setup Inno; o nome do artefato ou um EXE do app não basta.
- Registre e preserve o commit/run de origem dos binários reaproveitados. Um erro apenas no empacotamento/CI não exige reconstruir os outros alvos aprovados da mesma versão.

## Workflows e publicação

- Enquanto qualquer execução enviada estiver ativa ou pendente, somente consulte status e logs resumidos; não edite, faça commit/push, cancele, instale o aplicativo nem dispare outra execução. Espere o workflow inteiro encerrar antes de reunir falhas e enviar um único lote corrigido e testado.
- Não duplique dispatch quando o push já dispara o workflow. Não cancele execuções sem instrução do usuário.
- Nas releases públicas Windows publique somente os Setups Inno cliente x86, cliente x64 e suporte x64. Não compilar nem publicar novos pacotes de suporte x86. Preserve os pacotes nativos de atualização nos artefatos internos e no R2 para o aplicativo.
- Reaproveitar builds NÃO permite pular a publicação estável. Mesmo com a versão já publicada, confira e complete os Setups de cliente x86/x64 e suporte x64, preservando releases históricas existentes. Preserve o tag e os bytes existentes; envie os pacotes ausentes e remova apenas os atualizadores nativos já identificados e verificados dos downloads públicos Windows. A imutabilidade dos metadados R2 continua separada dessa sincronização GitHub.
- No R2, os pacotes devem ficar uma única vez na raiz, compartilhados pelo site e atualizador; diretórios de versão contêm somente metadados. Preserve validação de assinatura, hashes e tamanho.
- Preserve alterações locais e nunca imprima `.env`, credenciais ou certificados privados.

## Abas e sincronização upstream

- Antes de alterar sessões, entrada, atualizador ou integrar o RustDesk, leia [docs/unified-session-tabs.md](docs/unified-session-tabs.md) e `UPSTREAM.md`.
- Sair de uma aba remota libera toda a captura antes de selecionar qualquer outra aba; callbacks atrasados não podem reativá-la.
- Todos os tipos de sessão do suporte Flutter ficam no host principal. Fechar a janela principal confirma se houver várias sessões, oculta a janela e só então encerra as conexões. Preservar persistência/clipboard do terminal e namespaces de câmera/remoto.
- A primeira migração para revisões é manual. Preserve o comparador específico do atualizador, as assinaturas e os mapeamentos dos pacotes nativos.
