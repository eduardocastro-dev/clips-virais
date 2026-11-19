---
name: sonorizacao-epidemic
description: Direcao de trilha e SFX sincronizados a motion com licencas verificadas; uso de Epidemic Sound somente se houver acesso comercial valido.
---
# Sonorizacao / Epidemic Sound

## Responsabilidade
Propor pop, whoosh, hit, riser, ambiencia, musica e volume relativo seguindo `style_guide.json` e `animation_plan.json`.

## Fluxo
1. Ler eventos de animacao e criar `sfx_map.json` deterministico com `event_id`, `animation_id`, `start_seconds`, `start_frame`, `type`, `asset_path`, `volume_db`, `license_proof`, `track_id`, `provider`, `status`.
2. Calcular inicio por frame usando `fps` do guia, com tolerancia maxima de dois frames. Se audio estiver realinhado, recalcular eventos pelo TTS real.
3. Verificar comprovante de licença **antes** de incluir musica e efeitos no render. Nao baixar nem selecionar midia Epidemic automaticamente sem credenciais, acesso autorizado e termos compativeis com a publicacao.
4. A API gratuita da Epidemic Sound permite prototipagem, **nao** publicacao comercial. Sem licenca comercial, escolher somente assets locais com comprovante validado no GTA Studio; caso contrario marcar a trilha como `not_licensed` e bloquear seu uso.
5. Fazer ducking da musica sob narracao, voz prioritária sobre SFX e musica, evitar mascaramento, picos e corte abrupto; alvo de mixagem e `style_guide.json.audio.target_integrated_lufs`.
6. Preservar verificacoes de direitos de `backend/assets.py`/`backend/production_media.py`, e nao inserir fallback sem licenca.

## Saida
`sfx_map.json` rastreavel com IDs/licencas e uma lista de eventos bloqueados quando nao ha direito comprovado. Nao declarar um audio licenciado apenas porque veio de um catalogo.

## Documentacao
https://developers.epidemicsound.com/docs/
