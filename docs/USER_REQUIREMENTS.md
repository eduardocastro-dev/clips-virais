# MASTER PROMPT — GTA 6 AUTONOMOUS CONTENT STUDIO

## PAPEL

Você é um arquiteto de software sênior, engenheiro de IA, especialista em sistemas multiagentes, automação de mídias sociais, processamento de vídeo e infraestrutura Docker.

Sua missão é desenvolver um **ecossistema autônomo e self-hosted de produção, edição, análise e publicação de vídeos curtos sobre GTA 6**, utilizando ferramentas open source, agentes especializados e arquitetura modular.

O projeto será utilizado exclusivamente por uma pessoa. Não é um SaaS.

**Objetivo principal:** depois da configuração inicial, o sistema deverá pesquisar tendências, selecionar oportunidades, produzir vídeos em português brasileiro, avaliar a qualidade, publicar nas plataformas autorizadas, acompanhar resultados e iniciar novos ciclos automaticamente.

A intervenção humana deve ser excepcional: autenticações exigidas, problemas técnicos irrecuperáveis ou publicação manual obrigatória.

---

# 1. PRINCÍPIOS OBRIGATÓRIOS

1. Priorizar ferramentas open source e soluções self-hosted.
2. Utilizar Docker Compose para executar os serviços.
3. Implementar o sistema para uso exclusivamente pessoal.
4. Não desenvolver módulos de SaaS, pagamentos, assinaturas ou gestão de clientes.
5. Não exigir acervo permanente de vídeos.
6. Trabalhar com arquivos temporários e excluir materiais intermediários após o processamento e a retenção necessária.
7. Preservar o histórico de vídeos, métricas, fontes, configurações e publicações.
8. Evitar operações manuais repetitivas.
9. Oferecer um painel web moderno e responsivo.
10. Manter agentes independentes com responsabilidades bem definidas.
11. Utilizar scripts determinísticos para tarefas mecânicas, economizando tokens de IA.
12. Implementar recuperação de falhas, cache, logs, notificações e monitoramento.
13. Não publicar conteúdo sem permissões de uso adequadas.
14. Nunca inventar métricas, notícias, permissões ou status de publicação.
15. Não contornar bloqueios, limitações de autenticação ou mecanismos de segurança das redes sociais.

**Atenção:** o projeto deve resultar em uma aplicação funcional, não apenas documentação, pseudocódigo ou protótipos visuais.

---

# 2. FUNCIONAMENTO AUTÔNOMO

O usuário realiza uma configuração inicial:

- Conecta suas contas sociais.
- Configura o provedor de IA.
- Define idioma, estilo e identidade visual.
- Determina quantidade máxima de vídeos por dia.
- Escolhe duração, formatos e templates.
- Configura fontes de pesquisa e perfis monitorados.
- Define regras de direitos de uso e aprovação.
- Configura notificações.
- Ativa o modo automático.

Depois disso, o sistema inicia ciclos recorrentes de produção sem exigir novos comandos.

## Fluxo principal

```text
INÍCIO DO CICLO
      |
      v
DIRETOR
Planeja a produção diária
      |
      v
CAÇADOR
Pesquisa tendências e coleta fontes
      |
      v
ESCRITOR
Produz roteiro e briefing
      |
      v
EDITOR
Produz o vídeo final
      |
      v
AVALIADOR
Verifica qualidade e conformidade
      |
      +---- REVISAR ----> ESCRITOR
      |                  |
      |                  v
      |                 EDITOR
      |                  |
      |                  v
      |                AVALIADOR
      |
      | Máximo 2 revisões
      |
      v
DIRETOR
Consolida resultado
      |
      v
SERVIÇO DE PUBLICAÇÃO
      |
      +-- API autorizada --> PUBLICAÇÃO
      |
      +-- API indisponível --> FILA MANUAL
      |
      v
COLETA DE MÉTRICAS
      |
      v
RELATÓRIO E NOVO CICLO
```

O Diretor coordena os processos, mas não executa as responsabilidades especializadas dos outros agentes.

A distribuição, autenticação, armazenamento, agendamento e coleta mecânica de métricas devem ser realizadas por serviços convencionais, sem criar agentes adicionais desnecessários.

---

# 3. EQUIPE DE CINCO AGENTES ESPECIALIZADOS

Cada agente deve ter:

- Identidade e instruções de sistema próprias.
- Responsabilidade única.
- Contexto de execução isolado.
- Permissão para acessar somente arquivos necessários.
- Entradas e saídas estruturadas.
- Limites de execução e orçamento de tokens.
- Tratamento de falhas.
- Contrato de handoff.

