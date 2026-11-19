# Modo simplificado: pesquisa + edição + publicação manual

**Esta edição usa o OmniRoute existente, RSS gratuito e pesquisa pública de vídeos para criar MP4 e metadados. Não inicia Postiz nem publica nas redes.** Consulte [docs/MODO-MANUAL.md](docs/MODO-MANUAL.md) antes da atualização. A documentação antiga abaixo é histórica e pode mencionar serviços opcionais já removidos da pilha ativa.

---

# GTA 6 Autonomous Content Studio

Estúdio pessoal self-hosted com painel Next.js, API FastAPI, SQLite WAL e worker persistente. Produz vídeos verticais PT-BR com fontes rastreáveis, cinco etapas especializadas, FFmpeg/Piper e distribuição manual. Upload privado no YouTube é implementado pela API oficial e depende de OAuth e aprovação audiovisual. **YouTube, TikTok e Instagram podem usar o adaptador Postiz configurado; todas as redes têm fila manual. Nenhuma integração foi homologada com contas reais.**

## Iniciar — pacote Docker integrado

Pré-requisitos: Docker Desktop com containers Linux / Docker Compose v2. O conjunto integrado Postiz + Temporal/Elasticsearch + OmniRoute é mais pesado que o estúdio isolado: recomendo 4 CPUs, 12–16 GB de RAM e espaço livre de pelo menos 20 GB, conforme volume de mídias.

```powershell
# Na pasta do projeto (PowerShell). Não é necessário copiar .env.example:
.\start.ps1
# Linux:
# sh start.sh

docker compose ps
docker compose logs --tail=80 bootstrap
# Diagnóstico das chaves e endpoints, sem publicar:
docker compose exec api python -m backend.doctor
```

O instalador cria `.env` com segredos aleatórios e preserva valores existentes. **Nunca versionar nem compartilhar `.env`**. Acesse Estúdio em http://localhost:3000 (token `STUDIO_TOKEN` no `.env`), Postiz em http://localhost:4007 e OmniRoute em http://localhost:20128. Postiz e OmniRoute recebem usuários/senhas locais pelo bootstrap, mas autorização OAuth das redes e conexão a provedores de IA ainda são manuais.

**Se você já iniciou a versão com PostgreSQL e Redis separados por aplicação:** não suba a nova topologia diretamente. O instalador procura os containers antigos e bloqueia o start até realizar a migração. Consulte [docs/MIGRATION.md](docs/MIGRATION.md) e execute `python scripts/migrate_shared.py` na pasta original, com os volumes antigos intactos.

Portas expostas somente em loopback. Para VPS, use túnel SSH e um proxy HTTPS devidamente configurado antes de abrir OAuth/callbacks. **Não execute `docker compose down -v`** em ambiente com dados importantes.

## Primeira configuração

1. Em **Configurações**, salve nome do canal, limites, duração, países, frequência, retenção e destinos.
2. Na instalação integrada, a URL do provedor é configurada automaticamente para `http://omniroute:20128/v1`; conecte as contas no painel do OmniRoute e crie o combo `studio-free` com modelos aprovados/sem custos. Em instalação independente, configure uma URL compatível com OpenAI, por exemplo `http://host.docker.internal:11434/v1` para Ollama no host. Instale modelos no provedor e informe seus nomes para Escritor e Avaliador. OmniRoute usa a mesma interface. Diretor operacional, Caçador e Editor usam scripts; seus campos de modelo ficam reservados a extensões estratégicas.
3. O instalador gera uma `llm_api_key` restrita ao combo `studio-free` e salva criptografada; use a configuração manual apenas se conectar um provedor diferente. Configure custo por milhão de tokens conforme sua tabela real. O controle reserva um limite conservador antes de **cada** chamada, incluindo fallback; o painel distingue reserva estimada de tokens reportados pelo provedor.
4. Coloque uma voz Piper **PT-BR** e seu `.onnx.json` em `models/`, após verificar sua licença. Ajuste `PIPER_MODEL` em `.env` e recrie API/worker. Nenhuma voz é baixada silenciosamente. Verifique o CLI Piper com `docker compose exec worker piper --help`.
5. Opcional: habilite Faster Whisper e visão no Avaliador. Whisper baixa o modelo `small` no primeiro uso para o cache do volume. A URL de IA receberá frames se você habilitar visão. Sem esses recursos, a saída exige revisão humana.
6. Gere um **teste técnico**. Ele usa texto e sinal de áudio sintéticos, não gasta tokens e nunca é publicado automaticamente.
7. Para descoberta, salve uma `youtube_api_key` com YouTube Data API v3 habilitada. Cadastre perfis e inicie uma consulta.
8. Ative o modo automático depois que os componentes necessários estiverem configurados. A fila e o agendamento persistem após reinícios.

