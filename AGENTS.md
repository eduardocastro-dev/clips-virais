# GTA Studio — instruções para assistentes de desenvolvimento

Estas instruções são para o Codex (assistente de **código**) ao trabalhar neste repositório; não fazem parte dos prompts dos agentes de criação de vídeos e não devem ser enviadas ao OmniRoute.

## Skill de arquitetura

A skill MIT [`untangle-codebase`](.agents/skills/untangle-codebase/SKILL.md) de `caldoai/skills` está instalada em `.agents/skills/` com cópia de compatibilidade em `.claude/skills/`.

- **Só a execute mediante pedido explícito** (por exemplo, `$untangle-codebase backend/pipeline.py backend/media.py backend/assets.py`). O frontmatter original contém `disable-model-invocation: true`.
- Ao ser solicitada, siga a sequência original: perguntar separadamente sobre as opções Comments/Tests; listar problemas e dependências sem alterar código; fazer registro das decisões; refatorar apenas o escopo aprovado; validar comportamento, testes, render e frontend.
- Preserve comportamento funcional, publicação manual, isolamento de contextos, direitos/licenças, limites de custos, assets originais, credenciais e volumes persistentes.
- Nunca execute reset do banco, `docker compose down -v`, reescrita de volumes ou upload/publicação real sem autorização e backup confirmados.

## Diagnóstico solicitado para a evolução v6

Use `docs/REQUISITOS-V6-PIPELINE.md` como requisitos do usuário e `docs/DIAGNOSTICO-V5-E-GUIA-UNTANGLE.md` para o mapa dos componentes. Não reporte como concluída uma funcionalidade apenas por estar descrita ali.

Inspecione primeiro os cinco agentes existentes e as fronteiras entre `backend/pipeline.py`, `backend/personas.py`, `backend/assets.py`, `backend/production_media.py`, `backend/visual_renderer.py`, `backend/media.py`, `backend/audio_mix.py`, `backend/contracts.py`, `backend/integrations.py` e `frontend/app/`.

Antes de mudar o comportamento de render, execute o diagnóstico read-only `python -m backend.diagnose_assets --json` dentro do container API, aponte arquivos/cenas com evidências, depois altere uma unidade de comportamento por vez. Ao final, execute os testes Python, o build Next.js/TypeScript e um smoke FFmpeg com mídias próprias; não invente resultados. Todos os arquivos em `/assets/` pertencem ao usuário e devem ser preservados.

## Skills profissionais do estúdio de vídeo

O estúdio conta com skills especializadas instaladas em `.agents/skills/` e `.claude/skills/`:

| Skill / Agente | Função profissional no estúdio | Escopo principal |
|---|---|---|
| `diretor` | Diretor Executivo de Produção | Limites diários, parada de emergência, governança de tentativas e aprovação |
| `cacador` | Jornalista Investigativo e Curador | Validação de direitos, URLs, extração de fatos confirmados vs. rumores |
| `escritor` | Roteirista Criativo e Dramaturgo | Roteiro vertical 9:16, ganchos nos primeiros 2s, elenco de apresentadores |
| `redator` | Revisor de Texto Fonético | Adaptação para TTS Piper PT-BR, números por extenso, frases sem cortes |
| `editor` | Diretor Técnico de Montagem | TTS, gameplay alternado, avatares, ducking de áudio, preflight técnico |
| `avaliador` | Auditor Chefe de Qualidade | 13 critérios técnicos, evidências obrigatórias e score locking de aprovados |
| `pessoa` | Representante do Público Gamer | 7 perguntas de audiência, identificação de segundo de tédio (`boring_second`) |
| `handoff-compacto` | Protocolo de Passagem de Bastão | Contratos atômicos Pydantic entre agentes, resumos de até 3 linhas |
| `cache-de-dados` | Gestor de Memória e Custos | Cache de metadados e métricas com TTL explícito e invalidação segura |
| `amostragem-de-video` | Técnico de Inspeção Audiovisual | Extração de até 12 frames, probe de container e alinhamento de transcrição |
| `resumo-de-contexto` | Gestor de Memória Operacional | Isolamento de histórico e resumos de até 10 linhas entre agentes |
| `roteamento-de-modelo` | Infraestrutura e Limites de IA | Roteamento por agente no OmniRoute/Ollama, gestão de custos e fallback |
| `saida-enxuta` | Auditoria de Formato e Schemas | Respostas estritamente estruturadas sem preâmbulos, emojis ou alucinações |
| `scripts-deterministicos` | Operador de Automação e FFmpeg | Execução mecânica de conversões, recortes e subprocessos sem gastar LLM |
| `clips-virais-ops` | Operação e Diagnóstico Docker | Gerenciamento de containers, rebuilds seletivos, logs e diagnósticos |
| `untangle-codebase` | Engenharia de Arquitetura | Refatoração estrutural segura sob demanda explícita |
