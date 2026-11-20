# Viral Radar e cortes manuais sem YouTube Data API — 2026-11-19

## Decisão do operador

**Nenhuma funcionalidade de pesquisa, metadados, ranking ou corte de lives exige YouTube Data API key.**
O banco pode continuar contendo uma chave previamente cadastrada; ela é ignorada pelos novos fluxos. Não é necessário revogá-la para usar o Radar.

## Descoberta de temas
- O Radar original de Shorts, vídeos e fontes RSS continua funcionando sem API.
- O módulo Top 20 consulta uma página de ranking pública e tenta identificar canais via seus IDs UC, quando visíveis e verificáveis.
- Canais informados manualmente podem ser adicionados pelo ID UC, mesmo quando um ranking público não estiver acessível.
- A busca considera Shorts, vídeos e lives públicas de cada canal, consultando metadados acessíveis anonimamente via `yt-dlp` **sem baixar os vídeos**.
- **Janela: últimos 30 dias**. Privados, não listados, exclusivos, restritos por idade, antigos ou com dados públicos insuficientes são descartados.
- Métricas indisponíveis geram `score: null`, nunca curtidas/visualizações inventadas. Assim, o Top 20 pode ficar parcial.

## Nova aba Cortes de Lives
1. Acesse **Cortes de Lives → Enviar link de live para corte**.
2. Cole uma URL pública de VOD encerrado: `https://www.youtube.com/live/VIDEO_ID`, `https://www.youtube.com/watch?v=VIDEO_ID` ou `https://youtu.be/VIDEO_ID`.
3. Caso ainda não tenha registrado a permissão do titular, preencha no mesmo formulário o comprovante de licença/autorização de reutilização (não basta o vídeo ser público).
4. O GTA Studio consulta metadados sem API, verifica o ID do canal, publicação em até 30 dias, status `was_live`, acesso público e direitos cadastrados.
5. Após aprovação do preflight, o job é enfileirado para WhisperX, escolha do trecho, edição e revisão humana.
6. Sem acesso público aos metadados ou sem licença, nenhuma mídia é baixada; o motivo é exibido no painel.

**WhisperX continua sendo dependência opcional do worker** para legendas alinhadas de cortes. O upload final para YouTube, TikTok e Instagram permanece **manual**, sem OAuth e sem YouTube Data API.

## Integração e implantação

```powershell
git pull origin main
docker compose build api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
```

Os testes `tests/test_public_youtube_no_api.py` verificam a ausência de exigência de credenciais, URLs permitidas, restrições de privacidade, janela de 30 dias, cadastro manual e envio de URL. Não removemos a chave de um banco já existente nem substituímos validações de direitos.

### Limitações externas

É possível que o YouTube bloqueie metadados públicos para consultas anônimas, que os números públicos não incluam todas as métricas ou que uma página de ranking mude de formato. Nesses casos, o Radar mostra status parcial/indisponível e você pode informar URLs específicas. O GTA Studio **não usa cookies, login nem tenta contornar restrições**.