## Operação

**Importar por URL:** cole um link direto de YouTube, TikTok ou Instagram; selecione template, duração, instruções e direitos. `AUTHORIZED` exige evidência. `REFERENCE_ONLY` produz texto/visuais próprios sem baixar a mídia. `REVIEW_REQUIRED` e `BLOCKED` impedem processamento. URL desconhecida nunca vira autorizada. No Instagram, consulte primeiro o perfil da conta profissional conectada pela API Meta; o importador usa os metadados observados nessa consulta.

**Viral Radar:** busca YouTube por GTA 6, alternando o país configurado por janela de tempo. A nota combina visualizações/hora, recência e engajamento; não inclui uma média histórica do canal quando ela não está disponível. Perfis YouTube aceitam `@handle` ou `/channel/ID`. TikTok e Instagram consultam somente a conta autorizada pelos tokens configurados; a identidade retornada precisa corresponder ao perfil cadastrado. Nada contorna autenticação. Feeds RSS/Atom públicos podem ser cadastrados no Radar; artigos sobre GTA 6 entram como referências, sem download de mídia.

**Video Studio:** selecione um vídeo para pré-visualizar/baixar MP4 e inspecionar roteiro e handoffs. Os seis templates têm paleta, fonte, enquadramento central e fades configurados; ajuste cores e tamanho da legenda no painel. Abra **Editar briefing / criar uma nova versão** para alterar textos, narração, timestamps e início dos cortes da fonte. Cada versão tem novos handoffs, passa pelo pipeline e mantém o original. É um editor de cenas, sem timeline visual de arrastar e soltar. A similaridade bloqueia cópias cosméticas.

**Publicações:** o calendário apresenta intenção editorial, agendamentos confirmados e publicações. Cada rede tem uma linha independente. A fila manual gera vídeo e JSON em `output/<rede>/<data>/`. Baixe o vídeo no Studio, publique pela plataforma e registre a URL correspondente. Os arquivos pendentes não são apagados. Vídeos sintéticos são marcados `TESTE` e não podem receber confirmação de publicação real.

**Agentes:** consulte jobs, tentativas e erros; pause jobs ainda não executando ou reexecute depois de corrigir a causa. Há três tentativas técnicas com backoff. Revisões criativas são limitadas a duas, além da versão inicial. A parada de emergência impede novas etapas e envios; não encerra à força o FFmpeg já em execução.

