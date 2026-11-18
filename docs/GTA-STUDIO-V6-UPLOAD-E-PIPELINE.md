# GTA Studio v6 — correção de upload + melhorias do pipeline

## Instalar sem apagar seus dados

1. Faça backup da pasta atual `Clips-Virais`.
2. Extraia o **patch** na raiz do projeto, substituindo os arquivos de código. **Não sobrescreva `.env`, `models/`, `assets/`, `temp/`, `data/` ou volumes Docker.**
3. PowerShell: `docker compose up -d --build api worker web`.
4. Verifique: `docker compose ps` e `docker compose exec api python -m backend.doctor`.
5. Abra `http://localhost:3000` e tente **Retomar** com o mesmo arquivo que falhou em 99%. Se o `.part` ainda existir e corresponder ao fingerprint, o upload é retomado da posição já recebida.
6. Para diagnóstico somente de leitura: `docker compose exec api python -m backend.diagnose_assets --json`.
7. Novos testes: `docker compose --profile test run --rm tests python -m pytest -q tests/test_v6_upload_and_agents.py`.

**Não execute `docker compose down -v`, não apague `/studio/temp/uploads` nem exclua arquivos `.part` anteriores antes de retomar.**

## Corrigido no upload

`backend/uploads.py` (`finish`, `promote_across_volumes`, `create_session`): o upload antes executava `os.replace(<temp mount>, <assets mount>)`, que falha com `[Errno 18] Invalid cross-device link`. Agora copia com buffer de 4 MiB para arquivo staging **dentro do diretório de destino**, sincroniza com disco, valida tamanho e faz o último rename **no mesmo volume**. A origem temporária só é apagada depois que o destino estiver completo. Se já existir arquivo com o mesmo nome, não será sobrescrito. Sessões `FAILED` com `.part` íntegro podem ser retomadas. Usuário precisa dispor de espaço livre para staging.

## Estrutura

- `/assets/gameplay/`: gameplays próprias/autorizadas.
- `/assets/music/`: trilhas com licença/autorização.
- `/assets/sfx/`: efeitos sonoros.
- `/assets/personas/dante_palma/avatar.png`, `/assets/personas/lia_varela/avatar.png`, `/assets/personas/caio_rivas/avatar.png`: referências visuais originais. Cópia inicial a partir de `templates/personas/...` sem substituir arquivos do usuário.
- `/assets/images/`, `/assets/shorts/`, `/assets/clips/`, `/assets/uploads/`: demais originais e derivados.
- `/temp/<id_producao>/`: cópias para edição temporária.
- `/videos/final/<id>/attempt-NN.mp4`: renders de tentativas.
- `/handoff/<id>/`: fatos da fonte, roteiros, revisão do Redator, avaliação, manifestos de assets.

A **Biblioteca de assets** tem botão `Reescanear /assets`; o Worker faz varredura por polling a cada ~30 s. Arquivos novos entram com `REVIEW_REQUIRED` e só podem ser usados mediante autorização/licença; a simples presença de arquivos não presume direitos. Vídeos longos continuam sendo fatiados em clipes derivados, preservando original.

## Pipeline