Agentes não devem compartilhar histórico de conversa.

A comunicação ocorre exclusivamente por arquivos JSON ou Markdown estruturados.

## AGENTE 1 — DIRETOR

**Papel:** orquestrador, planejador e comunicador.

### Missão

Gerenciar a operação diária, definir prioridades, coordenar os agentes e acompanhar o crescimento do canal.

### Entradas

- Configurações do sistema.
- Metas diárias.
- Histórico de publicações.
- Estatísticas disponíveis das plataformas.
- Relatórios do Avaliador.
- Resultados de ciclos anteriores.

### Responsabilidades

1. Iniciar e encerrar ciclos de produção.
2. Determinar a quantidade de vídeos do dia.
3. Definir prioridades temáticas.
4. Orientar o Caçador com base no desempenho anterior.
5. Coordenar os agentes na sequência correta.
6. Controlar limites diários.
7. Tratar exceções e reprovações.
8. Acionar o serviço de publicação após aprovação.
9. Acompanhar publicações pendentes.
10. Consolidar estatísticas.
11. Recomendar ajustes para o próximo ciclo.
12. Produzir relatório diário resumido.

### Saída

`reports/YYYY-MM-DD.md`

Máximo de 30 linhas contendo:

- Quantidade de oportunidades encontradas.
- Vídeos produzidos.
- Vídeos aprovados.
- Vídeos reprovados e motivos.
- Publicações concluídas.
- Publicações manuais pendentes.
- Métricas principais.
- Erros relevantes.
- Prioridades do próximo dia.

### Restrições

O Diretor não pesquisa diretamente, não baixa vídeos, não escreve roteiros, não edita e não avalia materiais.

Ele coordena os módulos responsáveis.

---

## AGENTE 2 — CAÇADOR

**Papel:** pesquisador de tendências e coletor de mídias.

### Missão

Encontrar conteúdos relacionados a GTA 6 com elevado potencial de interesse e crescimento.

### Fontes

- YouTube e Shorts.
- TikTok.
- Instagram e Reels.
- Fontes oficiais da Rockstar.
- Notícias verificáveis sobre GTA 6.
- Perfis cadastrados manualmente.
- Links enviados pelo usuário.

### Países de pesquisa prioritários

- Estados Unidos.
- Reino Unido.
- Canadá.
- Austrália.

O conteúdo final será localizado para português brasileiro.

### Critérios de classificação

- Visualizações.
- Velocidade de crescimento.
- Engajamento.
- Recência.
- Popularidade do tema.
- Relevância para GTA 6.
- Potencial de adaptação para PT-BR.
- Novidade em relação ao histórico do canal.
- Disponibilidade de materiais com direitos de reutilização.

Criar pontuação de viralidade de 0 a 10.

Não considerar que número absoluto de visualizações significa necessariamente tendência.

Quando possível, comparar o desempenho com a média histórica do canal de origem.

### Temas de monitoramento

- Notícias oficiais.
- Trailers.
- Teorias da comunidade.
- Detalhes escondidos.
- Comparações com GTA V.
- Personagens.
- Mecânicas de gameplay.
- Mapas e cenários.
- Rumores claramente identificados.
- Reações e assuntos populares.

### Coleta

Utilizar conectores de plataformas e yt-dlp quando tecnicamente permitido e houver autorização de uso.

Classificar cada fonte como:

- `AUTHORIZED`: reutilização confirmada.
- `REFERENCE_ONLY`: referência para pesquisa ou roteiro original.
- `REVIEW_REQUIRED`: direitos não verificados.
- `BLOCKED`: material inadequado ou não autorizado.

Não transformar um status desconhecido em autorizado.

### Saídas

```text
videos/raw/<id>.mp4
handoff/cacador.json
```

O arquivo JSON deve conter:

- id.
- URL.
- Plataforma.
- Perfil de origem.
- Título.
- Métricas disponíveis.
- Nota de viralidade.
- Duração.
- Motivo da escolha.
- Status dos direitos.
- Evidência da autorização, quando aplicável.
- Créditos e atribuições exigidos.
- Próximo agente.

Para materiais exclusivamente referenciais, guardar metadados e informações permitidas para pesquisa, sem encaminhar a mídia para republicação.

### Restrições

O Caçador não escreve roteiros nem edita vídeos.

Respeitar o limite máximo diário definido pelo Diretor.

---

## AGENTE 3 — ESCRITOR

**Papel:** roteirista e diretor criativo de edição.

### Missão

Transformar uma oportunidade identificada em um roteiro original e um briefing técnico de edição.

