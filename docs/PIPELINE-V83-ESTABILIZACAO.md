# GTA Studio — Estabilização v8.3 do pipeline (sem apagar dados)

## Fase 1: mapa conferido na base v8.2

| Etapa | Entrada | Saída validada / handoff | Consumidor |
| --- | --- | --- | --- |
| Diretor | settings e limite de produção | `diretor.json` | Caçador |
| Caçador | URL, fonte, permissões | `cacador.json`, fatos/metadados | Escritor |
| Escritor | fatos, fonte, duração/template, elenco, orçamento da voz | `Script` Pydantic, `script.json` | Redator |
| Redator | `Script`, voz, metas de palavras e feedback | `Script` revisado, `redator-attempt-*.json` | Editor/TTS |
| Editor/TTS | `Script`, assets licenciados, Piper e FFmpeg | MP4 + áudio/transcrição/manifesto | Avaliador |
| Avaliador e Pessoa | MP4 renderizado, frames, transcrição | vereditos independentes, `video_attempts` | Diretor e Video Studio |

Prompts: `agents/{diretor,cacador,escritor,redator,editor,avaliador,pessoa}/system.md`, complementados nos payloads de `backend/pipeline.py` e `backend/redator.py`.

Contrato: `backend/contracts.py` (`Scene.source_start` de 0 a 600 segundos; `Script.music='none'`, cenas contíguas). Não foi relaxado.

## Fase 2: causas identificadas

1. `backend/storyboard.py` normalizava timestamps, mas também **apagava palavras** após um limite suposto de 2,15 palavras/s. A voz Piper nunca era medida antes desse corte. Isso explica parte da narração curta e a dificuldade de expansão posterior.
2. `backend/pipeline.py`, função `write_script()`, não informava ao Escritor qual fonte local havia sido obtida, sua duração real nem a unidade de `source_start`. O modelo retornava valores como 1025 ou 1520. O `source_start` é **segundo de origem**, não frame nem milissegundo. O teto de 600 provém tanto de `backend/contracts.py` quanto de `backend/highlights.py:MAX_SOURCE_SECONDS`.
3. `Script.music` proíbe seleção direta de música por nome sem catálogo licenciado, mas o prompt não explicitava `music='none'`. A trilha autorizada é selecionada de modo separado por `backend/audio_mix.py`.
4. O Redator inicial não recebia uma meta de **palavras ligada à voz instalada**. O ajuste tardio já usava duração real do TTS, porém sem enviar ao modelo o delta explícito em palavras e segundos.
5. `backend/highlights.py` calculava cortes usando a duração integral da fonte mesmo quando a análise só examinava os primeiros 600 segundos.

## Fase 3: alterações localizadas

- `backend/storyboard.py`: preserva a narração; mantém tempo contínuo; força música para `none` com registro antes da validação; limita `source_start` à fonte local real (e ao teto de 600) ou usa zero quando não há vídeo-fonte disponível; registra toda correção em handoff.
- `backend/narration_budget.py` (novo): mede uma amostra **real** de Piper por voz/velocidade, cacheia a taxa em `cache/voice_calibration/`, e calcula faixas de palavras. Se não houver Piper, o fallback é rotulado como estimado, não validado como medição.
- `backend/pipeline.py`: envia ao Escritor a duração local, unidade, limite e orçamento de voz. Continua usando o mesmo número de tentativas, com Pydantic estrito após a sanitização.
- `backend/redator.py`: envia a meta inicial por cena; em correção medida, mostra segundos, taxa real e delta de palavras. Preserva as exigências de fatos e a estrutura do roteiro.
- `backend/highlights.py`: cortes só dentro dos primeiros 600s efetivamente analisados; não altera `MAX_SOURCE_SECONDS`.
- `backend/validate_three_runs.py` (novo): diagnóstico somente de leitura de três produções reais (MP4, `Script`, linha do tempo).

Nenhum segredo, banco, dado da biblioteca, vídeo ou modelo de voz está neste patch. Não foi alterado o módulo de avaliação nem o frontend.

## Fase 4: testes

Executados neste ambiente: **127 testes Python passaram**, incluindo 9 testes novos de contrato e 3 casos distintos com saída simulada do modelo na etapa de roteiro/Redator. `feedparser` não estava instalado aqui, portanto foi utilizado um substituto local mínimo para a suíte de testes; ele **não é incluído** no patch.

**Não homologado neste ambiente:** três pipelines completos reais com OmniRoute + Piper + download e FFmpeg. A tentativa de render offline com assets sintéticos encontrou a limitação de alternância de clipes da versão atual e não terminou dentro da janela local de execução. Não declarar 38–40 segundos reais nem MP4s aprovados sem a execução no Docker.

## Instalação no Windows (PowerShell)

1. Backup da pasta atual e especialmente do `.env`, `assets`, `models`, `data` e volumes.
2. Extraia o ZIP do patch na raiz de `Clips-Virais` **sem substituir** `.env` e pastas persistentes.
3. Execute:

```powershell
docker compose up -d --build api worker

docker compose exec api python -m backend.doctor

docker compose --profile test run --rm tests
```

4. Gere 3 vídeos reais de **temas diferentes** pelo Video Studio, sem publicação automática. Monitore no painel a duração da voz medida e os handoffs `briefing-fixes-*.json` e `redator-attempt-*.json`.
5. Verifique os últimos 3:

```powershell
docker compose exec api python -m backend.validate_three_runs --latest 3
```

O diagnóstico imprime JSON e retorna exit code 1 se faltar vídeo, se o `Script` falhar, se a narração sair do orçamento ou se o MP4 não existir/não for válido. **É somente leitura.**

## Decisões preservadas / riscos

- O teto `source_start <= 600` continua obrigatório e não foi ampliado.
- `music` no `Script` continua `none`; música de fundo só pode vir de asset autorizado por `audio_mix`.
- Nenhum filtro inventa fatos. Se a fonte não fornecer informação suficiente para preencher a duração, o pipeline deve apresentar o problema real em vez de repetição ou tempo artificial.
- A calibração de uma amostra Piper é uma aproximação editorial; a decisão final usa a voz e os timestamps reais do vídeo.
- A base pode ainda falhar se houver apenas um gameplay selecionável, pois o algoritmo atual evita repetir consecutivamente o mesmo asset. Isso está fora dos três erros solicitados e não foi mascarado.
