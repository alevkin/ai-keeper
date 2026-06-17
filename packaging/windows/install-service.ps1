param(
    [int]$Port = 8766,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Command = "uv run aikeeper daemon start --host 127.0.0.1 --port $Port"

Write-Host "AI Keeper Windows service prep"
if ($DryRun) {
    Write-Host "DRY RUN"
}

Write-Host "Future service command: $Command"
Write-Host "AIKEEPER_HOME: $env:AIKEEPER_HOME"

if (-not $DryRun) {
    throw "Windows service installation is not implemented yet. Use -DryRun for planning."
}
