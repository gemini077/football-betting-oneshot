param(
    [string]$TaskName = "FootballPredictionDay",
    [int]$StartDelayMinutes = 5
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $RepoRoot "scripts\run_product_cycle.ps1"
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "Product cycle runner not found: $Runner"
}

$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$RunnerArgument = "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $RunnerArgument
$StartAt = (Get-Date).AddMinutes($StartDelayMinutes)
$Trigger = New-ScheduledTaskTrigger -Once -At $StartAt -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -User "$env:USERDOMAIN\$env:USERNAME" `
    -RunLevel Limited `
    -Force | Out-Null

Write-Output "Installed current-user hourly task: $TaskName"
Write-Output "Runner: $Runner"