**Notificações:** eventos são sempre registrados no painel. Para Telegram configure `telegram_token` e `telegram_chat_id`; para e-mail, `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `smtp_to`. SMTP usa STARTTLS. Entregas incertas são registradas, sem reenvio automático potencialmente duplicado. A homologação não envia mensagens reais.

**Analytics:** armazena snapshots reais de views/likes/comments disponíveis na API YouTube. Retenção, CTR, compartilhamentos e crescimento permanecem `null` quando não disponíveis. Totais usam somente a observação mais recente de cada publicação. Há gráfico comparativo por template. O Postiz preserva também as séries originais por data; não confunda seu total por período com um contador vitalício. Com pelo menos três observações por template, o Diretor sugere o próximo experimento de formato e usa essa sugestão nas novas descobertas, sem afirmar causalidade. Relatórios em `reports/YYYY-MM-DD.md`, também acessíveis pelo painel, têm até 30 linhas.

## Conectar redes

### YouTube

Pesquisa e métricas usam API key. Upload usa OAuth: crie um projeto Google Cloud, ative YouTube Data API, configure o consentimento e obtenha um refresh token para sua própria conta com escopo `https://www.googleapis.com/auth/youtube.upload`. Salve `youtube_client_id`, `youtube_client_secret`, `youtube_refresh_token`; alternativamente use um access token de curta duração. Este aplicativo **não implementa o fluxo interativo de consentimento OAuth**.

Habilite upload automático e modo de aprovação automática no painel. O envio só ocorre para vídeo real, aprovado, sem bloqueios de direitos, com visão e transcrição validadas. Os uploads são **privados**. A API pode impor quotas e restrições de auditoria. Um upload só vira `PUBLICADO` após receber ID da plataforma; isso confirma armazenamento privado, não disponibilidade pública. Se houver resposta ambígua, reconcilie no YouTube antes de qualquer repetição. Jobs recuperados não repetem uploads em `PUBLICANDO`.

### TikTok e Instagram

Publicação manual operacional e adaptador Postiz para envio/agendamento nas contas conectadas. TikTok oEmbed coleta metadados públicos quando disponível. Para consultar a própria conta TikTok, configure `tiktok_access_token` com `user.info.profile` e `video.list`; para a conta Instagram profissional via Facebook Login, configure `instagram_access_token` e `instagram_user_id`. A identidade retornada precisa corresponder ao perfil. Consulta arbitrária de terceiros continua sujeita às limitações oficiais. Não há navegador automatizado, cookies extraídos ou contorno de bloqueios.

### Postiz

A instalação integrada inclui Postiz e tenta registrar o administrador local automaticamente. Você também pode conectar uma instância externa se preferir. Para instalações externas, salve a base da API em Configurações (por exemplo `http://host.docker.internal:4007/api/public/v1`) e a credencial `postiz_api_key`. Consulte os canais autorizados e associe cada rede ao seu ID. No assistente oficial do Postiz, exporte as opções específicas de cada rede e preencha o JSON por plataforma. Configure privacidade e permissões reais; a aplicação não inventa opções permitidas pelo TikTok.

Após revisão manual, use **Planejar / enviar pelo Postiz** na publicação. O horário salvo sozinho é apenas planejamento editorial; **Enviar ao Postiz** faz upload e agenda. Para operação autônoma, habilite Postiz automático e avaliação automática com visão/transcrição. Receber `postId` muda o estado para `AGENDADO`; somente `PUBLISHED` com URL válida muda para `PUBLICADO`. A reconciliação roda a cada cinco minutos; a coleta de métricas usa cache de seis horas. Há limite conservador de 30 chamadas por hora.

Timeout após envio conserva `PUBLICANDO` e não repete o POST. Revise o Postiz e confirme a URL quando necessário. Parada local impede novos envios, mas **não cancela agendamentos já aceitos pelo Postiz**; cancele-os na instância externa. Veja [contratos dos conectores](docs/INTEGRATIONS.md).

## Arquitetura e arquivos

```text
backend/
  api.py            endpoints autenticados e configuração
  core.py           SQLite, fila, cache, segredos, handoffs atômicos
  contracts.py      schemas Pydantic e validação de URLs
  integrations.py   YouTube, TikTok oEmbed, modelos compatíveis
  distribution.py   Postiz: mídia, agendamento, reconciliação, métricas
  sources.py        RSS/Atom e contas TikTok/Instagram autorizadas
  pipeline.py       cinco etapas, revisões, publicação e relatórios
  media.py          Piper, Whisper, FFmpeg, ffprobe e amostragem
  worker.py         scheduler, leases, backoff, retenção, notificações
frontend/app/       painel Next.js/TypeScript/Tailwind e proxy same-origin
agents/            identidades e instruções estáveis dos cinco agentes
templates/         seis presets de renderização
.agents/skills/    sete skills canônicas Codex
.claude/skills/    referências às mesmas skills, sem cópia das instruções
tests/             testes com mocks externos e render real no Docker
scripts/           geração de skills, inventário de licenças, homologação
docs/              requisitos originais, plano, licenças e validação
```

