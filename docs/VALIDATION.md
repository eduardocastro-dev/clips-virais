# Estado da atualização Docker compartilhada (18/11/2026)

A homologação histórica abaixo foi feita **antes** da unificação de PostgreSQL/Redis.
A entrega desta atualização verificou: compilação sintática Python, validade estrutural YAML/volumes/dependências, parse do `start.sh` e **7 testes isolados** para segredos, bootstrap OmniRoute, preservação de configurações e guardas de migração. Os 7 testes usaram um *shim de importação* de `feedparser`, porque a dependência externa e o Docker CLI não estão presentes neste ambiente. Portanto, **não equivalem a rodar a suíte completa com dependências reais**. O Docker Compose não pôde ser iniciado ou homologado aqui, e nenhuma migração de volumes reais, Postiz, OmniRoute, FFmpeg ou integração OAuth foi executada nesta atualização.

Para homologação real na máquina do usuário: `docker compose config`, `docker compose ps`, `docker compose logs bootstrap`, `docker compose exec api python -m backend.doctor`, testes do perfil `test` e validação funcional manual das aplicações. Consulte `docs/MIGRATION.md` antes de apontar a topologia nova para volumes legados.

---

# Homologação executada

Ambiente: Windows, Python 3.13, Node 26 local, Docker Desktop Linux 29.7.2, Compose 5.5.0. Imagens: Python 3.13-slim e Node 22-alpine. Horários da aplicação: America/Sao_Paulo.

## Resultados

| Verificação | Resultado observado |
|---|---|
| Suíte no Docker | **40 passed**, 1 aviso de depreciação do Starlette/AnyIO, sem falhas |
| Suíte Windows | **39 passed, 1 skipped**; render ignorado porque FFmpeg/ffprobe não estão no PATH do host |
| Build Next.js 16.4.6 | Compilação de produção e TypeScript concluídos |
| Auditoria npm após atualização | 0 vulnerabilidades reportadas |
| Compose | API e worker saudáveis; web disponível em localhost:3000 |
| Render real | MP4 1080×1920 H.264/AAC, 10s, 333250 bytes |
| Fluxo iniciado pelo painel | Cinco handoffs gerados, avaliação aprovada em modo sintético, 3 filas manuais |
| Reinício API/worker | Mesmo ID de vídeo, tamanho de arquivo e publicações preservados |
| Publicação externa | **Nenhuma realizada** |

O teste sintético usa imagem gerada com FFmpeg e um sinal senoidal de áudio. **Não comprova qualidade da narração Piper, qualidade de roteiros de modelos ou qualidade perceptual de uma produção real.** Ele comprova execução mecânica, formato, persistência e bloqueio de envio de testes.

## Cobertura automatizada

Configuração e autenticação; segredos criptografados sem retorno do valor; URLs válidas/canônicas e rejeição de URLs não suportadas; direitos e bloqueio de download; cota diária; parada de emergência; CRUD/consulta enfileirada de perfis; cache expirado; notificações sem duplicação; handoffs atômicos/schema; claim concorrente e recuperação de lease; metadados YouTube mockados e cache; limite de duas revisões; ambiguidade do Editor devolvida ao Escritor sem loop; vídeo inválido bloqueado; distribuição manual idempotente; retenção de pendentes e prazo após confirmação; backoff até três tentativas; timestamps do roteiro; limites de IA e reserva separada para fallback; métricas ausentes como null; upload sem ID não confirmado; proteção de caminhos; render real e pipeline completo.

As chamadas a YouTube, modelos, Postiz, feeds, TikTok e Instagram são **mocks** na suíte. Foram acrescentados testes de agendamento sem confirmação prematura, timeout com intenção preservada, bloqueio de envio de testes, horários editoriais, RSS de referência, bloqueio de IP privado, identidade de conta, briefing atômico e versões idempotentes. Telegram, e-mail e redes sociais não receberam mensagens de teste. O teste de reinício real usa `scripts/smoke.py` antes/depois de `docker compose restart api worker`; a recuperação de jobs interrompidos é coberta pelo teste transacional de lease, não por uma interrupção forçada durante upload real.

## Interface observada

Navegação e estados inspecionados no navegador local: Dashboard, Importar, Studio, Publicações, Analytics, Agentes, Configurações e Radar. Viewports 1440×900 e 390×844. A largura útil observada foi 1425/375 px por causa da barra de rolagem; `scrollWidth == clientWidth`, sem overflow horizontal da página. Navegação e trilho de agentes têm rolagem própria no celular.

- Login inválido: erro legível e sem acesso aos dados.
- Login válido: dashboard com dados reais do teste.
- Importação inválida: mensagem legível, campo preservado; corrigida a apresentação inicial de JSON bruto.
- Carregamento: API pausada brevemente, indicador visível e atualização desabilitada; retomada concluída sem perda dos dados.
- Estado vazio: primeira execução sem vídeos e Analytics sem métricas.
- Estado parcial: vídeo disponível, publicação manual e métricas indisponíveis representadas explicitamente.
- Sucesso: vídeo aprovado e três destinos manuais, todos marcados como teste.
- Teclado: Tab entre URL e template; foco ciano sólido visível. Labels presentes na árvore acessível.
- Inspeção de console do build final: nenhuma mensagem de erro capturada.

Calendário móvel e cadastro de RSS foram inspecionados novamente após ampliação: sem overflow horizontal da página. Campos de integração Postiz e gráfico vazio de Analytics também foram conferidos. Capturas em `docs/evidence/`. Não foi executada auditoria completa com leitor de tela, teste de carga ou homologação em aparelhos físicos.

## Pendente de configuração/homologação real

Voz Piper licenciada; modelos Ollama/API e suas respostas; modelo visual do Avaliador; download e reconhecimento Faster Whisper; OAuth e upload privado real YouTube; metadados/métricas com chaves reais; instância Postiz com contas conectadas; tokens TikTok/Meta; feeds reais definidos pelo usuário; disponibilidade de TikTok oEmbed; entrega Telegram/SMTP. Os adaptadores existem, mas estes caminhos **não foram homologados com contas reais**.

## Requisitos ainda não implementados

Consentimento OAuth dentro do próprio painel (realizado na plataforma/Postiz); editor de timeline de arrastar e soltar; catálogo de trilhas licenciadas; efeitos avançados Revideo; otimização estatística de horários; pasta arbitrária do host configurável no painel; isolamento de contêineres por agente. Consulta global de terceiros no TikTok/Instagram continua limitada pelas permissões oficiais. Os módulos operacionais usam APIs reais, mas os acessos externos não foram homologados sem credenciais.

Esta entrega não equivale à conclusão integral de todas as funcionalidades do master prompt. O núcleo executável e a homologação local estão prontos; os itens acima permanecem abertos, distinguindo implementação pendente de simples autorização externa.
