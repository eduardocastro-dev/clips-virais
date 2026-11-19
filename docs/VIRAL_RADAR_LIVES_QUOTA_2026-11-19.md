# Viral Radar Top 20, cortes de lives e cota diária — 19/11/2026

## Meta: não criar outro X
O alvo de **Shorts** vem exatamente de `Configurações → Vídeos por dia` (`settings.daily_limit`). Não há valor `shorts` independente nem padrão em outro lugar. A meta complementar de cortes de lives é **5**. A duração e os ajustes do Piper, o preflight técnico e os direitos do pipeline original não foram alterados.

Arquivos persistidos em `STUDIO_DATA` (`/studio/data`): `daily_quota.json`, `quota_state.json`, `top_creators.json`, `viral_radar_YYYY-MM-DD.json`, `recent_lives.json`, `clipping_allowlist.json`, `rights_log.json`. Os relatórios `reports/daily_report.md`, `reports/quota_report.md` e `reports/viral_radar_YYYY-MM-DD.md` ficam em `STUDIO_FILES`.

## Como funciona
1. O worker agenda mensalmente a atualização do ranking (com tentativas no dia seguinte se falhar). O ranking público serve de ponto de partida; os IDs e inscritos são consultados na **YouTube Data API** antes de constarem como verificados. Nenhum top 20 é inventado se a API/fonte não estiver disponível.
2. O Radar lê apenas vídeos públicos nos últimos 30 dias, sem restrição etária ou geográfica identificada. Mede velocidade de visualizações, engajamento e desvio em relação à mediana dos vídeos recentes do canal. Apenas temas relacionados a GTA entram automaticamente na fila de ideias do pipeline atual, como **referência**, nunca licença de reutilização.
3. A aba **Cortes de Lives** administra `clipping_allowlist.json`: a presença na lista depende de declaração explícita de autorização do operador com evidência de uso. VODs públicos encerrados são verificados novamente na API antes de qualquer download.
4. O worker baixa primeiro **só o áudio**, detecta picos relativos, transcreve e alinha palavras com **WhisperX**, escolhe um momento com contexto e score configurável (60–100; inicial 70), corrige início/fim às frases e solicita somente o trecho escolhido. Para evitar reutilização, bloqueia a mesma live e títulos de tema equivalente usados nos sete dias anteriores.
5. Monta MP4 H.264 1080×1920, 30 fps, fundo desfocado derivado da própria fonte licenciada e imagem integral central, legendas com timestamps reais, normalização de áudio para -14 LUFS (±1). **Rastreamento dinâmico de rostos/locutor do ZIP ainda não foi integrado**; o reenquadramento conservador preserva o quadro original.
6. Após decodificação/metadata e medição do áudio, o corte entra em `REVIEW_PENDING` com miniatura, texto de postagem e fonte. O operador pode aprovar ou descartar no painel. **Nunca é postado automaticamente.** A produção anterior de Shorts permanece no pipeline.
7. Cotas e falhas são persistidas pelo scheduler. O limite de tentativas do item automático é 3; após falha definitiva outro candidato elegível pode ser escolhido. Após o horário limite no fuso São Paulo, o status passa a `PARCIAL` (quando incompleto), com ações no relatório. Nenhuma mídia sem licença ou score baixo é usada para completar números.

## Ativar
1. Atualizar código e reconstruir API/worker/web:
```powershell
git pull origin main
docker compose build --no-cache api worker web
docker compose up -d --force-recreate api worker web
```
2. Em **Configurações → Vídeos por dia**, informe a quantidade de Shorts desejada. Ela será exibida na cota automaticamente. Configure a chave **YouTube Data API** (somente leitura) nas integrações; a descoberta Top 20 não funciona sem ela.
3. Para habilitar WhisperX no worker, adicione `INSTALL_WHISPERX=1` no `.env` e reconstrua **o worker**, em ambiente com espaço e RAM suficientes:
```powershell
docker compose build --no-cache worker
docker compose up -d --force-recreate worker
docker compose exec worker python -c "import whisperx; print('WhisperX OK')"
```
A instalação de WhisperX é propositalmente opcional no Docker porque inclui dependências grandes de PyTorch; se ausente, nenhum corte é colocado em produção e o painel mostra o motivo, sem inventar timestamps.
4. Abra **Viral Radar** e atualize o top 20. Abra **Cortes de Lives**, informe os IDs de canais e suas permissões verificáveis. Configure deadline e score mínimo.
5. Ative o modo automático do Studio. A cota utiliza o valor já salvo de `settings.daily_limit` para Shorts e cinco cortes adicionais, somente com candidatos legítimos e licença.

## Limitações explicitadas
- O top 20 atual não foi preenchido neste commit: depende de consulta dinâmica na API com a chave do operador. Se o ranking público mudar de estrutura, o job pode falhar conservadoramente e o relatório não inventará a lista.
- O ZIP enviado (`cortes-de-live(1).zip`) foi auditado. Reaproveitamos a estratégia de áudio primeiro, pontuação por sinais, limites de frases e montagem vertical. Os scripts originais tinham opções de cookies/login; essas opções **não foram integradas** para preservar a regra de acesso público.
- O rastreamento automático do rosto do streamer e leitura de replay de chat ainda não foram implementados; candidatos de corte usam áudio/transcrição. O modo conservador de enquadramento evita cortar o vídeo integral horizontal.
- Sem VODs autorizados recentes, sem API, sem WhisperX ou sem score mínimo, a cota permanece incompleta: isso é uma salvaguarda, não um bug contornável por baixar fontes não autorizadas.
- A validação do Piper só se aplica a vídeos que tenham narração sintetizada. Cortes da fala original da live não inventam uma trilha Piper nem passam a ser atribuídos ao narrador do GTA Studio.
- `rights_log.json` registra verificação, uso e falhas dos candidatos efetivamente analisados; canais sem autorização ficam fora do download.
- Testes de regressão adicionados em `tests/test_live_quota_radar.py`. Uma compilação/execução completa em Docker com chave YouTube, modelos de ASR e VOD autorizado **ainda não foi realizada neste ambiente**.

## Validação segura
```powershell
docker compose --profile test run --rm tests python -m pytest -q tests/test_live_quota_radar.py
docker compose logs -f worker api
```
A imagem do perfil de testes não instala o WhisperX por padrão, pois os testes de unidade não fazem inferência real nem downloads.
Não execute `docker compose down -v` para atualizar: dados e estado da cota estão em volume persistente.
