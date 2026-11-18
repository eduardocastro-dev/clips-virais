$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host '[1/4] Parando Worker para criar snapshot consistente...' -ForegroundColor Cyan
docker compose stop worker
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel parar o Worker. Nenhuma exclusao foi feita.' }
Write-Host '[2/4] Criando backup SQLite + export JSON + arquivos de producao...'
$jsonText = (docker compose exec -T api python -m backend.reset_productions backup | Out-String)
if ($LASTEXITCODE -ne 0) { throw 'Falha no backup. Nao execute reset.' }
$info = $jsonText | ConvertFrom-Json
$id = [string]$info.backup_id
if (-not $id -or $id -notmatch '^[A-Za-z0-9T-]+$') { throw 'ID de backup invalido.' }
$dest = Join-Path $PSScriptRoot "backups\production-reset\$id"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Write-Host '[3/4] Copiando backup para a pasta local protegida...'
docker compose cp "api:/studio/backups/production-reset/$id/." "$dest/"
if ($LASTEXITCODE -ne 0) { throw 'Backup existe no volume, mas a copia para o host falhou. Nao execute reset.' }
foreach ($file in @('studio.sqlite','affected-tables.json','production-files.tar.gz','manifest.json')) {
  $item=Get-Item (Join-Path $dest $file) -ErrorAction SilentlyContinue
  if (-not $item -or $item.Length -le 0) { throw "Arquivo ausente no backup: $file. Nao execute reset." }
}
Write-Host '[4/4] Backup conferido. Nenhum registro foi removido.' -ForegroundColor Green
Write-Host "Backup ID: $id"
Write-Host "Copia local: $dest"
Write-Host 'Contagens anteriores:'
$info.counts_before | Format-List
Write-Host 'PARE AQUI. Envie o ID e as contagens; a exclusao requer sua confirmacao explicita.' -ForegroundColor Yellow
Write-Host 'O Worker permanece parado ate a decisao de continuar ou cancelar.'
