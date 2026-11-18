# GTA 6 Studio — Edição manual (sem Postiz)

Esta versão **não faz login em redes sociais, não agenda e não publica**.
O processo de pesquisa e edição continua self-hosted, utilizando OmniRoute já conectado.

## O que mudou

- Docker Compose inicia API, Worker, Web, Bootstrap, OmniRoute e Redis (serviço de testes fica no profile `test`).
- Postiz, Temporal, Elasticsearch e PostgreSQL não fazem mais parte da pilha ativa. **Nenhum volume antigo é apagado.**
- A chave de IA (`llm_api_key`) permanece no volume `studio`. A configuração existente do OmniRoute permanece no volume `omniroute-data`.
- O bootstrap desabilita qualquer configuração anterior de upload automático e cria dois feeds gratuitos do Google News (inglês e português) de modo idempotente.
- O botão **Viral Radar → Pesquisar tendências** enfileira pesquisa pública do YouTube (yt-dlp) e consulta dos RSS cadastrados, sem precisar de APIs Google/Meta/TikTok. Pesquisa pública do YouTube pode falhar ou trazer resultados parciais, sujeitos às políticas das plataformas.
- Roteiros de referência usam apenas metadados e resumo disponível; não presumem direitos de uso do vídeo original. Para editar vídeos de terceiros, comprove a autorização de reutilização.
- Vídeos aprovados são enviados **somente** à fila local, em `output/{youtube,tiktok,instagram}/YYYY-MM-DD/`, com MP4 e `metadata_<id>.json` (título, descrição, hashtags, créditos, avaliação). São apresentados no painel para baixar. Dados de publicações manuais anteriores são preservados.
- A avaliação audiovisual ainda depende de ferramentas/modelos de visão/transcrição ou da sua revisão humana. Os vídeos de teste sintético **não** substituem a validação de IA.

## Atualizar a instalação do Windows sem perder dados

1. Pare a produção automática no painel e aguarde jobs em execução finalizarem.
2. Faça backup da pasta atual, do `.env` e, idealmente, do volume `studio` com seu SQLite e `secrets.key`. Anote o nome atual do projeto Compose. **Não execute `down -v`, `docker volume prune` ou `docker compose up --remove-orphans`.**
3. Extraia os arquivos atualizados **por cima** da pasta atual, preservando `.env`, `models/` e seus volumes Docker. O ZIP não contém credenciais.
4. No PowerShell, execute:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
docker compose ps
docker compose exec api python -m backend.doctor
```

5. Confirme o Estúdio em `http://localhost:3000` e o OmniRoute em `http://localhost:20128`.
6. Os containers antigos do Postiz podem continuar como órfãos. **Após conferir que esta versão funciona**, você pode pará-los sem excluir volumes:

```powershell
$project = (docker compose config --format json | ConvertFrom-Json).name
$antigos = @('postiz','postgres','temporal','temporal-elasticsearch','postiz-postgres','postiz-redis','temporal-postgresql','omniroute-redis')
foreach ($svc in $antigos) {
  $ids = @(docker ps -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=$svc")
  if ($ids.Count -gt 0) { docker stop $ids }
}
```

Os containers ficam parados, mas seus volumes e dados antigos permanecem intactos para possível rollback.

## Usar

1. **Configurações**: confirme provedor `http://omniroute:20128/v1`, modelo `studio-free`, chave de inferência e os limites diários.
2. **Viral Radar → Pesquisar tendências**: o Caçador consulta publicações públicas e RSS. Notícias são fontes de **referência**, não licença para reutilizar mídias.
3. **Viral Radar → Criar vídeo**: escolha uma notícia; o Escritor usa OmniRoute para gerar roteiro original em PT-BR, o Editor renderiza os cards e narração, o Avaliador verifica as condições implementadas.
4. **Video Studio**: revise qualidade e fatos, baixe o MP4 e os metadados JSON de cada rede.
5. **Prontos para postar**: publique manualmente em cada aplicativo e, se desejar, cole a URL publicada para registrar histórico.

## Limitações atuais

- Google News RSS pode retornar manchetes com contexto insuficiente. Verifique os fatos antes de publicar. Eventos e teorias não viram notícias confirmadas por ter sido gerado um vídeo.
- `yt-dlp` faz pesquisa e metadados de melhor esforço, sem SLA nem autorização de reutilização. Mudanças das plataformas podem quebrar o acesso. Sem Google API key, dados públicos podem não conter visualizações, retenção ou séries históricas: pontuação de viralidade ficará indisponível em alguns resultados.
- TikTok/Instagram não têm coleta livre e estável de perfis de terceiros; links são aceitos como fontes, mas alguns podem não oferecer metadados sem autenticação oficial.
- O Editor usa cartões tipográficos e narração sintética quando só há texto. **Não gera gameplay real**, imagens inéditas de GTA VI nem material oficial por si só. Edição de imagens/vídeos depende de mídia própria/autorizada.
- O modelo Piper PT-BR configurado em `PIPER_MODEL` precisa existir em `models/` para a narração real; o teste sintético funciona sem voz.
- Integração de tendências pelo Google Trends/Trends Python foi considerada, mas não incluída para não adicionar uma dependência não oficial e instável à versão simples.
- Este ZIP foi validado estruturalmente e com testes locais disponíveis, mas não foi homologado com Docker e plataformas externas neste ambiente.
