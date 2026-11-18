# GTA Studio v7 — Áudio real, vozes independentes, 72 poses e tempo de narração

## 1. Diagnóstico do erro `metadata_errors`

Localização: `backend/transcription.py::main` importa `faster_whisper.WhisperModel` e executa `model.transcribe`. A versão `faster-whisper==1.2.1` usa `av.open(..., metadata_errors="ignore")` dentro de seu decodificador. A partir de PyAV 19, esse argumento deixou de existir. O projeto não fixava PyAV, portanto uma instalação recente pode quebrar **todas** as transcrições.

Correção: `backend/requirements-video.txt` fixa `av==18.1.0` ao lado de `faster-whisper==1.2.1`. O tratamento em `backend/media.py::run` identifica erros de processo Python/PyAV e preserva o traceback em `/studio/logs/media-last-error.log` em vez de rotulá-los como falha do executável FFmpeg.

A saída original do traceback e as versões instaladas na máquina do usuário **não vieram no ZIP**. Para confirmar no Docker real, após reconstruir:

```powershell
# Na pasta Clips-Virais
docker compose up -d --build api worker web
docker compose exec worker python -m backend.doctor_audio
# Reenfileira SOMENTE produções históricas bloqueadas por metadata_errors
docker compose exec api python -m backend.retry_audio_errors
```

Um erro Python/PyAV/FFmpeg/TTS interrompe a produção em `PIPELINE_ERROR`, sem incrementar a avaliação das cinco tentativas. O botão "Reescanear e retomar" funciona para `PIPELINE_ERROR`.

Fallback local: o Estúdio sintetiza **cada frase individualmente**, mede a duração do arquivo WAV com `ffprobe` e gera timestamp real por frase. Se Faster Whisper não transcrever, as legendas usam esses timestamps **por frase**, sem alegar alinhamento palavra-a-palavra. O relatório indica `tts_phrase_ffprobe_measured` ou `whisper_words`. Esse método não oferece a mesma precisão de word alignment, mas não usa `estimated_by_phrase`.

## 2. Três vozes Piper, uma por personagem

A v6 guardava `voice_model` em `kv['cast']` (JSON) e `backend/personas.py::get_cast`; todos caíam em `PIPER_MODEL` (mesma voz Cadu). Em v7:

| Personagem | Modelo PT-BR | Ritmo padrão |
|---|---|---|
| Dante Palma | `/models/pt_BR-cadu-medium.onnx` | 0,96 |
| Lia Varela | `/models/pt_BR-jeff-medium.onnx` | 0,92 |
| Caio Rivas | `/models/pt_BR-faber-medium.onnx` | 1,05 |

As vozes são **modelos distintos**, mas o gênero vocal e o grau de diferença perceptiva precisam ser confirmados ouvindo as amostras; não é possível verificar o timbre apenas pelo nome dos pesos.

Instalar em `./models`, montado como `/models` dentro do container:

```powershell
python scripts/install_voices.py
docker compose up -d --build api worker
docker compose exec api python -m backend.voice_samples
```

O instalador faz download dos pesos ONNX e dos JSONs direto de `rhasspy/piper-voices`, valida MODEL_CARD e SHA-256, preserva modelos já baixados e escreve `assets/voices/LICENSES.md`. As três amostras são salvas em `assets/voices/samples/` com WAV + SHA-256 + estimativa de frequência fundamental quando possível. Confirme cada timbre clicando em **Configurações → Ouvir amostra**.

**Limitação deste pacote:** pesos ONNX não foram embutidos: o ambiente de produção do ZIP não possuía acesso à rede para baixar os dois modelos adicionais. Execute o instalador no seu Windows, com internet. Cadu já presente será preservada.

## 3. Poses

Arquivos em `assets/personas/{dante_palma|lia_varela|caio_rivas}/expressions/{NN}_{slug}.png`. O pacote inclui 72 PNGs RGBA 1024×1536; cada personagem tem manifesto com 24 emoções/poses, checksum e estado ativo. Todos têm os quatro cantos transparentes. Também existem cópias em `templates/personas/` para semear uma instalação Docker nova sem sobrescrever conteúdo do usuário.

**O estilo é arte vetorial simplificada**, não 72 pinturas fotorrealistas. Personagens e roupas são fixos, expressões/gestos variam. Para exigir outra direção artística, use o botão **Trocar PNG** na galeria: arquivos precisam ser 1024×1536 RGBA, com cantos transparentes.

O código reconhece `Scene.emotion` (padrão `neutro`), resolve a imagem por personagem, evita pose consecutiva igual e registra `pose-timeline.json` por tentativa. A interface mostra a galeria 4×6 e o manifesto da pose usada. **Restaurar** repõe a pose original fornecida, não executa nova geração criativa por IA. `scripts/generate_expressions.py` permite recriar os PNGs locais de maneira reprodutível caso haja um arquivo corrompido (opcional no host: `python -m pip install CairoSVG`; não é dependência do runtime Docker).

## 4. Narração cinco segundos menor que o vídeo

Configurações: `narration_margin_seconds` (5,0 s padrão) e `narration_lead_seconds` (0,5 s padrão). Para 45 s, o alvo de **fala medida** é 40 s, iniciada em 0,5 s, com ~4,5 s de fechamento só com música e imagem. A tolerância aceita áudio real entre o alvo menos 2 s e o alvo, nunca acima.

`backend/audio_timeline.py` mede cada frase após síntese e normalização por `ffprobe`, emite `audio-timeline.json` por tentativa e encaixa a voz no vídeo sem acelerar acima de 1,1×. Se a fala ficar longa/curta, `backend/redator.py::adjust_timing()` pede ajuste localizado ao modelo, no máximo duas correções por tentativa, sem gastar uma das cinco avaliações. Se não conseguir corrigir, fica em `PIPELINE_ERROR` para o operador resolver; não se corta texto no meio nem se inventa sucesso.

O Video Studio exibe segundos do vídeo, duração real da fala, alvo, margem de fechamento e barras da linha do tempo. Para consultar em JSON:

```powershell
# Use um ID real da produção
# GET /api/videos/<ID>/audio-timeline?attempt=1
# GET /api/videos/<ID>/pose-timeline?attempt=1
```

## 5. Testes locais e homologação

- 99 testes Python passaram com parser RSS substituto do ambiente de testes; o parser verdadeiro não estava instalado no ambiente de desenvolvimento.
- Teste FFmpeg real: MP4 de 10 s, 1080×1920, H.264/AAC; verificação técnica aprovada com 4,5 s de encerramento sem fala.
- 72 PNGs verificados (24 por personagem, canal alpha, cantos transparentes, 1024×1536).
- Sintaxe TSX validada, sem build completo de Next.js por ausência de pacote no cache npm local.
- **Não homologado aqui:** PyAV/Faster Whisper/piper reais no Docker do usuário, download ONNX, 3 vozes e geração real do GTA Studio com OmniRoute.

A instalação não apaga SQLite, `/studio/data`, `models/`, `assets/` do usuário, `.env` nem vídeos anteriores. Preserve cópias de segurança antes de extrair o patch; jamais execute `docker compose down -v` para essa atualização.
