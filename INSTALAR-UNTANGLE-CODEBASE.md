# Instalação — Skill untangle-codebase (GTA Studio)

Extraia este patch na pasta raiz `Clips-Virais` preservando a estrutura de pastas. Não exclua ou sobrescreva `.env`, `assets`, `models`, `temp`, vídeos, dados ou volumes do Docker.

A skill fica em `.agents/skills/untangle-codebase/SKILL.md` (Codex) e em `.claude/skills/untangle-codebase/SKILL.md` (compatibilidade). O arquivo `AGENTS.md` contém instruções para assistentes de desenvolvimento. A referência da evolução pedida está em `docs/REQUISITOS-V6-PIPELINE.md`.

Para conferir a instalação no PowerShell:

```powershell
Test-Path .\.agents\skills\untangle-codebase\SKILL.md
Get-Content .\.agents\skills\untangle-codebase\SKILL.md -TotalCount 6
```

Depois de abrir a pasta no Codex, solicite explicitamente `$untangle-codebase` e a área-alvo. A skill **não é executada automaticamente** pelos cinco agentes do estúdio e não altera os modelos do OmniRoute.

**Diagnóstico opcional** de uma produção real (read-only, requer reconstruir só o serviço API para incluir o novo comando):

```powershell
docker compose up -d --build api
docker compose exec api python -m backend.diagnose_assets --json
```

Esse diagnóstico não modifica banco nem arquivos. O arquivo `docs/DIAGNOSTICO-V5-E-GUIA-UNTANGLE.md` mostra o que estava implementado na base v5 e quais lacunas persistem para o novo pedido v6.

O pacote **não** implementa os agentes adicionais ou os novos avatares. O documento v6 é a especificação para desenvolvimento posterior.
