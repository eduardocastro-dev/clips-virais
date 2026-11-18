# Plano e contrato de implementação

Aplicação pessoal, API FastAPI e worker separados, SQLite WAL em volume local, frontend Next.js. A fila transacional tem lease, backoff e chave única; um worker processa vídeos sequencialmente. SQLite não deve ser colocado em compartilhamento de rede.

Fases: infraestrutura e contratos → cinco agentes → vídeo e QA → painel → distribuição e métricas → homologação. Credenciais externas não são pré-requisito para o teste sintético; são obrigatórias para integrações reais.

## Contrato visual
Painel operacional escuro, tipografia legível, acentos ciano e âmbar, navegação lateral. Ação principal: importar conteúdo. Primeiro viewport: estado real, fila e próximo passo. Sem métricas demonstrativas. Alvos: 390×844 e 1440×900. Foco visível e controles com rótulos; tabelas roláveis no celular.

Estados: carregando mantém estrutura; vazio oferece importação/configuração; erro preserva entradas e permite repetir; parcial mostra métricas ausentes como indisponíveis; sucesso confirma ação; autenticação pede token local. A inspeção renderizada será registrada separadamente, sem declarar verificações não executadas.
