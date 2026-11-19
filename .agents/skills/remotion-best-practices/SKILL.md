---
name: remotion-best-practices
description: Boas práticas de composição audiovisual programática com React, animações temporizadas, tipografia e transições.
---

# remotion-best-practices

## Função no Estúdio
Desenho de layouts de vídeo verticais 9:16 (1080x1920), animações matemáticas suaves baseadas em frames (spring, interpolate) e sincronização visual.

## Diretrizes de Operação
1. **Frame-Rate e Proporção**: Produções sempre em 30 FPS ou 60 FPS, 1080x1920 (9:16 vertical), com tempo baseado em segundos absolutos e frames determinísticos.
2. **Curvas de Animação**: Utilizar funções de interpolação suaves (ease-out, spring) em cards de texto e entradas de mídia em vez de cortes secos.
3. **Safe Zones para Redes Sociais**:
   - Manter informações críticas entre Y=200px e Y=1500px para evitar sobreposição pelos botões de curtir/comentar do TikTok/Shorts.