### Entradas

- Handoff do Caçador.
- Transcrição.
- Frames amostrados.
- Metadados.
- Instruções manuais, quando existirem.
- Resultados de avaliações anteriores.

### Responsabilidades

1. Compreender o assunto.
2. Verificar informações importantes.
3. Diferenciar notícias confirmadas de rumores.
4. Criar roteiro em PT-BR.
5. Definir o gancho dos primeiros três segundos.
6. Determinar cortes e timestamps.
7. Preparar textos de tela.
8. Definir ritmo.
9. Especificar legendas.
10. Definir narração.
11. Escolher template.
12. Selecionar trilha com direitos adequados.
13. Criar CTA quando pertinente.
14. Preparar título, descrição e hashtags.
15. Indicar a origem de cada elemento visual necessário.

Se a fonte for `REFERENCE_ONLY`, desenvolver um vídeo original a partir do tema, usando materiais cuja utilização seja permitida.

Não produzir uma cópia disfarçada de tradução ou pequenas alterações cosméticas.

### Saída

`handoff/escritor_<id>.md`

O briefing deverá conter:

- Identificação.
- Objetivo.
- Duração.
- Gancho.
- Roteiro.
- Materiais autorizados.
- Lista numerada de alterações.
- Timestamps.
- Transições.
- Legendas.
- Narração.
- Template.
- Música.
- CTA.
- Metadados de publicação.

Cada alteração deverá informar:

`timestamp | ação | parâmetros | motivo`

O Editor deve conseguir executar as instruções sem precisar inventar decisões criativas.

### Restrições

O Escritor não renderiza nem edita o vídeo.

---

## AGENTE 4 — EDITOR

**Papel:** executor técnico da edição.

### Missão

Transformar o briefing do Escritor em um vídeo final pronto para distribuição.

### Tecnologias

- FFmpeg.
- ffprobe.
- Revideo.
- Faster Whisper.
- Piper TTS.
- Bibliotecas auxiliares open source.

### Responsabilidades

1. Carregar os materiais autorizados.
2. Aplicar cortes.
3. Reorganizar segmentos.
4. Converter vídeos para formato vertical.
5. Ajustar enquadramento.
6. Criar narração PT-BR.
7. Sincronizar áudio e imagem.
8. Adicionar legendas animadas.
9. Aplicar efeitos.
10. Criar títulos e sobreposições.
11. Ajustar volumes.
12. Utilizar templates.
13. Exportar versões necessárias.
14. Registrar a execução do briefing.

### Padrões iniciais

- Resolução: 1080 × 1920.
- Proporção: 9:16.
- Formato: MP4.
- Codec de vídeo: H.264.
- Áudio: AAC.
- Idioma: PT-BR.
- Duração: configurável.
- Qualidade: adequada às plataformas de destino.

### Saídas

```text
videos/final/<id>.mp4
handoff/editor_<id>.json
```

O handoff deve registrar:

- Itens executados.
- Itens ignorados.
- Falhas.
- Duração final.
- Resolução.
- Codec.
- Tamanho do arquivo.
- Local do vídeo.

### Restrições

O Editor não altera a estratégia criativa.

Ambiguidades devem retornar ao Escritor, por handoff.

---

## AGENTE 5 — AVALIADOR

**Papel:** controle de qualidade e conformidade.

### Missão

Garantir que somente vídeos tecnicamente válidos, consistentes e com permissões adequadas avancem para distribuição.

### Entradas

- Vídeo final.
- Briefing do Escritor.
- Checklist do Editor.
- Registros de origem e direitos.

### Checklist

Avaliar de 0 a 10:

1. Qualidade do gancho.
2. Clareza da narrativa.
3. Qualidade do áudio.
4. Sincronização das legendas.
5. Qualidade dos cortes.
6. Ritmo.
7. Resolução e proporção.
8. Duração.
9. Aderência ao briefing.
10. Originalidade.
11. Exatidão das informações.
12. Direitos e créditos.

Os critérios de direitos de uso, integridade técnica e conformidade devem funcionar como bloqueios obrigatórios, independentemente da nota geral.

### Vereditos

- `APROVADO`.
- `REVISAR`.
- `REPROVADO`.

Nota mínima de aprovação configurável, inicialmente 8/10.

### Revisões

Se o resultado for `REVISAR`:

1. Gerar lista objetiva de correções.
2. Devolver ao Escritor.
3. Encaminhar novo briefing ao Editor.
4. Executar nova avaliação.

Permitir no máximo duas revisões por vídeo.

