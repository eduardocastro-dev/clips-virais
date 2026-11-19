---
name: code-review
description: Revisão técnica de código para identificar falhas lógicas, vulnerabilidades, débitos técnicos e anti-patterns.
---

# code-review

## Função no Estúdio
Auditoria técnica pré-merge e pós-refatoração no backend FastAPI e frontend Next.js do GTA Studio.

## Diretrizes de Operação
1. **Critérios de Revisão**:
   - Robustez no tratamento de exceções (nunca engolir erros sem log).
   - Gerenciamento seguro de recursos (fechamento de conexões, descritores de arquivo e processos FFmpeg).
   - Ausência de vazamento de chaves e segredos em logs e artefatos.
2. **Modularidade**: Funções enxutas com escopo único e contratos de tipagem Pydantic / TypeScript rigorosos.
