# GTA 6 Studio - configuracao de voz local Piper PT-BR
# Execute na raiz do repositorio: powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar-piper-ptbr.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.\docker-compose.yml')) { throw 'Execute este script na raiz de Clips-Virais (falta docker-compose.yml).' }
if (!(Test-Path -LiteralPath '.\backend\requirements.txt')) { throw 'Nao foi encontrado backend/requirements.txt.' }

$voice = 'pt_BR-cadu-medium'
$path = 'pt/pt_BR/cadu/medium'
$baseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/$path"
$models = Join-Path $PSScriptRoot 'models'
New-Item -Path $models -ItemType Directory -Force | Out-Null

function Download-Verified([string] $Url, [string] $Destination, [long] $MinSize) {
    if ((Test-Path -LiteralPath $Destination) -and ((Get-Item -LiteralPath $Destination).Length -ge $MinSize)) {
        Write-Host "Ja existe: $Destination"
        return
    }
    $temp = "$Destination.part"
    try {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
        Write-Host "Baixando: $(Split-Path $Destination -Leaf)"
        Invoke-WebRequest -Uri $Url -OutFile $temp -UseBasicParsing -MaximumRedirection 10
        if ((Get-Item -LiteralPath $temp).Length -lt $MinSize) { throw "Download incompleto ou inesperado: $Destination" }
        Move-Item -LiteralPath $temp -Destination $Destination -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

$onnx = Join-Path $models "$voice.onnx"
$json = Join-Path $models "$voice.onnx.json"
$card = Join-Path $models "$voice.MODEL_CARD"
Download-Verified "$baseUrl/$voice.onnx" $onnx 1000000
Download-Verified "$baseUrl/$voice.onnx.json" $json 500
Download-Verified "$baseUrl/MODEL_CARD" $card 200

# Garanta que a voz publicada ainda corresponde a cadeia de treinamento CC0 documentada.
$licenseInfo = [System.IO.File]::ReadAllText($card)
if ($licenseInfo -notmatch 'License:\s*CC0' -or $licenseInfo -notmatch 'rdh base model') {
    throw 'O MODEL_CARD mudou. Confira a licenca e o modelo antes de continuar.'
}
# PowerShell 5.1/Windows PowerShell usa dicionario case-insensitive em ConvertFrom-Json.
# Piper possui chaves distintas "x" e "X", validas em JSON. Python preserva essa distincao.
$pythonExe = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExe) { throw 'Python 3 nao encontrado no PATH. Ative sua .venv e execute o instalador novamente.' }
# Invoke a Python module directly: this avoids nested quoting issues on Windows PowerShell 5.1.
# json.tool respects distinct case-sensitive JSON keys such as "x" and "X".
& $pythonExe.Source -m json.tool $json 1>$null
if ($LASTEXITCODE -ne 0) { throw 'JSON do Piper invalido ou incompleto; confira o download.' }
Write-Host 'Modelo e configuracao baixados; cartao de licenca conferido.'

# Backup e ajuste apenas do pin Piper.
$reqPath = Join-Path $PSScriptRoot 'backend\requirements.txt'
$req = [System.IO.File]::ReadAllText($reqPath)
if ($req -notmatch '(?m)^piper-tts==[\d.]+\s*$') { throw 'Pin piper-tts inesperado: confira backend/requirements.txt manualmente.' }
if ($req -notmatch '(?m)^piper-tts==1\.8\.0\s*$') {
    if (!(Test-Path -LiteralPath "$reqPath.bak-piper")) { Copy-Item -LiteralPath $reqPath -Destination "$reqPath.bak-piper" }
    $req = [regex]::Replace($req, '(?m)^piper-tts==[\d.]+\s*$', 'piper-tts==1.8.0')
    [System.IO.File]::WriteAllText($reqPath, $req, [System.Text.UTF8Encoding]::new($false))
}

$envPath = Join-Path $PSScriptRoot '.env'
if (!(Test-Path -LiteralPath $envPath)) { throw 'Arquivo .env nao existe. Execute primeiro start.ps1 para gerar as credenciais e tente novamente.' }
$envText = [System.IO.File]::ReadAllText($envPath)
if (!(Test-Path -LiteralPath "$envPath.bak-piper")) { Copy-Item -LiteralPath $envPath -Destination "$envPath.bak-piper" }
if ($envText -match '(?m)^PIPER_MODEL=.*$') {
    $envText = [regex]::Replace($envText, '(?m)^PIPER_MODEL=.*$', "PIPER_MODEL=/models/$voice.onnx")
} else {
    $envText = $envText.TrimEnd("`r", "`n") + "`r`nPIPER_MODEL=/models/$voice.onnx`r`n"
}
[System.IO.File]::WriteAllText($envPath, $envText, [System.Text.UTF8Encoding]::new($false))
Write-Host "PIPER_MODEL=/models/$voice.onnx"
Write-Host 'Atualizacao de dependencias e .env concluida. Reconstruindo API e worker...'
docker compose up -d --build api worker
if ($LASTEXITCODE -ne 0) { throw 'Falha no build. Consulte a saida anterior; modelos e .env foram preservados.' }

Write-Host 'Gerando WAV para validar o motor Piper...'
# The Piper CLI reads text from stdin; do not pass narration as an argument.
'Bem-vindo ao GTA seis Brasil. A narracao em portugues esta funcionando.' |
    docker compose exec -T worker piper --model "/models/$voice.onnx" --output_file '/tmp/teste-piper-ptbr.wav'
if ($LASTEXITCODE -ne 0) { throw 'Falha no teste de sintese. Veja os logs do worker.' }
docker compose cp 'worker:/tmp/teste-piper-ptbr.wav' '.\teste-piper-ptbr.wav'
if ($LASTEXITCODE -ne 0) { throw 'O audio foi gerado no container, mas nao foi possivel copia-lo para o Windows.' }
if (!(Test-Path -LiteralPath '.\teste-piper-ptbr.wav') -or (Get-Item -LiteralPath '.\teste-piper-ptbr.wav').Length -lt 1000) { throw 'O arquivo de teste nao foi criado corretamente.' }
Write-Host 'SUCESSO: narracao Piper PT-BR pronta. Abra teste-piper-ptbr.wav para ouvir.'
