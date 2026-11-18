#!/bin/sh
set -eu
cd "$(dirname "$0")"
HOST_UID="$(id -u)" HOST_GID="$(id -g)" docker compose -f compose.setup.yml run --rm setup
docker compose up -d --build
printf '%s\n' 'Estúdio: http://localhost:3000 | OmniRoute: http://localhost:20128 | Publicação: manual' 'Integração: docker compose logs -f bootstrap. Credenciais locais preservadas em .env.'
