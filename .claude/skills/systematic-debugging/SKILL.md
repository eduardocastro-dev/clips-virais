---
name: systematic-debugging
description: Metodologia científica para identificação e resolução da causa raiz de defeitos de software e renderização.
---

# systematic-debugging

## Função no Estúdio
Diagnóstico estruturado para falhas em pipelines de renderização, dessincronia de áudio/vídeo, estouro de timeouts e erros em APIs.

## Diretrizes de Operação
1. **Reprodução Mínima**: Reproduzir o defeito com o menor conjunto de dados possível antes de tentar alterações no código.
2. **Isolamento de Variáveis**: Inspecionar logs (`media-last-error.log`, traces de eventos) e separar falhas de FFmpeg de falhas de modelos ou dados.
3. **Confirmação com Testes**: Criar teste automatizado que falha antes da correção e passa após a solução.
