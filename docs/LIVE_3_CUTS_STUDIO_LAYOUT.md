# GTA Studio — 3 cortes por live e layout streamer/gameplay

## Objetivo
Cada VOD público, encerrado e autorizado passa por uma **produção-pai**, com pelo menos
três trechos **distintos e não sobrepostos** (20–60 s, score mínimo configurado).
A live é processada pelo WhisperX uma única vez; os MP4s são renderizados,
validados e persistidos individualmente, com SEO próprio.

## Regras de produção
1. A seleção manual do VOD pode ser feita pelo formulário ou diretamente na lista
   de lives encontradas pelo Viral Radar. Cada item não autorizado apresenta
   **Incluir autorização e gerar 3 cortes**. A prova declarada autoriza o canal,
   dentro da `clipping_allowlist.json`, antes de qualquer download.
2. O operador escolhe em qual canto da fonte está a webcam (padrão: inferior
   esquerdo, testado com o vídeo do Patife). Pode escolher os outros três cantos.
3. Um job `live_cut:<parent_id>` valida VOD e direitos, baixa o áudio uma vez,
   identifica três candidatos sem sobreposição, escolhe timestamps WhisperX
   e renderiza/valida cada candidato separadamente.
4. Se houver apenas 0–2 momentos acima do score mínimo, o job falha
   explicitamente; não é permitido completar a meta com cortes fictícios
   ou abaixar o limiar. Retentativas respeitam o limite da fila.
5. Cada corte concluído fica armazenado em
   `videos/final/live_cuts/<parent_id>/cut-01.mp4`, `cut-02.mp4`,
   `cut-03.mp4`, com `metadata-0N.json` e `cover-0N.jpg`.
6. O status `REVIEW_PENDING` indica resultado técnico aprovado **para revisão
   humana**, não publicação automática. Cada corte é aprovado ou descartado
   individualmente. O SEO inclui atribuição e link da live original.
7. A cota diária contabiliza MP4s individuais validados, não uma única live,
   e reserva até três posições enquanto um job está ativo. Como cada VOD
   fornece três cortes, uma segunda live pode ultrapassar a meta de cinco,
   sem inventar produção.
8. Os registros antigos de um único corte são importados para
   `live_clip_outputs` como `legacy-<parent_id>` e o arquivo antigo
   `cut.mp4` fica intacto.

## Layout vertical para lives
- Canvas 1080 × 1920, 30 fps.
- Webcam original ampliada: x=40–1040, y=130–785.
- Gameplay: x=40–1040, y=830–1600, com crop lateral para não repetir
  o inset da webcam.
- Legendas sincronizadas: centro em y=1735, dentro da faixa abaixo do jogo.
- Composição do FFmpeg é parametrizada por `webcam_anchor`:
  `bottom_left`, `top_left`, `bottom_right`, `top_right`.
- O preset não inventa câmera: extrai a webcam realmente incorporada à
  gravação. Se o canal tiver facecam em localização diferente ou sem webcam,
  o operador deve escolher outro preset; nunca afirmar detecção de rosto
  automática que não ocorreu.
- Mixagem mantém normalização -14 LUFS ±1, imagem H264 1080×1920 e
  legendas com timestamps reais. Essas validações não foram relaxadas.

## Video Studio e Cortes de Lives
- O mesmo painel de produção, `LiveStudioPanel`, é montado nas duas abas.
- Mostra fase ativa do worker, progresso `0/3 → 3/3`, as entregas filhas,
  status individual, nota, intervalo em segundos, prévia, download, SEO,
  aprovação ou descarte.
- Atualiza automaticamente a cada quatro segundos.
- Para live antiga com render incorreto, botão **Regerar 3 cortes com webcam em cima**:
  salva MP4s não aprovados em `history/<id>/` e mantém o original;
  cortes já aprovados não são substituídos.

## Banco e API (migração incremental)
- `live_clips` mantém o VOD pai e agora recebe
  `cut_target` (=3) e `webcam_anchor`.
- Nova tabela `live_clip_outputs`, com `parent_id`, `ordinal`, fonte,
  score, timestamps, status e caminhos independentes.
- `GET /api/live-clips` agrupa os filhos e retorna o job correspondente.
- `POST /api/live-clips/{parent_id}/outputs/{output_id}/decision` é a decisão
  humana individual de cada corte.
- `GET /api/live-clips/{parent_id}/outputs/{output_id}/file` e `/metadata`.
- `POST /api/live-clips/{parent_id}/reprocess` recria três cortes sem
  permitir sobrescrita de resultados já aprovados.
- Rotas preexistentes continuam operacionais para compatibilidade, mas a
  decisão de grupo é bloqueada quando existem três arquivos filhos.

## Implantação
Após terminar o processamento atual de WhisperX:
```powershell
git pull --ff-only origin main
docker compose build api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
```

A primeira subida aplica migrações aditivas, sem zerar o SQLite.
A execução real completa depende de VOD disponível e autorizado, WhisperX,
FFmpeg e capacidade de processamento. `INSTALL_WHISPERX=1` é necessário
no build do worker se WhisperX ainda não estiver instalado.

## Testes
`tests/test_live_multi_output.py` testa esquema, limites, autorização,
agrupamento, aprovação individual, quota, reprocessamento e mock de três renders.
A CI `Validate GTA Studio` executa sintaxe, build Next e regressões Python
relevantes. Um VOD longo real requer homologação no Docker do operador.
