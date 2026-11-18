# GTA 6 Autonomous Content Studio

Estúdio pessoal self-hosted com painel Next.js, API FastAPI, SQLite WAL e worker persistente. Produz vídeos verticais PT-BR com fontes rastreáveis, cinco etapas especializadas, FFmpeg/Piper e distribuição manual. Upload privado no YouTube é implementado pela API oficial e depende de OAuth e aprovação audiovisual. **YouTube, TikTok e Instagram podem usar o adaptador Postiz configurado; todas as redes têm fila manual. Nenhuma integração foi homologada com contas reais.**

## Iniciar

Pré-requisitos: Docker Desktop em modo Linux, Docker Compose e espaço para imagens/modelos. Recomendado: 4 núcleos, 8 GB de RAM e 10 GB livres. O limite de produção interrompe novas descobertas quando há menos de 2 GB disponíveis.

```powershell
# Uma .env local já foi criada durante a instalação; não a sobrescreva.
# Em uma instalação nova:
Copy-Item .env.example .env
# Edite STUDIO_TOKEN com uma senha aleatória longa.
docker compose up -d --build
docker compose ps
```

Abra [http://localhost:3000](http://localhost:3000). Informe o valor de `STUDIO_TOKEN` da sua `.env`. Não coloque esse token em URLs, commits ou serviços externos. API: [http://localhost:8000/docs](http://localhost:8000/docs). As rotas de dados exigem `Authorization: Bearer <token>`.

O Docker mantém banco, chave criptográfica, handoffs e mídias no volume `clips-virais_studio`. Não execute `down -v` se quiser preservar o histórico. As portas estão vinculadas apenas a `127.0.0.1`. Para servidor remoto, configure HTTPS e acesso privado antes de expor a aplicação.

## Primeira configuração

1. Em **Configurações**, salve nome do canal, limites, duração, países, frequência, retenção e destinos.
2. Configure uma URL compatível com OpenAI, por exemplo `http://host.docker.internal:11434/v1` para Ollama no host. Instale modelos no provedor e informe seus nomes para Escritor e Avaliador. OmniRoute usa a mesma interface. Diretor operacional, Caçador e Editor usam scripts; seus campos de modelo ficam reservados a extensões estratégicas.
3. Salve `llm_api_key` quando o provedor exigir. Configure custo por milhão de tokens conforme sua tabela real. O controle reserva um limite conservador antes de **cada** chamada, incluindo fallback; o painel distingue reserva estimada de tokens reportados pelo provedor.
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

Execute uma instância self-hosted seguindo a documentação oficial ou conecte uma instância que você já usa. Salve a base da API em Configurações (por exemplo `http://host.docker.internal:4007/api/public/v1`) e a credencial `postiz_api_key`. Consulte os canais autorizados e associe cada rede ao seu ID. No assistente oficial do Postiz, exporte as opções específicas de cada rede e preencha o JSON por plataforma. Configure privacidade e permissões reais; a aplicação não inventa opções permitidas pelo TikTok.

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
- Edição por cenas e versões criativas implementadas; não há timeline de arrastar e soltar, catálogo de músicas ou Revideo. Postiz é um adaptador para instância externa, não um serviço embutido no Compose principal.
- Seis templates compartilham o mesmo mecanismo de corte central/cards e fades; não implementam efeitos cinematográficos complexos ou reações com avatar.
- Descoberta YouTube, RSS/Atom e consulta de contas autorizadas TikTok/Instagram implementadas. Não há busca global irrestrita dessas duas redes nem inferência automática de direitos de terceiros.
- Avaliação por amostragem e ASR não garante exatidão factual ou qualidade perceptual; não equivale a revisão integral. O modo textual sempre requer revisão humana.
- Relatórios e sugestões por template são descritivos. Não há otimização estatística de horários ou inferência causal de desempenho.
- Retentativas e limites são conservadores; segredos não são enviados a handoffs. O diretório de logs de mídia pode conter caminhos locais.
- Configuração de pasta de saída usa o volume Docker; o painel não aceita caminhos arbitrários do host. Há migração aditiva das colunas de distribuição no SQLite; não há ferramenta geral de downgrade.

O estado exato da homologação está em [docs/VALIDATION.md](docs/VALIDATION.md). Esta entrega é uma base operacional executável; os limites acima não devem ser apresentados como funcionalidades concluídas.
