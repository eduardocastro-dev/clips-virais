---
name: cicd-automation
description: Automação de rotinas de verificação, testes contínuos, validação de tipos e integridade de containers.
---

# cicd-automation

## Função no Estúdio
Manutenção de pipelines de homologação rápida, verificações sintáticas e testes automatizados de ponta a ponta.

## Diretrizes de Operação
1. **Verificação Pré-execução**: Executar validação de tipagem Python (`mypy` / `pytest`) e sintaxe TypeScript antes de homologações.
2. **Build Limpo**: Manter containers Docker reproduzíveis sem poluição de arquivos temporários.
3. **Integridade de Dependências**: Monitorar compatibilidade entre versões de Python, PyAV, FFmpeg e pacotes Node.
