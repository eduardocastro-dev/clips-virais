---
name: ffmpeg-skill
description: Operação avançada de filtros FFmpeg, redimensionamento com proporção preservada, transições, ducking e exportação H.264.
---

# ffmpeg-skill

## Função no Estúdio
Engenharia de linha de comando FFmpeg para corte, composição de múltiplas camadas, overlay com alpha, mixagem de áudio e aceleração gráfica.

## Diretrizes de Operação
1. **Cálculo de Proporção e Escala**:
   - Para fundo vertical: `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1`.
   - Para cards e capturas com Ken Burns: `zoompan=z='min(zoom+0.0008,1.15)':d=1:s=1080x1920:fps=30`.
2. **Composição em Camadas (filter_complex)**:
   - Camada 0: Gameplay / Fundo animado.
   - Camada 1: Card editorial ou trecho de vídeo da fonte com borda e sombra.
   - Camada 2: Avatar da persona com animação de flutuação e respiração.
   - Camada 3: Legendas sincronizadas (ASS) e badge temático superior.
3. **Mixagem de Áudio**:
   - Narração primária no canal frontal, música ambiente atenuada com ducking (`sidechaincompress`) para garantir clareza vocal.
