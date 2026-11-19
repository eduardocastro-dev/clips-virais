---
name: animacao-hyperframes
description: Planejar motion graphics 9:16 para GTA Studio usando style_guide.json; HyperFrames e opcional e nao substitui FFmpeg ou o pipeline automaticamente.
---
# Animacao / HyperFrames

## Ferramenta
[HyperFrames oficial](https://github.com/heygen-com/hyperframes) transforma HTML/CSS/JS e animacoes seekable em video. Requer instalacao separada do CLI/dependencias para executar. **Esta skill instala orientacoes no repositorio; nao instala o executavel do HyperFrames.**

## Regras obrigatorias
1. Carregar `style_guide.json` como fonte unica de estilo, dimensoes, paleta, safe zones, duracao, easing e efeitos.
2. Carregar `transcript.json` somente quando a origem dos tempos for conhecida. Gerar animacoes por palavra apenas com tempos alinhados; sem eles, animar frases sem atribuir exatidao.
3. Planejar `animation_plan.json` com por elemento: `scene`, `start_seconds`, `end_seconds`, `effect`, `duration_ms`, `easing`, `layout`, `sfx_event`, `source_asset_id`.
4. Escolher `effect`, `easing` e layout **apenas** das listas no guia. Nunca repetir o mesmo layout em cenas consecutivas quando houver alternativa coerente; nao adicionar dois movimentos de camera fortes simultaneos.
5. Usar somente animacoes deterministicas e buscaveis por timecode. Conferir snapshots e video temporario antes do compositing.
6. Priorizar camadas RGBA com canal alfa quando o formato/exportador realmente permitir. Se nao permitir, compor pelo FFmpeg existente sem fingir que existe alpha.
7. Ajustar movimento ao tempo REAL do audio Piper, nao retimar o audio para caber na animacao. Preservar validacao FFprobe e de direitos do pipeline.

## Integracao incremental
Experimentar em um modulo **opcional**, por ex. `backend/motion_hyperframes.py`, somente quando for solicitada implementacao. Evitar substituir `backend/visual_renderer.py`, `backend/media.py` e `backend/audio_timeline.py`.
O efeito de um plano nao autoriza utilizar arquivo sem licenca. Sem CLI HyperFrames, gerar o plano e manter render FFmpeg existente.

## Saida
`animation_plan.json` e, somente se o ambiente suportar, clipes/overlays validados. Nao afirmar que cenas foram renderizadas sem arquivos e checagens reais.
