# Instruções para agentes

## Versão do aplicativo

- A versão do BGDesk deve acompanhar a versão do RustDesk upstream que esta árvore representa: atualmente **1.5.1**.
- Não faça version bump próprio do BGDesk para empacotamento, correções, inclusão de plataformas ou publicação. Só altere a versão ao sincronizar a base com uma nova versão do RustDesk, ou por instrução explícita do usuário.
- Mantenha `Cargo.toml`, `flutter/pubspec.yaml`, `libs/portable/Cargo.toml` e os respectivos `Cargo.lock` coerentes. O estado atual do Flutter é `1.5.1+68`.
- Diferencie versão do aplicativo de identificação de build/publicação (commit, run e tentativa). Não use uma versão fictícia do aplicativo para resolver colisões de artefatos. Não sobrescreva silenciosamente releases ou metadados assinados existentes com bytes diferentes.

## Reaproveitamento de builds

- Por pedido explícito do usuário, a decisão de reutilizar uma build aprovada é pela **versão do aplicativo e alvo (plataforma/arquitetura)**, sem invalidar por diferenças de commit ou arquivos. Mudanças funcionais devem vir acompanhadas da mudança de versão da base RustDesk.
- Exija job completo aprovado no `release.yml` da main deste repositório, ambas as edições e artefatos Actions não expirados. Antes de decidir pular a compilação, baixe e valide os arquivos reais de ambas as edições: versão, seletores, hashes e tamanhos. No Windows, ambas precisam conter um Setup Inno; o nome do artefato ou um EXE do app não basta.
- Registre e preserve o commit/run de origem dos binários reaproveitados. Um erro apenas no empacotamento/CI não exige reconstruir os outros alvos aprovados da mesma versão.

## Workflows e publicação

- Enquanto qualquer execução enviada estiver ativa ou pendente, somente consulte status e logs resumidos; não edite, faça commit/push, cancele, instale o aplicativo nem dispare outra execução. Espere o workflow inteiro encerrar antes de reunir falhas e enviar um único lote corrigido e testado.
- Não duplique dispatch quando o push já dispara o workflow. Não cancele execuções sem instrução do usuário.
- Nas releases públicas Windows publique somente os Setups Inno x86/x64. Preserve os pacotes nativos de atualização nos artefatos internos e no R2 para o aplicativo.
- Reaproveitar builds NÃO permite pular a publicação estável. Mesmo com a versão já publicada, confira e complete os Setups de cliente e suporte nas duas arquiteturas. Preserve o tag e os bytes existentes; envie os pacotes ausentes e remova apenas os atualizadores nativos já identificados e verificados dos downloads públicos Windows. A imutabilidade dos metadados R2 continua separada dessa sincronização GitHub.
- No R2, os pacotes devem ficar uma única vez na raiz, compartilhados pelo site e atualizador; diretórios de versão contêm somente metadados. Preserve validação de assinatura, hashes e tamanho.
- Preserve alterações locais e nunca imprima `.env`, credenciais ou certificados privados.
