---
name: remotion-render
description: Pipeline de renderização de alta velocidade para MP4, controle de codecs e geração de miniaturas de capa.
---

# remotion-render

## Função no Estúdio
Padronização da renderização final para compatibilidade com YouTube Shorts, TikTok e Instagram Reels.

## Diretrizes de Operação
1. **Especificações Técnicas de Saída**:
   - Contêiner: MP4 (`-movflags +faststart`).
   - Codec de Vídeo: H.264 (libx264), High Profile, CRF 22, pixel format `yuv420p`.
   - Resolução: 1080x1920 (proporção 9:16).
   - Codec de Áudio: AAC estéreo, 48kHz, 192kbps.
2. **Validação de Pré-Voo**: Confirmar duração, resolução, ausência de quadros pretos e integridade do áudio antes da entrega.
