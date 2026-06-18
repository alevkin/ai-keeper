param(
    [int]$Port = 8766,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Aikeeper = Join-Path $RepoRoot ".venv\Scripts\aikeeper.exe"
$Command = "`"$Aikeeper`" daemon start --host 127.0.0.1 --port $Port"

Write-Host "AI Keeper Windows service prep"
if ($DryRun) {
    Write-Host "DRY RUN"
}

Write-Host "Future service command: $Command"
Write-Host "AIKEEPER_HOME: $env:AIKEEPER_HOME"

if (-not $DryRun) {
    throw "Windows service installation is not implemented yet. Use -DryRun for planning."
}