Se o problema persistir, escalar ao Diretor.

### Economia de tokens

Não analisar todos os frames.

Utilizar:

- Transcrição.
- Frames-chave.
- Amostragem temporal.
- ffprobe.
- Detecção de silêncio.
- Verificações determinísticas.

### Saída

`handoff/avaliador_<id>.json`

Registrar notas, veredito, falhas e correções necessárias.

---

# 4. CONTRATO DE HANDOFF

Todos os agentes devem seguir o mesmo contrato.

Campos obrigatórios:

```json
{
  "id": "video_001",
  "status": "CONCLUIDO",
  "proximo_agente": "editor",
  "resumo": "Briefing de edição concluído.",
  "arquivos": [
    "handoff/escritor_video_001.md"
  ]
}
```

Regras:

1. Handoffs compactos, idealmente com até 40 linhas.
2. O resumo deve ter no máximo três linhas.
3. Não incluir transcrições completas.
4. Não compartilhar históricos de conversa.
5. Não enviar logs completos entre agentes.
6. Referenciar arquivos grandes somente pelo caminho.
7. Cada agente acessa apenas arquivos necessários à própria função.
8. Utilizar identificadores únicos por vídeo e por execução.
9. Gravar handoffs de forma atômica para evitar leituras parciais.
10. Validar JSON contra schemas definidos.
11. Registrar falhas sem improvisar soluções fora da responsabilidade do agente.

Quando necessário, utilizar um índice compacto em `handoff/cacador.json` e arquivos individuais por vídeo.

---

# 5. SKILLS DE OTIMIZAÇÃO DE TOKENS

Criar sete skills reutilizáveis.

O projeto deve funcionar prioritariamente com Codex.

Utilizar a estrutura de skills reconhecida pelo Codex, em `.agents/skills/`, e disponibilizar compatibilidade com `.claude/skills/` quando aplicável, evitando duplicações divergentes.

## Skill 1 — handoff-compacto

Padronizar entrada e saída entre agentes.

Proibir compartilhamento de históricos e materiais brutos desnecessários.

## Skill 2 — resumo-de-contexto

Ao final de cada etapa, produzir um resumo de até 10 linhas.

Descartar contexto intermediário antes de iniciar o próximo subagente.

## Skill 3 — cache-de-dados

Implementar cache com TTL para:

- Estatísticas de canais.
- Resultados de pesquisa.
- Perfis monitorados.
- Vídeos analisados.
- Tendências.
- Consultas repetidas.

Evitar buscas redundantes.

## Skill 4 — scripts-deterministicos

Utilizar scripts para:

- Download autorizado.
- FFmpeg e ffprobe.
- Conversão.
- Transcrição.
- Extração de frames.
- Coleta de métricas.
- Manipulação de arquivos.
- Agendamento e publicação.
- Limpeza de temporários.

A IA deve receber apenas resumo, resultado e erros relevantes.

## Skill 5 — amostragem-de-video

Extrair frames-chave com intervalo configurável.

Usar transcrições e metadados para reduzir processamento.

## Skill 6 — roteamento-de-modelo

Permitir configurar modelos diferentes por agente:

- Modelo econômico: Caçador.
- Modelo intermediário: Escritor.
- Modelo econômico ou scripts: Editor.
- Modelo mais capaz: Avaliador em casos complexos.
- Modelo mais capaz: Diretor em decisões estratégicas.

Suportar roteamento por capacidade, custo e disponibilidade, sem exigir nomes específicos de modelos.

Integrar Ollama e permitir provedores compatíveis com APIs externas, incluindo OmniRoute quando configurado.

Implementar fallback, limites de custo, controle de tokens e tratamento de rate limits.

## Skill 7 — saida-enxuta

Padronizar respostas curtas e estruturadas.

Proibir explicações longas e repetição de briefings nas comunicações internas.

### Boas práticas

- Cada `SKILL.md` deve ter aproximadamente 100 linhas ou menos.
- Detalhes adicionais ficam em arquivos de referência.
- Carregar referências somente quando necessário.
- Manter prompts de sistema estáveis para favorecer caching.
- Não recriar tarefas que possam ser executadas por scripts.

---

# 6. MODOS DE ENTRADA DE CONTEÚDO

Implementar três modos independentes.

## Modo A — Descoberta automática

O Caçador pesquisa vídeos e tendências internacionais sobre GTA 6.

Os vídeos são classificados e encaminhados ao pipeline conforme a política de direitos de uso.

## Modo B — Importação de vídeo por URL

O usuário poderá inserir diretamente o link de um vídeo do:

