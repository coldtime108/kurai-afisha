param(
    [switch]$Configure,
    [switch]$KeepRunning
)

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDirectory '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Сначала установите зависимости по README.'
}

Push-Location -LiteralPath $projectDirectory
$runnerLock = $null
try {
    New-Item -ItemType Directory -Path 'data/runtime' -Force | Out-Null
    $runnerLock = [IO.File]::Open((Join-Path $projectDirectory 'data/runtime/telegram-runner.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $settingsPath = Join-Path $projectDirectory '.env'
    if (Test-Path -LiteralPath $settingsPath) {
        foreach ($line in [IO.File]::ReadAllLines($settingsPath)) {
            if ($line -match '^\s*(TELEGRAM_BOT_TOKEN|DATABASE_URL|NVIDIA_API_KEY|LLM_ENABLED|LLM_MODEL)\s*=(.*)$') {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), 'Process')
            }
        }
    }
    if (-not $env:TELEGRAM_BOT_TOKEN) {
        throw 'Добавьте TELEGRAM_BOT_TOKEN в локальные настройки .env.'
    }
    if (-not $env:DATABASE_URL) {
        New-Item -ItemType Directory -Path 'data/runtime' -Force | Out-Null
        $env:DATABASE_URL = 'sqlite:///./data/runtime/preview.db'
    }
    $env:PYTHONPATH = 'backend'
    $env:PYTHONUTF8 = '1'
    & $pythonPath -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить базу данных.' }
    if ($Configure) {
        & $pythonPath -m kurai.telegram_setup
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось настроить профиль Telegram.' }
    }
    do {
        & $pythonPath -m kurai.telegram_worker
        if ($KeepRunning) {
            Write-Warning 'Бот остановился. Повторный запуск через пять секунд.'
            Start-Sleep -Seconds 5
        }
        elseif ($LASTEXITCODE -ne 0) {
            throw 'Бот остановлен. Проверьте подключение и локальные настройки.'
        }
    } while ($KeepRunning)
}
finally {
    if ($runnerLock) { $runnerLock.Dispose() }
    Pop-Location
}
