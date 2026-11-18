# Hotfix do upload do GTA Studio

## Problema corrigido

No Docker Desktop, `/studio/temp/uploads/` e `/studio/assets/uploads/` podem ser volumes/mounts diferentes. O `os.replace()` anterior lançava `[Errno 18] Invalid cross-device link` na conclusão do upload, inclusive em 99%.

`backend/uploads.py` agora usa cópia em blocos de 4 MiB, staging no mesmo sistema de arquivos do destino, `fsync`, verificação do tamanho e `os.replace()` apenas entre caminhos no destino. Mantém o `.part` até conclusão. Se o arquivo já estiver no destino, somente considera concluído se o SHA-256 coincidir. Evita sobrescrever conteúdo diferente.

O endpoint de criação de sessão recupera sessões `FAILED` antigas quando ainda há `.part` local correspondente ao fingerprint, permitindo clicar **Retomar** com o mesmo arquivo selecionado no navegador sem retransmitir tudo.

## Instalação

1. Faça backup de `Clips-Virais`.
2. Aplique o ZIP na raiz do projeto, substituindo `backend/uploads.py`.
3. Preserve `.env`, `models`, `assets`, `temp`, `data` e os volumes Docker.
4. Execute: `docker compose up -d --build api worker web`.
5. Na aba **Upload de mídia**, clique **Retomar** no mesmo arquivo.
6. Verifique `assets/uploads/video` e `docker compose logs --tail=80 api worker`.

**Não execute `docker compose down -v` nem apague `/temp/uploads` antes da retomada.**

## Limites da validação

A cópia segura, a idempotência e a prevenção de sobrescrita foram testadas localmente. Não houve acesso ao Docker Windows do usuário, portanto a retomada no ambiente real ainda precisa ser confirmada.

## Evolução v6 especificada no anexo

A versão mais ampla solicitada (sexto agente Redator, elenco com vozes, watcher de assets, gameplay e música obrigatórios, Avaliador + Pessoa em paralelo, refação cirúrgica por critério e pré-visualização) **não faz parte deste hotfix** e requer integração e testes de regressão adicionais. Não apresente esse hotfix como implementação dessas funções.