- YouTube.
- TikTok.
- Instagram.

O sistema deverá:

1. Identificar a plataforma.
2. Validar a URL.
3. Obter metadados disponíveis.
4. Verificar condições de acesso e direitos.
5. Baixar a mídia quando autorizado.
6. Exibir uma prévia quando possível.
7. Permitir informar instruções personalizadas.
8. Encaminhar ao Escritor e Editor.
9. Gerar o resultado final.
10. Publicar ou disponibilizar para publicação manual.

Exemplos de comandos:

- "Transforme em um Short de 30 segundos."
- "Traduza e crie uma narração original em PT-BR."
- "Adicione legendas dinâmicas."
- "Crie uma versão mais cinematográfica."
- "Extraia três ideias para vídeos curtos."
- "Utilize esse vídeo como referência e produza uma versão original."
- "Aplique o template GTA News."

O sistema deverá distinguir solicitações para editar mídias autorizadas daquelas para usar vídeos de terceiros apenas como referência.

## Modo C — Monitoramento de perfis

Permitir cadastrar links de perfis e canais das três plataformas.

O usuário poderá:

- Adicionar perfil.
- Remover perfil.
- Ativar ou desativar monitoramento.
- Definir frequência de consulta.
- Consultar vídeos recentes.
- Ordenar conteúdos por viralidade.
- Selecionar conteúdos para análise.
- Solicitar edição de conteúdos autorizados.
- Definir perfis prioritários.

A seleção deve poder ocorrer manualmente ou por critérios automáticos.

Não utilizar mecanismos para contornar controles de acesso das plataformas.

---

# 7. VIDEO STUDIO E TEMPLATES

Desenvolver um sistema de edição baseado em templates reutilizáveis.

Templates iniciais:

1. GTA News — notícias rápidas.
2. GTA Theory — teorias e curiosidades.
3. GTA Comparison — comparações.
4. GTA Cinematic — estilo cinematográfico.
5. GTA Facts — fatos e detalhes.
6. GTA Reaction — comentários e análises.

Cada template deverá definir:

- Tipografia.
- Paleta de cores.
- Estilo de legendas.
- Transições.
- Animações.
- Enquadramento.
- Posicionamento de textos.
- Efeitos visuais.
- Identidade do canal.

Permitir modificar parâmetros pelo painel.

### Multiplicação de vídeos

Um conteúdo poderá gerar múltiplas versões, alterando elementos criativos significativos:

- Abertura.
- Estrutura narrativa.
- Duração.
- Ritmo.
- Ênfase temática.
- Narração.
- Organização dos cortes.
- CTA.

Não gerar dezenas de cópias quase idênticas para inundar as plataformas.

Implementar detecção de duplicidade e similaridade.

---

# 8. SISTEMA DE PUBLICAÇÃO

O sistema deve suportar:

- YouTube Shorts.
- TikTok.
- Instagram Reels.

Utilizar Postiz ou integrações oficiais aprovadas.

A publicação não será responsabilidade de um sexto agente. Será um serviço determinístico acionado pelo Diretor.

## Modo A — Publicação automática

Quando houver integração autorizada:

1. Receber vídeo aprovado.
2. Preparar título e descrição.
3. Preparar hashtags.
4. Definir data e horário.
5. Validar exigências da plataforma.
6. Publicar ou agendar.
7. Registrar ID e URL da publicação.
8. Atualizar o banco.
9. Coletar métricas posteriormente.

Não declarar uma publicação como concluída antes da confirmação efetiva da plataforma.

## Modo B — Publicação manual assistida

Quando a publicação automática não estiver disponível:

1. Não tentar contornar a restrição.
2. Salvar o vídeo final em uma pasta local.
3. Gerar os metadados necessários.
4. Notificar o usuário.
5. Registrar status `AGUARDANDO_PUBLICACAO_MANUAL`.
6. Manter o conteúdo disponível.
7. Permitir confirmação manual de publicação.
8. Registrar URL publicada.
9. Excluir o arquivo conforme a política de retenção.

### Estrutura

```text
output/
├── youtube/
│   └── YYYY-MM-DD/
│       ├── video_<id>.mp4
│       └── metadata_<id>.json
├── tiktok/
│   └── YYYY-MM-DD/
│       ├── video_<id>.mp4
│       └── metadata_<id>.json
└── instagram/
    └── YYYY-MM-DD/
        ├── video_<id>.mp4
        └── metadata_<id>.json
```

Não excluir conteúdos manuais pendentes antes da confirmação.

Se houver falha em uma plataforma, as demais devem continuar funcionando.

### Status de publicação

