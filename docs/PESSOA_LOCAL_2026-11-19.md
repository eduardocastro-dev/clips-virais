# Simplificação da Pessoa — 19/11/2026

## Motivo
O processo parava ao receber timeout na chamada `llm('pessoa', ...)` durante a avaliação, apesar de o render e a avaliação técnica poderem estar corretos.

## Alterações
- A Pessoa deixa de consultar OmniRoute e não precisa mais do modelo `studio-free`.
- Em vez de sete notas subjetivas de audiência, passa a produzir um checklist **local e informativo**, sem nota e sem reprovação, com informações verificáveis do roteiro: gancho, presença de texto/narração nas cenas, duração/distribuição das cenas.
- O Avaliador continua responsável pela análise de qualidade. Verificações técnicas, FFprobe, transcrição e direitos permanecem obrigatórias.
- O frontend deixa de exibir configuração e habilitação multimodal do modelo Pessoa. Resultados legados ainda podem ser exibidos no histórico.
- Configurações Pessoa antigas continuam persistidas por compatibilidade, mas não são utilizadas na avaliação.
- Nenhuma pontuação fictícia ou relato de pessoa real é produzido.

## Testes
No ambiente de desenvolvimento, 19 testes direcionados passaram. A suíte completa retornou 138 aprovados, 1 falha por falta da dependência `feedparser` na máquina de teste. A dependência é declarada no backend, mas não pôde ser instalada neste ambiente offline. Validar em Docker na máquina de produção.

## Atualizar
```powershell
git pull origin main
docker compose build --no-cache api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
docker compose logs -f worker api
```

Para vídeos antigos que ficaram em PIPELINE_ERROR por esse motivo, retome-os no painel depois do deploy; não apague volumes com `down -v`.
