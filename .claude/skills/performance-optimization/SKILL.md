---
name: performance-optimization
description: Otimização de tempo de renderização, uso de CPU/GPU, vazamento de memória e processamento assíncrono.
---

# performance-optimization

## Função no Estúdio
Maximização de eficiência em montagens FFmpeg, consultas SQLite, geração de áudio TTS e cache de assets intermediários.

## Diretrizes de Operação
1. **Reutilização e Caching**: Evitar renderizar novamente trechos idênticos de vídeo (`segment-cache` por hash SHA256).
2. **Paralelismo Controlado**: Limitar threads de FFmpeg (`-threads 2`) para evitar exaustão de recursos no host.
3. **Filtragem de Processos**: Liberar subprocessos zumbis e aplicar timeouts determinísticos em todas as operações de E/S.