Handoffs ficam isolados por vídeo em `handoff/<id>/`, incluem `run_id` e seguem schema comum. Cada chamada de modelo começa sem histórico compartilhado e recebe apenas o payload preparado pela etapa; modelos não têm ferramentas de filesystem. Os cinco agentes são módulos no mesmo processo de worker, **não contêineres de segurança separados**. SQLite usa transações `BEGIN IMMEDIATE` para claim e cota diária; leases têm heartbeat. Um único worker é o deployment suportado.

Skills: `handoff-compacto`, `resumo-de-contexto`, `cache-de-dados`, `scripts-deterministicos`, `amostragem-de-video`, `roteamento-de-modelo`, `saida-enxuta`. Consulte [licenças e escolhas técnicas](docs/LICENSES.md).

## Testes e manutenção

```powershell
docker compose --profile test build tests
docker compose --profile test run --rm tests
docker compose logs --tail 100 api worker
docker compose restart api worker
```

Localmente: Python 3.13, `pip install -r backend/requirements.txt -r backend/requirements-dev.txt`, FFmpeg/ffprobe no PATH e `python -m pytest -q`. O teste de render fica explicitamente ignorado se as ferramentas não existirem. Frontend: `cd frontend`, `npm ci`, `npm run build`.

Backup: preserve o volume inteiro, inclusive `data/secrets.key`, com os serviços parados. Essa chave permite descriptografar credenciais; proteja o backup. Não compartilhe `.env`, banco ou chave. Limpeza automática remove somente mídia elegível dentro das pastas controladas, preservando registros, fontes e handoffs.

## Limites atuais

- Homologação externa exige suas credenciais e autorização; nenhum upload real é realizado nos testes.
- Edição por cenas e versões criativas implementadas; não há timeline de arrastar e soltar, catálogo de músicas ou Revideo. Postiz e OmniRoute já são serviços embutidos no Compose principal; versões anteriores exigem migração de dados.
- Seis templates compartilham o mesmo mecanismo de corte central/cards e fades; não implementam efeitos cinematográficos complexos ou reações com avatar.
- Descoberta YouTube, RSS/Atom e consulta de contas autorizadas TikTok/Instagram implementadas. Não há busca global irrestrita dessas duas redes nem inferência automática de direitos de terceiros.
- Avaliação por amostragem e ASR não garante exatidão factual ou qualidade perceptual; não equivale a revisão integral. O modo textual sempre requer revisão humana.
- Relatórios e sugestões por template são descritivos. Não há otimização estatística de horários ou inferência causal de desempenho.
- Retentativas e limites são conservadores; segredos não são enviados a handoffs. O diretório de logs de mídia pode conter caminhos locais.
- Configuração de pasta de saída usa o volume Docker; o painel não aceita caminhos arbitrários do host. Há migração aditiva das colunas de distribuição no SQLite; não há ferramenta geral de downgrade.

O estado exato da homologação está em [docs/VALIDATION.md](docs/VALIDATION.md). Esta entrega é uma base operacional executável; os limites acima não devem ser apresentados como funcionalidades concluídas.


## Radar multifuentes e clipes automáticos de gameplay

O radar voltou a mostrar **YouTube Shorts (prioridade máxima), vídeos comuns do YouTube e notícias/RSS**, além de perfis conectados e links diretos de outras redes quando autorizados. Para mídia com licença registrada e mais de 45s, FFmpeg detecta cenas, o Escritor do OmniRoute seleciona timestamps para cortes e o Editor monta um Short de no máximo 45s. Veja [docs/RADAR-MULTIFONTES-E-CLIPES.md](docs/RADAR-MULTIFONTES-E-CLIPES.md). Publicação permanece manual.

