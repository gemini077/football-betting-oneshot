param(
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bridgeScript = Join-Path $projectRoot 'scripts\live_odds_bridge.py'
$logRoot = Join-Path $projectRoot 'data\live_odds_bridge\service'
$stdout = Join-Path $logRoot 'stdout.log'
$stderr = Join-Path $logRoot 'stderr.log'

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    exit 0
}

New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$python = (Get-Command python -ErrorAction Stop).Source
$arguments = @(
    $bridgeScript,
    '--host', '127.0.0.1',
    '--port', [string]$Port,
    '--allowed-page-host', 'user-pc-new.hl99yjjpf.com'
)

Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $projectRoot `
    -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/health" -TimeoutSec 2
        if ($health.ok) { exit 0 }
    } catch { }
}

throw "Football Betting OneShot 本地桥接启动失败，请查看 $stderr"
