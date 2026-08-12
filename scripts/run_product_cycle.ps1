param(
    [string]$Date,
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogRoot = Join-Path $RepoRoot "logs\product_cycle"
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogRoot "$Stamp.log"
$Arguments = @("scripts/automation_cycle.py")
if ($Date) {
    $Arguments += @("--date", $Date)
}

$ExitCode = 1
Push-Location $RepoRoot
try {
    & $PythonCommand @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $ExitCode
