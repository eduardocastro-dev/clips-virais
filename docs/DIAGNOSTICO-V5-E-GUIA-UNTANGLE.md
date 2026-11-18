# GTA Studio — untangle-codebase e auditoria preliminar do pipeline

## O que foi instalado

Origem: `caldoai/skills`, arquivo `skills/untangle-codebase/SKILL.md`, branch principal, licença MIT (aviso em `docs/licenses/caldoai-untangle-codebase-LICENSE.txt`).

A skill foi instalada para os assistentes de **desenvolvimento**:

- `.agents/skills/untangle-codebase/SKILL.md` — Codex;
- `.claude/skills/untangle-codebase/SKILL.md` — compatibilidade com Claude Code;
- `AGENTS.md` — orientação para uso e guardrails.

A skill **não** é enviada aos cinco agentes do GTA Studio, não altera modelos/combo `studio-free`, não gera mídia e não executa refatorações de forma silenciosa. O arquivo upstream pede refatoração profunda e começa perguntando se o usuário quer as opções adicionais **Comments** e **Tests**. A invocação precisa ser explícita.

## Como usar no Codex

Abra a pasta `Clips-Virais` como workspace no Codex e envie, por exemplo:

> Use a skill `$untangle-codebase` com foco em `backend/pipeline.py`, `backend/personas.py`, `backend/assets.py`, `backend/visual_renderer.py` e `backend/media.py`. Antes de alterar qualquer código, analise o acoplamento entre personagens, assets, renderização, legendas e avaliação. Use o documento `docs/REQUISITOS-V6-PIPELINE.md` como comportamento desejado. Não execute resets nem edite dados de produção. Mantenha um registro de decisões, faça alterações testáveis e valide TypeScript, Python e FFmpeg.

A skill não substitui a implementação do pedido v6; ela apenas oferece um método para detectar problemas estruturais antes de alterá-los.

## Diagnóstico estático da base v5 do ZIP (não da sua instalação real)

| Área | Evidência do código v5 | Lacuna diante dos requisitos v6 |
| --- | --- | --- |
| Agentes | `backend/pipeline.py`: `AGENTS = ['diretor','cacador','escritor','editor','avaliador']` | O Redator não existe; a IA “Pessoa” também não existe como avaliadora paralela |
| Dossiês | `backend/personas.py`: `PRESETS` para Nico Neon, Dante Palma e Vito Onda | Existem definições textuais, não um elenco com fala por cena |
| Avatar | `get_persona()` lê `persona.image_path` das configurações; `backend/media.py:render()` o usa somente se preenchido | Imagem não é obrigatória; se ausente o render segue sem personagem |
| Arte da persona | O ZIP v5 contém apenas `assets/persona/.gitkeep`, nenhuma imagem de personagem | A referência visual de cada personagem não foi gerada neste pacote |
| Voz | `backend/media.py:narration()` usa `persona.voice_model` ou `PIPER_MODEL` global | Um único modelo é usado na prática; não há atribuição de locutores por cena |
| Cena visual | `backend/assets.py:select_visuals()` escolhe assets com `status=READY`, `rights_status=AUTHORIZED`, `active=1`, `path` válido | Sem um asset elegível a cena recebe `animated_gradient` |
| Render | `backend/visual_renderer.py:montage()` tenta o visual escolhido e, em caso de erro, usa gradiente | O comportamento v6 desejado exige bloquear o render quando faltar gameplay/música/persona |
| Música | `backend/audio_mix.py:mix()` trata música e efeitos como opcionais | Falta bloquear quando não há música autorizada e validar presença na trilha |
| Legendas | `backend/media.py:subtitles()` estima timestamps se não houver transcrição real | Falta tornar alinhamento real obrigatório |
| Avaliação | `backend/pipeline.py:evaluate()` usa um avaliador | Falta a avaliação independente “Pessoa”, travamento de critérios aprovados e diagnóstico audiovisual verificável |

**Limite do diagnóstico:** não há no ZIP o banco SQLite da sua máquina, nem os assets e os renders locais. Não é possível afirmar quais caminhos existem **no seu Docker** ou qual asset foi realmente usado sem consultar aquela instalação. A captura de tela mostra o resultado visual, mas não os caminhos internos.

## Diagnóstico read-only de uma produção real

Depois de aplicar o patch e reconstruir só a API, execute no PowerShell, dentro do projeto:

```powershell
docker compose up -d --build api
docker compose exec api python -m backend.diagnose_assets
```

Para escolher um vídeo específico:

```powershell
docker compose exec api python -m backend.diagnose_assets --video ID_DA_PRODUCAO --json
```

O diagnóstico relata o status do vídeo, renders por tentativa, arquivo do manifesto, arquivo escolhido por cena e se **existe agora**, avatar, modelo de voz e músicas autorizadas. Ele também exibe eventos `VISUAL_FALLBACK`/`PERSONA_IMAGE_MISSING` quando registrados. **Não altera o SQLite nem reprocessa mídia.** O manifesto indica seleção, não prova conclusiva de uso no render final; arquivos temporários podem não existir mais após limpeza normal.

## Ordem recomendada para implementar o pedido v6

1. Rastrear uma produção real com o diagnóstico read-only e confirmar os caminhos.
2. Tornar `assets` a origem única e adicionar rescan/watcher, com direitos explícitos.
3. Adicionar dossiê e asset visual **de cada** personagem, TTS por segmento e opção de ouvir amostra.
4. Centralizar as invariantes de mídia (gameplay, persona, música, prints), removendo fallback visual gradiente **depois** de garantir assets suficientes, com pausa explícita quando faltar insumo.
5. Criar o Redator antes do TTS; guardar texto antes/depois e permitir duas devoluções estruturais.
6. Aplicar verificações determinísticas antes do avaliador e criar segundo avaliador independente “Pessoa”.
7. Revisar reaproveitamento seletivo de critérios: só manter nota “travada” quando nenhuma alteração afetar a evidência correspondente. Se a cena mudar, reavaliar todos os critérios impactados — evitar aceitar nota obsoleta.
8. Executar testes com um vídeo seu de uma cena e só depois habilitar produção diária.

**Atenção:** este pacote instala a skill e o diagnóstico read-only. Não implementa os novos agentes, os novos avatares nem as mudanças de renderização do pedido v6.
