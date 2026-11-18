#!/bin/sh
set -eu
cd "$(dirname "$0")"
docker compose -f compose.setup.yml run --rm setup
docker compose up -d --build
printf '%s\n' 'Estúdio: http://localhost:3000 | Postiz: http://localhost:4007 | OmniRoute: http://localhost:20128' 'Integração: docker compose logs -f bootstrap. Senhas locais: .env.'
