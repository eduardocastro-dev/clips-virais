# GTA 6 Studio — Radar multifuentes e cortes automáticos (2026-11-18)

## O que mudou

- **YouTube Shorts primeiro**: usa a aba Shorts/pesquisa filtrada no YouTube via yt-dlp, sem token de IA.
- **YouTube comum em segundo**: consulta vídeos de GTA 6, trailers, gameplay e canais monitorados via descoberta pública; vídeos longos voltam a ser exibidos.
- **Notícias/RSS em seguida**: feeds Google News pt-BR/en-US, notícias oficiais da Rockstar localizadas pelo Google News e feeds HTTPS adicionados pelo usuário. O botão *Pesquisar no YouTube* também coloca fontes RSS habilitadas na fila; o agendador consulta cada feed no intervalo salvo.
- **TikTok/Instagram**: continuam aceitando links diretos como referência; monitoramento de perfis exige token oficial com acesso à própria conta, conforme limitações dos provedores.
- **Publicação 100% manual**: o módulo de envio automático continua desabilitado; você revisa o MP4 e os metadados antes de postar.

## Edição de gameplay autorizado com mais de 45 segundos

Quando a fonte está marcada `AUTHORIZED`, com evidência registrada, a aplicação pode baixar a mídia dentro dos limites existentes. Se o arquivo tiver mais de **45 segundos**:

1. Aplica o teto de **45s** ao vídeo final, inclusive se o usuário selecionou uma duração maior.
2. Analisa a trilha de vídeo **localmente** por transições de cena com FFmpeg.
3. Extrai até oito quadros leves e grava timestamps em `handoff/<id>/highlights.json`.
4. Se a transcrição local estiver habilitada, usa **Faster Whisper** para obter trechos de fala com tempo; sem essa dependência ou se for gameplay silencioso, segue normalmente.
5. O Escritor, conectado ao **OmniRoute**, recebe essa análise para criar um roteiro original e sugerir `source_start` para cada cena. **Se o modelo do Escritor aceitar visão e a opção estiver ligada**, recebe até três quadros como apoio visual.
6. `fit_cuts()` valida os intervalos, impede trechos sobrepostos e seleciona alternativas usando as detecções de cena se necessário. Grava `handoff/<id>/highlight-edl.json`.
7. O Editor recorta os segmentos com FFmpeg, monta **um Short vertical contendo múltiplos trechos**, insere narração Piper e legendas. O relatório do Editor registra a EDL para auditoria.

**Limite importante:** seleção de destaques não é uma classificação infalível dos melhores momentos da gameplay. Sem transcrição ou visão multimodal, a escolha fica baseada sobretudo em mudanças de cena e distribuição temporal. Este fluxo produz **um vídeo montado por ciclo**, não vários posts independentes. Variantes adicionais podem ser solicitadas pelo editor existente, respeitando o limite diário.

## Direitos e fatos

- Descobrir um vídeo público **não** concede licença para baixar, recortar ou republicar a mídia.
- Shorts e vídeos de terceiros sem licença permanecem `REFERENCE_ONLY`: a IA escreve narrativa própria e o editor gera telas e elementos gráficos originais. Se não houver material visual autorizado, **não** há extração de gameplay do YouTube.
- Notícias e rumores devem ser distinguíveis. A origem e o motivo das afirmações devem constar no roteiro, sem tratar postagens especulativas como anúncio da Rockstar.
- Nenhuma integração com Postiz, TikTok, Instagram ou YouTube publica automaticamente.

## Instalação

1. Faça cópia da pasta, especialmente `.env`, `models` e quaisquer bancos de dados do volume Docker.
2. Extraia o ZIP patch na raiz da instalação atual, substituindo os arquivos correspondentes. **Não** substitua `.env` nem a pasta `models`.
3. Em PowerShell, dentro de `Clips-Virais`:

```powershell
docker compose up -d --build api worker web
docker compose ps
docker compose exec api python -m backend.doctor
```

4. No GTA Studio: **Viral Radar → Pesquisar no YouTube**. Notícias/RSS são consultadas no mesmo comando e também por agendamento; é possível cadastrar novos feeds em *Fontes RSS e notícias*.
5. Para uma edição de gameplay com mais de 45s, importe um link e informe a evidência de licença/reutilização. Opcionalmente, em **Configurações → Avaliação audiovisual**, marque a opção de visão do Escritor se o modelo escolhido suportar imagens.
6. Veja os registros `handoff/<id>/highlights.json` e `handoff/<id>/highlight-edl.json`; confirme o resultado no **Video Studio**, baixe o MP4 e publique manualmente.

## Verificações realizadas neste ambiente

- **62 testes Python locais passaram**, utilizando um substituto de parser RSS porque `feedparser` não estava instalado aqui. Isso não substitui uma execução real da integração RSS.
- Teste funcional real de **FFmpeg** em vídeo sintético de 60 segundos confirmou a detecção de mudanças aos 20 e 40 segundos e a extração de quadros.
- Compilação dos módulos Python e verificação de sintaxe TSX concluídas.
- **Não homologado:** acesso real ao YouTube/TikTok/Instagram no Docker do usuário, inferência multimodal com os modelos de sua conta, renderização de um Short completo com Piper no Windows e atualização da aplicação já em execução.

## Notas de recursos

- Descoberta/FFmpeg/Whisper local **não consomem tokens do OmniRoute**. Escritor e Avaliador utilizam tokens quando invocados; habilitar visão no Escritor aumenta o consumo por chamada.
- O Docker instala as dependências do pacote recebido. O Faster Whisper é opcional e pode baixar seu modelo na primeira execução.
- Os jobs do Postiz herdados continuam inativos e os dados não são apagados por este patch.
- A busca por Shorts e os canais do YouTube usam endpoints públicos que podem mudar ou impor limite; a falha de uma fonte não concede permissão para contornar controles de acesso.