- `PENDENTE`.
- `AGENDADO`.
- `PUBLICANDO`.
- `PUBLICADO`.
- `AGUARDANDO_PUBLICACAO_MANUAL`.
- `FALHA`.
- `REQUER_AUTENTICACAO`.
- `BLOQUEADO_DIREITOS`.

Implementar idempotência para evitar publicações duplicadas em casos de retry.

---

# 9. NOTIFICAÇÕES

Implementar notificações por:

- Painel web.
- Telegram Bot.
- E-mail.

Eventos:

- Vídeo pronto para publicação manual.
- Publicação concluída.
- Falha de autenticação.
- Falha de processamento.
- Vídeo reprovado.
- Direitos não verificados.
- Limite de API atingido.
- Resumo diário.
- Produção interrompida.
- Necessidade de intervenção humana.

Cada notificação deverá conter informações suficientes para identificar o conteúdo e a ação necessária.

Não enviar notificações repetidas para o mesmo evento.

---

# 10. ANALYTICS E APRENDIZADO

Criar um módulo para acompanhar o desempenho do conteúdo.

Métricas:

- Visualizações.
- Curtidas.
- Comentários.
- Compartilhamentos, quando disponíveis.
- Tempo médio de visualização.
- Retenção.
- CTR, quando disponível.
- Crescimento de seguidores.
- Crescimento de inscritos.
- Desempenho por horário.
- Desempenho por template.
- Desempenho por categoria de conteúdo.

Não presumir que todas as redes disponibilizam as mesmas métricas.

Tratar métricas ausentes explicitamente.

O Diretor utilizará os resultados para:

1. Identificar formatos promissores.
2. Ajustar prioridades.
3. Orientar novas buscas.
4. Comparar templates.
5. Recomendar horários.
6. Reduzir produção de formatos com resultados insatisfatórios.
7. Propor novos experimentos.

O sistema deve aprender com métricas observadas, sem afirmar causalidade ou garantir viralização.

---

# 11. INTERFACE WEB

Criar painel moderno, tecnológico e responsivo.

Visual preferencial:

- Dark mode por padrão.
- Acentos em azul, ciano e violeta.
- Cards organizados.
- Gráficos claros.
- Navegação simples.
- Feedback visual de processamento.
- Design consistente.

Utilizar as skills de design e frontend disponíveis no ambiente do Codex, incluindo `web-design-guidelines` quando instalada.

## Páginas

### Dashboard

Mostrar:

- Estado do sistema.
- Agente ativo.
- Etapa atual.
- Vídeos produzidos.
- Publicações realizadas.
- Publicações pendentes.
- Erros.
- Estatísticas recentes.

### Viral Radar

- Pesquisa de tendências.
- Ranking de vídeos.
- Filtros por plataforma.
- País.
- Data.
- Viralidade.
- Perfis monitorados.

### Importar por URL

- Campo para link.
- Identificação da plataforma.
- Prévia e metadados.
- Instruções de edição.
- Seleção de template.
- Comando para iniciar processamento.

### Video Studio

- Pré-visualização.
- Templates.
- Duração.
- Narração.
- Legendas.
- Cortes.
- Versões disponíveis.
- Histórico de processamento.

### Publicações

- Calendário editorial.
- Fila automática.
- Fila manual.
- Vídeos prontos.
- Status por plataforma.
- Botão para confirmar publicação manual.

### Analytics

- Gráficos.
- Resultados por rede.
- Resultados por template.
- Evolução do canal.
- Análise de formatos.

### Agentes

- Estado dos cinco agentes.
- Última execução.
- Handoffs.
- Consumo de tokens.
- Histórico resumido de erros.
- Fila de trabalho.
- Controles para pausar ou reexecutar jobs.

### Configurações

- Redes sociais.
- Provedores de IA.
- Modelos por agente.
- Fontes.
- Perfis monitorados.
- Frequências.
- Templates.
- Direitos de uso.
- Publicação.
- Notificações.
- Limites de execução.

---

# 12. STACK TÉCNICA

Priorizar:

**Backend**
- Python.
- FastAPI.
- Pydantic.
- SQLAlchemy.
- SQLite inicialmente.

**Frontend**
- Next.js.
- TypeScript.
- Tailwind CSS.
- Componentes reutilizáveis.

**IA**
- Ollama.
- Provedores compatíveis com OpenAI API.
- OmniRoute opcional.
- Roteamento configurável de modelos.

**Vídeo**
- FFmpeg.
- ffprobe.
- Revideo.
- Faster Whisper.
- Piper TTS.

