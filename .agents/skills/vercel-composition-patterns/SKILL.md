---
name: vercel-composition-patterns
description: Padrões modernos de composição de componentes React, Server/Client components e arquitetura Next.js.
---

# vercel-composition-patterns

## Função no Estúdio
Arquitetura de componentes Next.js / React no painel de controle do estúdio, separando streaming e renderização de dados.

## Diretrizes de Operação
1. **Divisão de Responsabilidades**: Isolar Server Components (busca de dados estáveis) de Client Components (interatividade do estúdio).
2. **Composição Limpa**: Evitar props drilling usando composição direta (`children` e slots).
3. **Feedback Instantâneo**: Estados de loading (skeletons) e fallbacks com React Suspense.
