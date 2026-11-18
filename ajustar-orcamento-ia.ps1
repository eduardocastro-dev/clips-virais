param(
    [ValidateRange(1000,1000000)]
    [int]$TokensPorDia = 200000
)
$ErrorActionPreference = 'Stop'
$scriptPython = @'
import sys
from backend import core as db

db.init_db()
target = int(sys.argv[1])
config = db.settings()
previous = config.daily_tokens
# Do not reduce an existing, higher user-defined limit.
if previous < target:
    config.daily_tokens = target
    db.put_setting('settings', config.model_dump())
used = db.rows('SELECT tokens,cost FROM usage WHERE day=:day', {'day': db.today()})
print('Limite anterior (tokens/dia):', previous)
print('Limite atual (tokens/dia):', config.daily_tokens)
print('Tokens ja contabilizados hoje:', used[0]['tokens'] if used else 0)
print('Orcamento de custo interno (USD/dia):', config.daily_cost_usd)
print('Custo estimado por milhao:', config.cost_per_million)
print('Historico de uso foi preservado. Quotas reais do OmniRoute nao foram modificadas.')
'@
$scriptPython | docker compose exec -T api python - $TokensPorDia
if ($LASTEXITCODE -ne 0) { throw 'Falha ao atualizar o limite interno. Confira se o container api esta rodando.' }
