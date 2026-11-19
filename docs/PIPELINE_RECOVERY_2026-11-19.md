# Recuperação do pipeline — 19/11/2026

## Problemas corrigidos
1. A antiga tolerância de 15s no Redator fazia um áudio real de 54,97s ser aceito sem correção apesar do alvo 38–40s. Agora somente o FFprobe/TTS real determina aprovação e reescritas devem avançar em direção à meta de palavras.
2. Respostas OmniRoute HTTP 200 com JSON quebrado, vazio ou sem campos obrigatórios passam por nova tentativa, com fallback de modelo quando configurado. Erros passam a registrar as causas resumidas.
3. O polimento opcional do Redator preserva o texto do Escritor diante de falha do serviço. O TTS continua obrigatório; sem áudio válido, não há aprovação.
4. Erros de preflight e integração são propagados ao worker, que aplica backoff e até cinco tentativas para jobs do pipeline. Outros tipos de job mantêm limite de três. Depois de esgotar, a produção entra em PIPELINE_ERROR para retomada manual, sem virar REJECTED.
5. O script validado em handoff/script.json é reaproveitado nos retries técnicos, quando compatível com template/duração; artefatos e histórico permanecem.
6. Fallback local apenas remove frases estritamente duplicadas; não remove fatos, artigos/preposições ou funde cenas para simular duração.

## Verificação
64 testes direcionados passaram na cópia local. A suíte ampliada obteve 136 aprovações e uma falha de ambiente em test_feed_reference_only_and_production por feedparser ausente no ambiente de testes (a dependência consta no requirements.txt). Não foi possível validar o TTS real e OmniRoute em Docker local neste ambiente. As correções devem ser homologadas após o rebuild.

## Atualização (PowerShell no projeto)
```powershell
git pull origin main
docker compose build --no-cache api worker
docker compose up -d --force-recreate api worker
docker compose ps
docker compose logs -f worker api
```

## Retomar produções antigas bloqueadas por TTS/Redator (depois da atualização)
```powershell
docker compose exec worker python -m backend.retry_tts_budget --limit 20
docker compose exec worker python -m backend.retry_tts_budget --limit 20 --apply
```
Verifique primeiro a prévia: o modo --apply enfileira as correspondentes e não apaga a mídia.

## Atenção
- HTTP 200 apenas confirma a resposta HTTP, não a validade do JSON do modelo.
- Tentar novamente não garante sucesso se o modelo estiver desconfigurado, sem quota ou continuamente indisponível.
- Não execute `docker compose down -v`; isso remove volumes persistentes.