## Reset e Avaliador v3 (2026-11-18)

Antes de excluir as produções, consulte [docs/RESET-AVALIADOR-V3.md](docs/RESET-AVALIADOR-V3.md).
A nova rotina de backup está em `backup-producoes.ps1` e **não executa reset**.
O Studio passou a preservar renders por tentativa, exibir avaliação completa, configurar 12 critérios e permitir até 5 tentativas com decisão manual.

## GTA Studio v4: biblioteca / mídia temporária / persona

A atualização v4 preserva o modo de postagem manual. Consulte [docs/MIDIA-TEMP-PERSONA-V4.md](docs/MIDIA-TEMP-PERSONA-V4.md) para migração dos assets, requisitos do Playwright, 3 personas, permissões, testes e retenção. Atenção: copie arquivos antigos de `/studio/assets` antes de ativar os bind mounts `./assets` e `./temp`.

---

## V5 — Upload de mídia e fatiamento de vídeos longos

O software continua **100% com publicação manual**. Sem Postiz e sem OAuth para
publicar. Todos os arquivos utilizados na montagem precisam ter autorização.

### Atualização de uma instalação existente

1. Faça backup da pasta do projeto e mantenha seu `.env`, `models/`, `assets/`,
   `temp/` e volumes Docker. Não execute `docker compose down -v`.
2. Extraia o **patch V5** na raiz de `Clips-Virais`, sobrescrevendo apenas o código.
3. No PowerShell, execute:

   ```powershell
   docker compose up -d --build api worker web
   docker compose exec api python -m backend.doctor
   docker compose logs --tail=80 worker
   ```

4. Abra `http://localhost:3000` → **Upload de mídia**. Selecione múltiplos arquivos
   ou arraste arquivos para a área indicada. Informe categoria, tags, classificação
   da origem e evidência da licença. Um arquivo sem evidência permanece **pendente
   de direitos**, portanto não é utilizado automaticamente na edição.
5. Acesse **Biblioteca de assets** para visualizar mídia, clipes agrupados,
   progresso de fatiamento, filtros, ativação/desativação e autorização. A exclusão
   do original com seus clipes exige confirmação explícita.
6. Em **Configurações**, ajuste: duração mínima para dividir (45s), tamanho dos
   clipes (10s), último trecho mínimo (3s), tamanho máximo de upload (1024 MB)
   e volume da música (0,12 por padrão). Alterações de tamanho não processam
   novamente arquivos já fatiados.

### Como funciona o processamento

- Vídeos de até 45s são mantidos inteiros. Os maiores entram em uma tarefa
  assíncrona `split:<id>` executada pelo Worker, com FFmpeg H.264 reencodado e
  áudio AAC (quando presente). A proporção original é preservada.
- Exemplo: 51 segundos → 10 + 10 + 10 + 10 + 11 segundos.
- Mídias provenientes de Shorts, Viral Radar e importação por URL **só são
  baixadas e fatiadas quando houver direitos de uso registrados**. A pesquisa
  por si só guarda metadados, não copia vídeos privados ou sem autorização.
- O upload usa blocos de 4 MB com deslocamento verificado no servidor. Se a
  conexão cair, selecione o mesmo arquivo e clique **Retomar**; os blocos já
  confirmados permanecem em disco. O servidor rejeita offsets incompatíveis.
- O Studio identifica duplicatas pelo hash SHA-256 completo do arquivo.
  Duplicatas reutilizam a entrada existente sem sobrepor direitos/metadados.
- Na montagem, o Editor alterna trechos de aproximadamente 3s, prioriza
  categorias/tags que coincidam com a cena e menor contagem de uso. Jamais
  repete o mesmo clipe em dois cortes consecutivos; quando não há alternativa,
  usa um fundo próprio. Clipes do mesmo vídeo pai são evitados quando possível.