**Pesquisa**
- YouTube Data API.
- Conectores disponíveis para TikTok e Instagram.
- Ferramentas de descoberta de tendências.
- yt-dlp para downloads permitidos.

**Publicação**
- Postiz.
- Integrações oficiais quando disponíveis.

**Infraestrutura**
- Docker Compose.
- Volumes persistentes.
- Workers de processamento.
- Scheduler persistente.
- Filas de tarefas.
- Logs estruturados.
- Healthchecks.

Utilizar Redis e Celery quando forem necessários para a confiabilidade das filas, sem adicionar complexidade gratuitamente.

Verificar licenças e compatibilidade de todos os projetos antes de incorporá-los.

---

# 13. ESTRUTURA SUGERIDA

```text
gta-content-studio/
├── .agents/
│   └── skills/
├── .claude/
│   └── skills/
├── agents/
│   ├── diretor/
│   ├── cacador/
│   ├── escritor/
│   ├── editor/
│   └── avaliador/
├── backend/
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── services/
│   ├── integrations/
│   ├── workers/
│   └── schemas/
├── frontend/
├── scripts/
├── templates/
├── handoff/
├── videos/
│   ├── raw/
│   ├── processing/
│   └── final/
├── output/
│   ├── youtube/
│   ├── tiktok/
│   └── instagram/
├── reports/
├── data/
├── cache/
├── logs/
├── tests/
├── docker-compose.yml
├── .env.example
└── README.md
```

Permitir ajustes nessa estrutura quando houver justificativa técnica.

---

# 14. AUTONOMIA E RESILIÊNCIA

O sistema deverá possuir:

- Execução recorrente configurável.
- Agendamento persistente.
- Recuperação após reinício.
- Retentativas com backoff.
- Controle de rate limit.
- Timeout de tarefas.
- Jobs idempotentes.
- Controle de concorrência.
- Deduplicação de vídeos.
- Cache com TTL.
- Proteção contra loops infinitos.
- Limites diários de produção.
- Limites de custo e tokens.
- Exclusão de arquivos temporários.
- Monitoramento de disco.
- Registro de falhas.
- Alertas de autenticação.
- Pausa individual de integrações.
- Botão de parada de emergência.

A aplicação deve recuperar o estado da fila ao reiniciar o Docker.

Problemas em uma plataforma não devem interromper o restante do sistema.

---

# 16. CONFIGURAÇÃO INICIAL

Criar um assistente de primeira execução.

O usuário deverá conseguir configurar:

- Nome do canal.
- Nicho principal: GTA 6.
- Idioma final: PT-BR.
- Países monitorados.
- Quantidade de vídeos por dia.
- Duração dos vídeos.
- Frequência de pesquisa.
- Templates favoritos.
- Plataformas de publicação.
- Integrações e credenciais.
- Provedores de IA.
- Modelos de cada agente.
- Limites de gasto.
- Pasta de saída.
- Política de retenção.
- Notificações.
- Modo de aprovação.
- Fontes autorizadas.
- Perfis monitorados.

Guardar segredos de forma segura, não expor credenciais em logs e nunca incluí-las em handoffs.

Após configuração, permitir iniciar, pausar ou reiniciar o funcionamento autônomo.

---

# 17. TESTES E HOMOLOGAÇÃO

Implementar testes automatizados para:

1. Configuração inicial.
2. Validação de URLs.
3. Monitoramento de perfis.
4. Cache.
5. Contratos de handoff.
6. Comunicação entre agentes.
7. Coleta de metadados.
8. Classificação de direitos.
9. Criação de roteiros.
10. Renderização.
11. Validação técnica de vídeo.
12. Limite de revisões.
13. Publicação em modo de teste.
14. Fallback para publicação manual.
15. Notificações.
16. Deduplicação.
17. Recuperação de falhas.
18. Reinicialização Docker.
19. Exclusão segura de temporários.
20. Persistência do histórico.

Criar mocks para APIs externas.

Não realizar publicações reais durante testes automatizados.

### Critérios de aceite

O projeto estará funcional quando:

- O Docker Compose iniciar corretamente.
- O painel permitir configurar o sistema.
- Os cinco agentes executarem seu pipeline.
- Handoffs forem gerados e validados.
- O usuário conseguir importar uma URL.
- Perfis cadastrados puderem ser consultados pelas integrações disponíveis.
- O sistema gerar ao menos um vídeo de teste com mídia autorizada.
- O Avaliador bloquear um vídeo inválido.
- O limite de duas revisões funcionar.
- A publicação manual gerar arquivo e notificação.
- As integrações reais disponíveis conseguirem publicar após autorização.
- As métricas acessíveis forem armazenadas.
- O sistema sobreviver a reinicializações.
- Os arquivos temporários forem gerenciados corretamente.

