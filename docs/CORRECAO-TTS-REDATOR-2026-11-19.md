# GTA Studio — Correção do orçamento de narração (v8.1)

## Erro observado

Em uma produção de 45 s, a narração ficou com **34,24 s**, enquanto a faixa
configurada era **38–40 s**. O código rejeitava a narração curta **antes** de
permitir desaceleração moderada com FFmpeg. O Redator era chamado até duas vezes,
mas podia não aumentar suficientemente a duração real, gerando `PIPELINE_ERROR`
em toda a esteira.

## Correção

- `backend/audio_timeline.py`: aplica primeiro um `atempo` entre **0,88 e 1,10**
  (desaceleração de até 12% ou aceleração de até 10%) sem alterar a altura da voz.
  O alvo permanece `duração do vídeo - margem`, com tolerância de até 2 s para
  menos. O FFmpeg mede o resultado real; nunca corta a fala.
- `backend/redator.py`: importação de `IntegrationError` corrigida; preserva o
  comportamento de ajustes de texto somente quando o ritmo moderado não resolve.
- `backend/retry_tts_budget.py`: ferramenta conservadora para reenfileirar somente
  produções `PIPELINE_ERROR` relacionadas a Redator/TTS. Modo padrão só lista.
- `tests/test_tts_budget_fix.py`: regressões de áudio curto, longo e dentro da faixa.

## Instalação em projeto existente (PowerShell)

1. Salve uma cópia de segurança dos seus arquivos e banco.
2. Extraia o ZIP **patch** na raiz de `Clips-Virais`, mantendo `.env`, `assets/`,
   `models/`, `data/` e os volumes Docker existentes.
3. Rode:

```powershell
docker compose up -d --build api worker web

docker compose exec api python -m backend.retry_tts_budget --limit 5
```

O comando acima **não altera o banco**; exibe quais vídeos seriam retomados.
Para efetivar um lote pequeno:

```powershell
docker compose exec api python -m backend.retry_tts_budget --apply --limit 3
docker compose logs --tail=120 worker
```

Você também pode abrir uma produção com `Erro de pipeline` e usar
**Reescanear e retomar**. Não execute `down -v`.

## Como conferir

- O erro `Redator não conseguiu melhorar o orçamento temporal` deixa de acontecer
  quando o áudio se encaixa via `atempo`.
- `temp/{id}/audio-timeline.json` (diretório de trabalho da produção) inclui
  `raw_tts_seconds`, `tempo_applied`, `speech_real_seconds` e `status`.
- Para um vídeo de 45 s, a narração termina entre 38–40 s; o vídeo continua com
  o encerramento musical. Se o texto for excessivamente curto/longo para um
  ajuste suave, o Redator continua responsável por reescrever o texto e o vídeo
  permanece em erro técnico caso a correção seja impossível, sem gastar uma das
  cinco tentativas do Avaliador.

## Testes

- Suíte de backend: **111 testes** com parser RSS de teste neste ambiente;
  o parser RSS real não estava instalado.
- FFmpeg sintético: 34,24 s de áudio tratados com `atempo≈0,896335` resultaram
  em **38,196 s** medidos por `ffprobe`, dentro do intervalo aceito.
- A geração real com Piper/OmniRoute e o Docker do computador do usuário ainda
  dependem de homologação local.
