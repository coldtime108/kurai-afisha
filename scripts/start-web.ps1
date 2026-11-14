param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDirectory '.venv/Scripts/python.exe'
Push-Location -LiteralPath $projectDirectory
try {
    $settingsPath = Join-Path $projectDirectory '.env'
    if (Test-Path -LiteralPath $settingsPath) {
        foreach ($line in [IO.File]::ReadAllLines($settingsPath)) {
            if ($line -match '^\s*(ADMIN_TOKEN|DATABASE_URL|NVIDIA_API_KEY|LLM_ENABLED|LLM_MODEL|COLLECTION_ENABLED)\s*=(.*)$') {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), 'Process')
            }
        }
    }
    if (-not $env:DATABASE_URL) {
        New-Item -ItemType Directory -Path 'data/runtime' -Force | Out-Null
        $env:DATABASE_URL = 'sqlite:///./data/runtime/preview.db'
    }
    $env:PYTHONPATH = 'backend'
    $env:PYTHONUTF8 = '1'
    & $pythonPath -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить базу данных.' }
    & $pythonPath -m uvicorn kurai.main:app --host 127.0.0.1 --port $Port --no-access-log
}
finally { Pop-Location }