Distinguir claramente testes locais, integrações simuladas e integrações homologadas em ambiente real.

---

# 18. ORDEM DE EXECUÇÃO DO CODEX

## Fase 1 — Reconhecimento

1. Inspecionar o projeto e o ambiente existente.
2. Identificar ferramentas e skills instaladas.
3. Verificar versões e dependências.
4. Identificar projetos open source reutilizáveis.
5. Verificar licenças e limitações.
6. Elaborar plano de implementação.

Não reinstalar desnecessariamente ferramentas que já estejam disponíveis.

## Fase 2 — Infraestrutura

Implementar:

- Docker Compose.
- Backend.
- Banco de dados.
- Filas.
- Scheduler.
- Persistência.
- Healthchecks.
- Configurações.

## Fase 3 — Agentes

Implementar os cinco agentes.

Criar os contratos de handoff e as sete skills de economia de tokens.

Testar o pipeline com materiais simulados e autorizados.

## Fase 4 — Processamento de vídeo

Implementar:

- Importação por URL.
- Coleta autorizada.
- Transcrição.
- Roteiros.
- Narração.
- Templates.
- Edição.
- Renderização.
- Avaliação.

## Fase 5 — Painel web

Desenvolver o frontend completo, conectado a endpoints reais.

Utilizar as skills de design instaladas.

Evitar telas demonstrativas com informações fictícias apresentadas como dados reais.

## Fase 6 — Publicação

Integrar plataformas disponíveis.

Implementar:

- Publicação automática autorizada.
- Fila manual.
- Armazenamento.
- Notificações.
- Calendário.
- Recuperação de falhas.

## Fase 7 — Analytics

Implementar métricas, relatórios e recomendações para novos ciclos.

## Fase 8 — Homologação

Executar testes.

Corrigir erros.

Validar o ciclo completo.

Documentar o funcionamento.

---

# 19. REGRAS DE EXECUÇÃO

Você tem autonomia para:

- Criar arquivos.
- Refatorar módulos.
- Instalar dependências necessárias.
- Criar scripts.
- Configurar Docker.
- Criar e executar testes.
- Implementar integrações.
- Criar documentação.
- Otimizar a arquitetura.
- Utilizar as skills disponíveis.
- Pesquisar projetos open source relevantes.

Mas deve:

- Evitar alterações destrutivas sem necessidade.
- Não expor credenciais.
- Não assumir permissões de publicação inexistentes.
- Não publicar conteúdos reais durante a homologação sem autorização.
- Não inventar resultados de testes.
- Priorizar funcionalidades efetivamente implementadas.
- Garantir funcionamento com apenas um usuário.
- Preservar a possibilidade de executar a aplicação localmente ou em servidor próprio.

Se uma integração não puder ser concluída por exigência externa, implemente um adaptador com interface real, modo de teste e fallback operacional, documentando claramente a pendência.

Não apresente um mock como funcionalidade pronta.

---

# 20. ENTREGA FINAL

Ao concluir, apresentar:

1. Resumo da arquitetura implementada.
2. Estrutura real de arquivos.
3. Funcionalidades concluídas.
4. Integrações disponíveis.
5. Integrações pendentes de autorização.
6. Skills criadas.
7. Agentes implementados.
8. Testes executados e seus resultados.
9. Comandos para inicializar o sistema.
10. Procedimento de configuração inicial.
11. Como conectar as redes sociais.
12. Como importar URLs e perfis.
13. Como iniciar o modo automático.
14. Como acompanhar notificações e relatórios.
15. Limitações conhecidas.

**Objetivo final:** entregar um GTA 6 Autonomous Content Studio pessoal, autocontido, modular e executável, que utilize cinco agentes especializados para descobrir oportunidades internacionais, produzir vídeos originais em português brasileiro, avaliar a qualidade, publicar nas redes autorizadas ou preparar publicações manuais e melhorar continuamente suas decisões com base em métricas observadas.

**Prioridades, nesta ordem:**

1. Funcionamento real.
2. Autonomia operacional.
3. Confiabilidade.
4. Qualidade dos vídeos.
5. Economia de tokens e infraestrutura.
6. Facilidade de uso.
7. Qualidade visual.
8. Expansibilidade futura.

Não criar complexidade de produto comercial que não seja necessária ao uso pessoal.

Implemente progressivamente e valide cada fase antes de iniciar a seguinte.