- Música e efeitos são opcionais; FFmpeg normaliza a narração, reduz a música
  quando há fala (ducking) e usa um limiter na mistura final. Áudio original
  e arquivos da biblioteca não são modificados.
- Trechos de terceiros exigem autorização, recebem crédito visível e ficam
  limitados a **5 segundos totais por produção** e até 4 segundos por trecho.
  O Studio não ultrapassa esse teto automaticamente.
- O manifesto `handoff/<id>/visual-assets-attempt-<n>.json` registra cena,
  asset/clipe, ID pai, origem, classificação, duração e caminho de trabalho;
  ele aparece na pré-visualização por tentativa.

### Pastas do projeto

| Pasta | Conteúdo |
|---|---|
| `assets/uploads/video/` | Originais MP4, MOV, WEBM e MKV enviados |
| `assets/uploads/audio/` | Originais MP3, WAV e M4A |
| `assets/uploads/image/` | Imagens PNG, JPG, WEBP e GIF |
| `assets/uploads/font/` | TTF/OTF |
| `assets/uploads/subtitle/` | Legendas SRT |
| `assets/uploads/logo/` | Logos |
| `assets/clips/<id-pai>/` | Derivados `clip_001.mp4`, `clip_002.mp4` etc. |
| `temp/uploads/` | Arquivos de upload parcial; limpeza de sessões antigas |
| `temp/<id-producao>/` | Cópias de trabalho temporárias |
| `videos/final/<id>/` | MP4 renderizado por tentativa |

### Testes direcionados

```powershell
# Executa a suite existente e os novos testes no Docker (sem publicar vídeos)
docker compose --profile test run --rm tests

# Se o vídeo de 51 segundos terminar, procure cinco derivados na Biblioteca
# Abra Video Studio para ver a origem de cada corte no manifesto da cena.
```

**Limitações:** a retomada é ao selecionar novamente o mesmo arquivo no mesmo
navegador; não é sincronizada entre dispositivos. O banco registra progresso
em blocos e os arquivos parciais são removidos após a retenção configurada.
O build de frontend e o end-to-end dentro do Docker precisam ser verificados
na máquina do usuário antes de operar de modo automático.

## Skill Codex `untangle-codebase` (auditoria de arquitetura)

O repositório inclui a skill MIT `caldoai/skills/untangle-codebase` para **assistentes de desenvolvimento**. Use-a sob demanda no Codex (`$untangle-codebase`); ela não é um modelo OmniRoute e não roda automaticamente com as produções. Consulte `docs/DIAGNOSTICO-V5-E-GUIA-UNTANGLE.md` para diagnóstico de assets, comandos e requisitos da futura evolução v6.

### Atualização v7: vozes, poses e alinhamento

Leia `docs/ENTREGA-V7-AUDIO-VOZES-POSES.md`. Depois de instalar o patch:

```powershell
python scripts/install_voices.py
docker compose up -d --build api worker web
docker compose exec worker python -m backend.doctor_audio
docker compose exec api python -m backend.voice_samples
docker compose exec api python -m backend.retry_audio_errors
```

Os pesos Piper não acompanham o ZIP. Os 72 PNGs das poses e os manifestos acompanham a atualização. A narração usa duração **real medida** e a margem de cinco segundos é editável em Configurações.

## Elenco — assets de narradores incluídos

Esta distribuição inclui as 24 poses de Dante Palma, Lia Varela e Caio Rivas,
com manifests e avatares instaláveis no volume `assets/personas/`.
As poses foram derivadas de folhas 4×6 fornecidas pelo criador, não de artes
individuais nativas de 1024px. Consulte `docs/ASSETS-NARRADORES.md`.
Para sincronizar o volume local do Docker: `docker compose exec api python -m backend.persona_assets`.

