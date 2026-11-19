# GTA Studio — Redator/TTS sem progresso (hotfix v8.2)

## O que causava o erro

No `backend/redator.py`, a rotina `adjust_timing` fazia uma chamada de IA e
considerava que houve correção apenas se o texto resultante fosse diferente.
Quando o modelo do OmniRoute devolvia o texto original, o código levantava
`PreflightError('Redator não conseguiu melhorar o orçamento temporal do TTS.')`
imediatamente. Isso impedia renderizar qualquer vídeo com roteiro curto,
mesmo quando o pipeline e o Piper estavam operacionais.

A revisão inicial (`polish`) também podia encurtar demais um roteiro; não havia
proteção contra perda acentuada de palavras antes da medição do Piper.

## Correção

- A revisão inicial não aceita uma redução acima de 15% do número de palavras,
  pedindo um novo texto que preserve o contexto; em último caso mantém o roteiro inicial.
- O ajuste temporal calcula alvos de palavras por cena a partir da **duração
  medida pelo Piper**, não de um único valor fixo de palavras por segundo.
- Se o Redator devolver texto idêntico ou mudar poucas palavras, o sistema
  tenta outra vez com metas concretas e, por último, usa a rota do Escritor.
- A versão corrigida registra `word_count_before`, `word_count_after`, rota
  usada e respostas insuficientes em
  `handoff/<id>/narration-timing-adjust-<tentativa>-<correcao>.json`.
- Não adiciona silêncio artificial nem inventa fatos para bater duração.
  Quando a fonte não contém contexto suficiente ou nenhum modelo segue a
  instrução, o pipeline exibe detalhes úteis e permanece em `PIPELINE_ERROR`
  sem consumir tentativas do Avaliador.

## Instalação (no PowerShell)

1. Faça backup da pasta do projeto. Preserve `.env`, `models`, `assets`, banco
   SQLite e volumes Docker.
2. Extraia o ZIP do patch na raiz `Clips-Virais`, substituindo os arquivos.
3. Rode:

```powershell
docker compose up -d --build api worker web
docker compose exec api python -m backend.diagnose_tts_budget --limit 10
docker compose exec api python -m backend.retry_tts_budget --limit 3
docker compose exec api python -m backend.retry_tts_budget --apply --limit 3
docker compose logs -f --tail=100 worker
```

O diagnóstico e o comando `retry_tts_budget` sem `--apply` são somente leitura.
`--apply` reenfileira as produções com falha de TTS, sem apagar renders,
configurações, API keys ou os limites de produção.

### O que verificar

- No arquivo `handoff/<id>/narration-timing-adjust-*.json`, confira o
  crescimento real de palavras.
- Compare o novo tempo medido pelo Piper e o tempo-alvo na linha do tempo.
- Se o modelo continuar devolvendo o mesmo texto, verifique a rota
  `redator` e a rota `escritor` na tela Configurações. Ambas precisam de
  um modelo instruído para gerar texto estruturado no OmniRoute.
- O sistema mantém a margem configurada (5 s por padrão) e o vídeo final
  continua com a duração do template.

## Arquivos alterados

- `backend/redator.py` — proteção contra resumo excessivo e segunda estratégia
  de expansão ou redução controlada por TTS real.
- `backend/diagnose_tts_budget.py` — relatório sem escrita no banco.
- `tests/test_redator_tts_resilience.py` — regressão contra resposta idêntica
  do modelo e fallback para Escritor.

A correção foi testada com respostas simuladas de IA, não no Docker nem no
OmniRoute real do usuário. Os resultados precisam ser confirmados em produção.
