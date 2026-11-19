---
name: clips-virais-ops
description: Operar e atualizar o projeto Clips-Virais (Docker Compose, logs, saúde dos serviços, rebuild e deploy local). Use quando o usuário pedir para subir, reiniciar, atualizar, diagnosticar ou ver logs do projeto.
---

# clips-virais-ops

## Contexto do ambiente
- Projeto em `C:\Users\Eduardo Castro\Documents\ChatGPT\Clips-Virais`, rodando via Docker Compose (projeto "clips-virais").
- Containers conhecidos:
  - `api` (porta 8000): FastAPI backend
  - `worker`: processamento de jobs e pipeline em background
  - `web` (porta 3000): frontend Next.js / React
  - `omniroute` (porta 20128): gateway e roteamento de modelos de IA
  - `redis`: persistência e cache do OmniRoute
  - `bootstrap`: inicialização de tokens e configuração inicial

## Fluxo operacional padrão

### 1. Diagnóstico de Saúde e Status
```powershell
docker compose ps
docker compose logs --tail 50 api
docker compose logs --tail 50 worker
```

### 2. Atualização e Rebuild Seletivo
1. Verifique `git status` antes de puxar alterações.
2. Reconstrua apenas o serviço modificado para economizar tempo:
```powershell
docker compose up -d --build api
# ou para worker:
docker compose up -d --build worker
# ou para frontend:
docker compose up -d --build web
```

### 3. Diagnóstico Read-Only de Mídia e Produção
Para inspecionar por que uma produção falhou ou por que faltam assets:
```powershell
docker compose exec api python -m backend.diagnose_assets --json
```

Para inspecionar um vídeo específico:
```powershell
docker compose exec api python -m backend.diagnose_assets --video ID_DA_PRODUCAO --json
```

### 4. Execução de Testes
```powershell
docker compose exec api pytest tests/ -v
```

## Regras de segurança invioláveis

- **NUNCA** execute `docker compose down -v`, `docker system prune`, `git reset --hard` ou `git clean -fd` sem autorização explícita e confirmação de backup.
- **NUNCA** apague volumes persistentes de dados: `studio`, `omniroute-data` e `shared-redis`.
- **NUNCA** imprima no terminal ou exponha conteúdos de arquivos `.env`, `STUDIO_TOKEN` ou chaves de API secretas.
- **NUNCA** altere arquivos originais de áudio ou vídeo dentro da pasta `/assets/`. Todos os arquivos nessa pasta pertencem ao usuário.
- Antes de editar `docker-compose.yml` ou arquivos `.env`, apresente o diff proposto e solicite confirmação.
