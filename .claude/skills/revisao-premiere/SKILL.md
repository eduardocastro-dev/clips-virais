---
name: revisao-premiere
description: Checklist de revisao em Adobe Premiere quando disponivel; preflight FFmpeg/FFprobe permanece obrigatorio e nao depende de Premiere dentro do Docker.
---
# Revisao / Adobe Premiere Pro

## Papel
Revisar qualidade de edicao e entrega depois do render; **nao** substituir `backend/media.py` nem executar Premiere em containers onde nao esteja instalado.

## Entrada
`style_guide.json`, `transcript.json` (se existir), `animation_plan.json`, `sfx_map.json`, MP4 final autorizado e manifesto de licencas.

## Checklist
1. Confirmar formato 9:16, dimensoes, FPS e H.264 via FFprobe, sem assumir exportacao Premiere.
2. Conferir texto dentro de safe zones do guia, contraste, tempo de leitura, legibilidade em dispositivos moveis.
3. Verificar sincronia SFX/animacao (<=2 frames), legendas e audio real Piper. Sem timestamps de palavra, nao afirmar precisao por palavra.
4. Detectar repeticao consecutiva de layout, movimentos simultaneos excessivos e cortes sem justificativa narrativa.
5. Validar loudness integrado com `ebur128`/`loudnorm` e confirmar ducking de musica sob a fala.
6. Confirmar fontes, efeitos, videos, imagens, templates e trilhas com origem/licenca; asset sem licenca deve ser retirado/bloqueado.
7. Se houver Adobe Premiere Pro com automacao suportada e autorizada, preparar artefatos editaveis e check visual. Caso contrario, produzir revisao via FFmpeg/ffprobe e relatar `premiere_not_available`; nao fingir que o Premiere revisou/exportou.

## Saida
`review_checklist.json` com item, evidencias, status, timestamp e bloqueios; `review_notes.md` para intervencao humana. Nenhum `APROVADO` sem preflight tecnico do pipeline.

## Referencia
https://developer.adobe.com/premiere-pro/uxp/plugins/
