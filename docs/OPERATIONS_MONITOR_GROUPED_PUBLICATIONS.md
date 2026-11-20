# Monitor operacional e publicações agrupadas — GTA Studio

## Monitor do Dashboard
- A tela principal exibe `Monitor de produção` acima da antiga linha dos agentes.
- Atualização automática a cada 4 segundos pelo endpoint autenticado `GET /api/operations/live`. Polling HTTP; não é WebSocket e **não** estimamos porcentagens.
- Dados reais: heartbeat do worker, jobs `RUNNING` e `QUEUED`, tentativas, fila, último evento, estágio de edição e últimas falhas.
- A tela diferencia worker offline, executando, aguardando e disponível.
- Nos cortes de lives, o estágio muda quando o worker verifica a licença, baixa áudio, analisa o som, transcreve, seleciona, baixa trecho, renderiza e valida.
- Etapas com mais de cinco minutos sem alteração mostram um aviso de ausência de mudança registrada. Um processamento longo (WhisperX / FFmpeg) pode continuar ativo; **não** classificar automaticamente como travamento.
- O monitor é exclusivamente leitura e não altera direitos, aprovações, fila, renderização ou limites do Piper.

## Fila prioritária
- Um job de corte enviado manualmente é escolhido antes dos pipelines comuns e das pesquisas automáticas, quando elegível.
- O Radar pesquisa em lotes de até 3 canais, com limite nominal de 100s por execução; cede lugar quando um corte aguarda. Chamadas externas já iniciadas podem ultrapassar esse limite nominal.
- Jobs em execução **não** são interrompidos à força; a nova prioridade age na próxima escolha da fila.
- Jobs com data futura de tentativa continuam aguardando seu horário; prioridade não afrouxa os limites de retentativa.

## Prontos para postar
- Um card por título canônico, com plataformas agrupadas e seus estados individuais.
- Cada plataforma mantém seus próprios campos de SEO, links, exclusão e confirmação manual.
- Títulos iguais provenientes de IDs de vídeo diferentes aparecem juntos, mas os diferentes arquivos permanecem acessíveis individualmente.
- O calendário exibe um único item por título/dia, com total de redes incluídas.
- O contador lateral passa a indicar **vídeos distintos** com pendências, não o número de publicações em plataformas.

## Implantação
```powershell
git pull --ff-only origin main
docker compose build api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
```

Acompanhe os logs do worker se o status permanecer em RUNNING sem progresso e sem novos eventos. As melhorias de tela não dependem de YouTube Data API key.

## Testes
- `tests/test_operations_monitor.py`: prioridade na fila, monitor via HTTP, heartbeat, etapa e evento reais.
- `tests/test_api_boot_smoke.py`: presença da rota do monitor.
- Testes existentes de licenciamento, Piper e vídeo devem continuar passando. O build Docker completo não foi executado aqui.

Nenhuma migração destrutiva foi adicionada. A coluna opcional `stage` é criada em `live_clips` apenas caso ainda não exista, preservando os registros anteriores.
