# GTA Studio — Reset controlado e avaliador v3

## Instalação sem apagar dados

1. Faça cópia da pasta do projeto e preserve `.env`, `models/` e volumes Docker.
2. Substitua os arquivos do patch na raiz do projeto.
3. Execute `docker compose up -d --build api web worker`.
4. Confira `docker compose exec -T api python -m backend.reset_productions counts`.

A migração do banco é incremental e não deleta produções. Em bancos antigos, a migração tenta recuperar renders `videos/final/<id>.mp4` de reprovadas e seus antigos `review-*.json`. Se o arquivo nunca foi gerado, não é possível criar uma prévia retroativamente.

## Etapa 1 — BACKUP OBRIGATÓRIO, sem exclusão

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\backup-producoes.ps1
```

O script **para o worker**, exporta banco SQLite completo, arquivos de produção, `affected-tables.json`, `secrets.key` (quando existente) e manifesto. Copia tudo para `backups/production-reset/<ID>` na sua máquina. **Não envia esses arquivos a terceiros**, pois o backup contém configurações, chaves criptografadas e a chave de criptografia.

**Pare aqui e confirme explicitamente o reset depois de conferir backup ID e contagens.**

## Etapa 1B — Reset destrutivo: executar SOMENTE após confirmação

A rotina de reset está disponível, mas é protegida por ID do backup e pela frase `CONFIRMO_RESET_TOTAL`.

```powershell
# SOMENTE depois de ter confirmado que deseja apagar TODO o histórico de produção.
docker compose exec -T api python -m backend.reset_productions reset --backup-id <BACKUP_ID> --confirm CONFIRMO_RESET_TOTAL
docker compose exec -T api python -m backend.reset_productions counts
docker compose up -d worker
```

O reset zera `videos`, `video_attempts`, `jobs`, `events`, `publications`, `metrics`, `notifications`, `usage`, `cache`, chaves legadas `kv.daily:*` e mídia/briefings de produção; preserva `settings`, `secret:*`, fontes, perfis e contas OmniRoute. Redis externo não é limpo: o limite diário pertence ao SQLite do GTA Studio, e executar FLUSHDB na instância compartilhada destruiria caches/contas de outro serviço.

Em caso de falha de cópia, **não execute** o reset. Salve o backup fora da pasta do projeto.

## Onde estava o limite diário

Antes: `backend/pipeline.py::create_video`, `kv['daily:'+db.today()]`, incrementado no início de cada trabalho, sem liberação em falha, reprovação ou testes. Agora: `backend/core.py::production_usage()` + `local_day_bounds()`, consultando registros `videos` com janela de data de `America/Sao_Paulo`. Testes e estados `FAILED`, `REJECTED`, `AWAITING_MANUAL_DECISION`, `DISCARDED` não entram. Produções reais ativas reservam **um** slot cada; aprovadas contam na data de aprovação; revisões do mesmo vídeo não incrementam slots.

## Etapa 2 — Motivos de reprovação

Video Studio → selecione produção → Histórico de tentativas. Avaliação JSON integral fica em `video_attempts.details` e `handoff/<id>/review-<n>.json`. Cada tentativa mostra `reason_full`, `corrections`, `criteria` e `render_error` sem truncamento.

## Etapa 3 — Critérios editáveis

Configurações → **Critérios de avaliação** permite habilitar/desabilitar e alterar peso e nota mínima de cada critério. Configurações → Nota de aprovação define a média ponderada mínima. Regras determinísticas de direitos de uso e integridade técnica **continuam obrigatórias**. A rubric inclui 12 critérios (gancho, narrativa, áudio, legendas, cortes, ritmo, formato, duração, briefing, originalidade, exatidão, direitos/créditos). Ausência de evidência visual independente é uma limitação para a revisão humana, não prova automática de informação falsa. A expressão “Fair Use” por si só não é justificativa de rejeição nem autorização de reutilização.

## Etapa 4 — Refazer e decidir

Configurações → Tentativas máximas (padrão 5). A cada reprovação, Escritor recebe todas as correções, Editor renderiza outra versão, Avaliador analisa; após o máximo o estado vira `AWAITING_MANUAL_DECISION`. Ações `Aprovar manualmente` e `Reprovar / Descartar` aparecem em Video Studio. Aprovar exige um arquivo renderizado válido e direitos documentados; se ainda não houver render numa produção ativa, registra solicitação para aprovação após a renderização. Registrar ator `local_operator` e timestamp em `videos`. Não há publicação automática.

## Etapa 5 — Pré-visualização

Cada `videos/final/<id>/attempt-01.mp4` etc. é salvo **antes** da avaliação; `videos.final_path` aponta para a versão mais recente disponível. A API `GET /api/videos/<id>/attempts` retorna as avaliações, `GET /api/files/<id>?attempt=N` permite ver/download de cada versão. Renders permanecem armazenados para revisão até reset explícito. Quando não há arquivo, a tela exibe o erro real de renderização e não inventa uma prévia.

## Validação local e limites

Executar:

```powershell
docker compose up -d --build api worker web
docker compose exec -T api python -m backend.reset_productions counts
docker compose exec -T api python -m backend.doctor
# No painel: Testar pipeline -> selecionar vídeo -> notas -> vídeo -> decisão manual
```

As APIs/SQL e a montagem de vídeo sintético são cobertas por testes locais. É necessário homologar os containers, as permissões de arquivos Piper e as chamadas reais de IA no seu ambiente. O teste de pipeline usa mídia sintética e não publica em redes sociais.
