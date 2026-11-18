# Migração segura: dois PostgreSQL e dois Redis legados → duas instâncias compartilhadas

**Somente para quem já iniciou uma versão anterior do projeto.** Em uma instalação nova, `start.ps1` / `start.sh` cria os bancos compartilhados sem necessidade de migração.

## Antes de começar

- **Use a mesma pasta do projeto e o mesmo nome de projeto do Docker Compose (`COMPOSE_PROJECT_NAME`) do deploy original.** Copiar os arquivos para uma pasta com nome diferente muda o prefixo dos volumes e não equivale a migrar o deploy existente.
- **Não execute `docker compose down -v`, `docker volume prune`, nem apague `.env` ou `data/migration`.** O serviço Postiz também utiliza `postiz-config`/`postiz-uploads`, o OmniRoute usa `omniroute-data`, e o estúdio usa `studio`; esses volumes não são recriados nem copiados durante a migração.
- Reserve disco para backups e novo PostgreSQL/Redis. Pare publicações e agendamentos externos; o script para os workers locais e o Temporal antes dos dumps, mas **não cancela** publicações já programadas em redes sociais.
- Guarde previamente uma cópia da instalação (incluindo a `.env` e todos os volumes) em local seguro. `data/migration` contém registros e possíveis dados sensíveis; nunca envie isso para o Git.
- A migração é **lógica**: faz `pg_dump -Fc`/`pg_restore` de `postiz`, `temporal` e, quando existe, `temporal_visibility`; gera um RDB independente de cada Redis legado; copia todas as chaves Redis com `MIGRATE ... COPY` para DB 0 (Postiz) e DB 1 (OmniRoute). Elasticsearch continua usando `temporal-search` do deploy original.

## Executar no PowerShell

```powershell
# Apenas se .env não existir ainda; este comando NÃO inicia o stack novo.
docker compose -f compose.setup.yml run --rm setup

# Python 3.10+ instalado no host (nenhuma biblioteca Python adicional necessária).
python scripts/migrate_shared.py

# Somente após a mensagem de migração concluída:
.\start.ps1
docker compose ps
docker compose logs --tail=80 bootstrap postiz omniroute temporal
```

## Executar no Linux

```sh
docker compose -f compose.setup.yml run --rm setup
python3 scripts/migrate_shared.py
sh start.sh
docker compose ps
```

O script recusa migrar se faltar algum volume legado, se já existir volume compartilhado ou se encontrar tabelas/chaves no destino. **Não remove os volumes ou dados originais.** A marca `data/migration-shared.completed.json` é criada somente após conferir as quantidades de tabelas restauradas e chaves copiadas. A pasta `data/migration/<UTC>/` possui os dumps individuais, snapshots Redis, hashes SHA-256 e manifest da operação.

A checagem de quantidade de tabelas/chaves é uma verificação básica, **não uma homologação integral de integridade funcional**. Após a migração, confira usuários/canais no Postiz, workflows do Temporal, combo/modelos OmniRoute, jobs agendados e logs dos serviços antes de reativar publicações. **A migração não foi executada no seu Docker por esta entrega; requer validação na máquina de destino.**

## Se algo falhar

1. Não execute `start.ps1`/`start.sh` se a migração falhou. Preserve os dumps e consulte o erro.
2. O arquivo original `docker-compose.legacy.yml` reproduz a topologia antiga. As instâncias de origem e seus volumes permanecem preservados. Dependendo da etapa onde a falha ocorreu, pode ser necessário interromper os serviços `postgres`/`redis` novos para retomar com `docker compose -f docker-compose.legacy.yml up -d`.
3. Se algum volume compartilhado foi parcialmente populado, o migrador **recusa sobrescrever**. Revise/recupere os dados antes de tentar novamente; não remova volumes às cegas.
4. Se a Postiz ou Temporal já tinha dados no banco mas containers tinham sido removidos, o script pode reabrir os serviços legados a partir dos volumes. Confirme primeiro o projeto Compose e a identificação dos volumes com `docker volume ls`.
5. O script não migra bancos de outras instalações Docker na sua máquina; somente volumes rotulados com o mesmo projeto Compose.

## Como fica a infraestrutura

| Serviço | Container | Isolamento |
|---|---|---|
| PostgreSQL 17 | `postgres` | `postiz`, `temporal`, `temporal_visibility`, usuários independentes |
| Redis 7.2 | `redis` | DB lógico 0 para Postiz, 1 para OmniRoute, senha e AOF |
| Temporal | `temporal` | Banco principal e `temporal_visibility` compartilhados na instância Postgres |
| Elasticsearch | `temporal-elasticsearch` | Índices próprios Temporal persistidos no volume original |
| Estúdio FastAPI | `api`/`worker` | SQLite WAL `studio`, preservado para não romper o schema existente |
| OmniRoute | `omniroute` | Configuração própria `/app/data`/SQLite, cache e afinidade Redis quando habilitados |
| Postiz | `postiz` | Uploads/configuração próprios, banco PostgreSQL compartilhado |

Compartilhar **instância** PostgreSQL/Redis não significa misturar esquemas, permissões, filas ou credenciais dos aplicativos. O SQLite do Estúdio e o banco próprio do OmniRoute não foram migrados para PostgreSQL, pois isso exigiria reescrever cada aplicação e arriscaria perda de estado.
