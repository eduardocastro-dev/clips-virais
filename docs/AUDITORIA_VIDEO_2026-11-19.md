# Auditoria real do MP4 + plano de edição de alto impacto — GTA Studio

Data: 2026-11-19. Arquivo recebido: `032fc35ec31d465f83b75141bd2c21f4-tentativa-3.mp4`.

## Evidências do vídeo enviado

| Medição | Resultado | Método |
|---|---|---|
| Duração | 30,000s | ffprobe |
| Formato | 1080×1920, 9:16, H.264 30 fps, AAC 48kHz | ffprobe |
| Loudness integrado | **−22,7 LUFS** | FFmpeg `ebur128` |
| True peak | **−9,7 dBFS** | FFmpeg `ebur128=peak=true` |
| Cortes abruptos evidentes | ~8 candidatos: 2,0s; 5,37s; 11,37s; 16,67s; 18,67s; 20,67s; 25,97s; 27,97s | FFmpeg `select=gt(scene,0.42)`; não conta todos os cortes |
| Outros movimentos/cortes | 18 alterações fortes a limiar de diferença média >32 entre amostras de frames a 5 fps | OpenCV; métrica heurística, não equivalente a cortes de PySceneDetect |
| Imagens escuras | 35,6% das amostras com luminância média abaixo de 50/255 | OpenCV 180×320 a 5 fps |

## Problemas do vídeo (inspeção visual por timestamps)

- **0–2s:** a screenshot/card da fonte cobre parte importante da área visual. Manchete extensa ocupa o topo, visual de gameplay e título competem entre si. O foco da abertura fica difuso.
- **2–6s:** texto solto palavra a palavra e o apresentador pequeno, com expressão/movimento limitados. Corte da informação em palavras individuais impede leitura natural.
- **6–16s:** o mesmo título `O ASSUNTO VIRALIZOU` permanece visualmente dominante enquanto clipes mudam. Não existe uma progressão visual proporcional ao avanço da narrativa.
- **16–24s:** repetição de `GTA 6 NA CULTURA POP BR`, com gameplay que nem sempre demonstra o assunto em específico. Não afirmar que imagens de GTA V comprovam novidades de GTA 6.
- **26–30s:** CTA em parágrafo longo ocupa o centro/parte inferior e compete com o apresentador e as legendas. Fala perde impacto no encerramento.
- **Todo o vídeo:** persona pequena perto do rodapé, cenas muito escuras, grafismos genéricos, pouco contraste emocional, ausência de um padrão próprio de abertura/destaque/fechamento.
- **Áudio:** −22,7 LUFS contra alvo de trabalho −14 LUFS; a voz perde presença. Volume e entonação são questões distintas: o Piper não é um TTS com controle granular de atuação emocional.

## Referências mundiais pesquisadas (não copiar os vídeos)

- Guinness World Records: `BEST Duo Trick Shots` (Colin Amazing), 4,66 bilhões de visualizações em 10/03/2026, listado como Short mais visto. Fonte: https://www.guinnessworldrecords.com/world-records/771115-most-viewed-youtube-shorts-video
- Ranking externo de Reels: vídeo promocional de Deepika Padukone / Hilton, ~1,99 bilhão de views, listado entre os mais vistos em 2026; não é um formato de jornalismo gamer e rankings mudam. Fonte: https://fastsocial.co/most-viewed-instagram-reels
- Entrevista do YouTube sobre Shorts: importância do primeiro segundo e minihistórias com curiosidade, avanço e satisfação. Fonte: https://blog.youtube/creator-and-artist-stories/youtube-shorts-deep-dive/
- Meta destaca originalidade: simples bordas, cortes e legendas em material de terceiros não constituem transformação editorial suficiente. Fonte: https://about.fb.com/news/2026/03/rewarding-original-creators-on-facebook/

Não existe um único template universal para os vídeos mais vistos; desafios/truques/publicidade têm públicos e objetivos diferentes. O GTA Studio adota os **princípios de alta retenção**, com identidade própria e conteúdo factual.

## Implementação incremental

1. **Masterização final obrigatória:** `backend/audio_mix.py` sempre produz MP4 com áudio masterizado, mesmo sem trilha/SFX. Aplicar high-pass 80Hz, reforço +1,5dB em 2,5kHz, compressão 2,2:1 e loudnorm final para −14 LUFS, TP −1,5. Música licenciada recebe ducking. SFX licenciados ficam sincronizados à abertura e a cada terceiro corte real de montagem; não há mais um som arbitrário a cada 5s.
2. **Legendas por blocos:** `backend/media.py` e `backend/viral_edit.py`: 3–4 palavras por bloco, progresso ASS karaoke se existirem timestamps reais de palavra; fallback por frase real do Piper quando ASR falhar, sem inventar alinhamento palavra-a-palavra.
3. **Gancho e CTA:** intro com headline de duração curta; títulos de cena só aparecem ~1,15s; CTA resumido para até 48 caracteres, exibido por ~2s sem cobrir avatar.
4. **Câmera virtual e cards:** `backend/visual_renderer.py` adiciona movimento suave de enquadramento a vídeos licenciados. Cards de fonte menores, curtos (máx. 1,9s) e reduzidos a duas aparições por vídeo via `backend/assets.py`.
5. **Personas:** `backend/media.py` aumenta discretamente o tamanho do avatar; `backend/personas.py` ajusta velocidade padrão de fala para novos presets (Dante 1,02; Lia 1,00; Caio 1,08). *Valores definidos manualmente pelo usuário em configurações continuam prevalecendo*. A expressividade é aprimorada principalmente no texto do Escritor/Redator.
6. **Templates adicionais:** `gta-radar-viral`, `gta-detail-breakdown` e `gta-hype-reaction`. Templates antigos continuam disponíveis e se beneficiam da mixagem/legenda/câmera. Nenhuma reprodução de assets ou identidade de criadores de referência.

## Qualidade e preservação

- **NÃO ALTERAR:** limites da duração real TTS Piper, validação de prova de licença, cópia segura de gameplay, fluxo de revisão humana, antiplágio, status de aprovação, arquivos persistentes.
- Não foi incorporada música ou SFX sem licença. Sem biblioteca licenciada, a entrega recebe apenas voz masterizada.
- A normalização foi exercitada no áudio do arquivo real: ~−14,4 LUFS e −1,3 dBFS de pico verdadeiro, preservando a duração. É uma verificação do processamento de áudio, **não** uma nova renderização com o TTS.
- Teste de FFmpeg com enquadramento móvel executado com sucesso no vídeo enviado.
- A suíte automatizada do repositório e renderização Docker com assets próprios devem ser validadas após o deploy; os testes novos cobrem agrupamento de legendas, fallback de frase, mixagem sem trilha e horários de SFX.

## Deploy

```powershell
git pull origin main
docker compose build --no-cache api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
docker compose logs -f worker api
```

Os vídeos já aprovados não são alterados automaticamente. Crie um novo render ou reabra a produção para uma nova tentativa de edição autorizada. Não execute `docker compose down -v`.