- Cinco papéis anteriores: **Diretor** (orquestra), **Caçador** (pesquisa), **Escritor** (roteirista), **Editor** (render), **Avaliador** (qualidade técnica e de fontes).
- Sexto papel: **Redator** (revisa texto para locução; `backend/redator.py`), registra mudanças antes/depois e usa sua própria rota no OmniRoute, herdando o modelo do Escritor se não houver configuração anterior.
- Revisão da **Pessoa**: segunda chamada de IA, independente e paralela ao Avaliador; esta é uma segunda perspectiva dentro da avaliação e não um sétimo agente orquestrador. Tem rota `pessoa` editável em Configurações, por padrão herda a rota do Avaliador.
- Elenco de três papéis originais: **Dante Palma** (apresentador), **Lia Varela** (analista), **Caio Rivas** (repórter). Dossiês em `backend/personas.py`; configuração por personagem no banco (`kv.cast`), imagens em `/assets/personas/`, modelos Piper em `/models/*.onnx`. Se usar somente uma voz instalada, os personagens não terão timbres independentes; você deve apontar arquivos `.onnx` diferentes para essa finalidade.
- Cada cena pode marcar `speaker`; o render sobrepõe o avatar correspondente durante a fala. Narração usa modelo Piper da persona selecionada. Cache reutiliza áudio e trechos visuais idênticos em novas tentativas.
- Todo render real exige **gameplay, música e avatar**. Se faltar material licenciado, a produção fica `PAUSED_MISSING_ASSETS` e o painel mostra os diretórios necessários, com ação `Reescanear e retomar` sem consumir tentativa do Avaliador.
- O fundo gradiente/neon automático foi removido do caminho de produção. Quando a captura de notícia falhar, ainda pode aparecer um **cartão de manchete** sobre gameplay, sem esconder a origem da informação.
- Fonte é classificada inicialmente como alegação da fonte ou rumor; nunca é chamada de fato confirmado somente pela matéria. `backend/facts.py` salva um inventário em `handoff/<id>/facts.json`.
- Antes da avaliação real, são usadas narração transcrita por Faster Whisper com timestamps por palavra, ffprobe e validações determinísticas. Falhas de insumo suspendem a produção como `PAUSED_VALIDATION`, sem reprovar cinco vezes por erro técnico.
- Avaliador e Pessoa retornam notas separadas com evidência. Critérios sem evidência concreta não reprovam automaticamente. A aprovação é por nota mínima de cada critério (a média não decide). O painel exibe `Problema → Evidência → Correção` sem duplicar o texto.

## Limitações ainda pendentes

- **Não é feito envio nativo de MP4 para a API de modelos de vídeo.** O OmniRoute atual recebe frames JPEG, transcrição e metadados técnicos. Portanto, não é correto dizer que as IAs assistiram/escutaram o arquivo completo. A checagem de áudio, vídeo, resolução e sincronismo é local.
- A revisão cirúrgica economiza trabalho quando o áudio e os segmentos visuais ficam idênticos. **Ainda não há preservação perfeita de todos os critérios aprovados quando o conteúdo muda**, nem garantia de refazer exclusivamente uma cena em todo caso. Reavaliar dependências alteradas é necessário para evitar nota desatualizada.
- Diferentes **timbres** dependem de modelos Piper reais instalados e licenciados; apenas mudar velocidade não cria timbres próprios.
- As capturas Playwright de notícias e imagens de terceiros dependem de acesso ao site, licença e termos de uso. Não haverá download que contorne autenticação, paywall ou DRM.
- Este ambiente não dispõe do Docker da máquina do usuário nem de todas as dependências de build do Next.js; homologar `npm run build` no Docker do usuário. Um teste sintético local de FFmpeg e os testes novos passaram.

## Como testar

1. Na aba **Upload de mídia**, selecione novamente o arquivo que falhou em 99% e clique **Retomar**. Observe progresso de 99% a 100%, arquivo em `assets/uploads/video` e clipes derivados em `assets/clips/<id>/`.
2. Coloque dois arquivos de gameplay próprios em `assets/gameplay/`, uma música com licença em `assets/music/` e abra **Biblioteca de assets → Reescanear**. Complete as licenças dos materiais novos na Biblioteca.
3. Confira os três personagens em **Configurações**. Clique **Ouvir amostra**; para vozes diferentes informe um arquivo `.onnx` distinto para cada personagem, montado em `/models`.
4. Importe uma notícia de fonte permitida e acompanhe um vídeo de 10–30 s. Veja o registro de fatos, personagens por cena e manifestos em `handoff/<id>`.
5. No Video Studio, verifique MP4 antes da avaliação, avatar durante falas, gameplay de fundo, música, prints/cartão da notícia e histórico de tentativas com **Avaliador** e **Pessoa**.
6. Faça o teste sem música ou sem gameplay: a produção deve pausar com erro claro, sem gerar gradiente e sem consumir as cinco tentativas. Reponha os assets, autorize na Biblioteca e retome.
7. Consulte `docker compose logs --tail=100 worker` em caso de erro. Não remova volumes para corrigir problemas de código.
