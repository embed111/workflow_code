param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8090,
    [switch]$SkipBackfill,
    [switch]$OpenBrowser
)

Write-Host "[deprecated] please use scripts/dev/launch_workflow.ps1"
& (Join-Path $PSScriptRoot "launch_workflow.ps1") -BindHost $BindHost -Port $Port -SkipBackfill:$SkipBackfill -OpenBrowser:$OpenBrowser
exit $LASTEXITCODE
