---
name: playwright-cli
description: Automação e testes com navegadores headless, capturas de tela reais de matérias e validação E2E.
---

# playwright-cli

## Função no Estúdio
Captura autêntica de manchetes e imagens de matérias jornalísticas (Playwright Chromium) e testes de ponta a ponta na interface do usuário.

## Diretrizes de Operação
1. **Captura Fiel de Notícias**:
   - Bloquear cookies, anúncios, pop-ups e banners promocionais via injeção CSS antes do screenshot.
   - Capturar seletores pontuais (`h1`, `article p`, `article img`) gerando prints limpos e transparentes.
2. **Segurança de Navegação**:
   - Bloquear requisições a redes privadas/localhost e URLs não HTTPS.
   - Timeout rígido para evitar congelamento de workers em matérias pesadas.
