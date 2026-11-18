$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
docker compose -f compose.setup.yml run --rm setup
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar configuração local.' }
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Falha ao iniciar serviços. Consulte docker compose logs.' }
Write-Host 'Estúdio: http://localhost:3000 | Postiz: http://localhost:4007 | OmniRoute: http://localhost:20128'
Write-Host 'Acompanhe a integração: docker compose logs -f bootstrap. Senhas locais: arquivo .env.'
