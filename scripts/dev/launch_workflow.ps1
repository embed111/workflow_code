param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8090,
    [string]$RuntimeRoot = ".runtime",
    [switch]$SkipBackfill,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
Set-Location $root
$runtimeRootPath = if ([System.IO.Path]::IsPathRooted($RuntimeRoot)) {
    [System.IO.Path]::GetFullPath($RuntimeRoot)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $root $RuntimeRoot))
}
New-Item -ItemType Directory -Path $runtimeRootPath -Force | Out-Null
$entryScriptPath = (Join-Path $root "scripts/bin/workflow_entry_cli.py")

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    throw "python not found in PATH."
}

Write-Host "[workflow] workspace: $root"
Write-Host "[workflow] runtime root: $runtimeRootPath"
Write-Host "[workflow] python: $($pythonCmd.Source)"

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $ownerId = [int]$listener.OwningProcess
    $ownerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId" -ErrorAction SilentlyContinue
    $ownerName = if ($ownerProcess) { [string]$ownerProcess.Name } else { "" }
    $ownerCommand = if ($ownerProcess) { [string]$ownerProcess.CommandLine } else { "" }
    $isWorkflowServer =
        ($ownerName -match '^python(?:w)?\.exe$') -and
        ($ownerCommand -match 'scripts[\\/](bin[\\/])?workflow_web_server\.py')
    if (-not $isWorkflowServer) {
        $detail = if ($ownerName) { "$ownerName (PID=$ownerId)" } else { "PID=$ownerId" }
        throw "port $Port is already in use by $detail; please free the port or choose another one."
    }
    Write-Host "[workflow] stop stale server on port $Port (PID=$ownerId) ..."
    Stop-Process -Id $ownerId -Force
    $deadline = (Get-Date).AddSeconds(8)
    do {
        Start-Sleep -Milliseconds 200
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    } while ($listener -and (Get-Date) -lt $deadline)
    if ($listener) {
        throw "stale workflow server on port $Port did not exit in time."
    }
}

if (-not $SkipBackfill) {
    Write-Host "[workflow] backfill JSONL -> SQLite ..."
    & python scripts/bin/workflow_entry_cli.py --root $runtimeRootPath --mode backfill
    if ($LASTEXITCODE -ne 0) {
        throw "backfill failed with exit code $LASTEXITCODE"
    }
}
else {
    Write-Host "[workflow] skip backfill."
}

Write-Host "[workflow] refresh status ..."
& python scripts/bin/workflow_entry_cli.py --root $runtimeRootPath --mode status
if ($LASTEXITCODE -ne 0) {
    throw "status failed with exit code $LASTEXITCODE"
}

$url = "http://$BindHost`:$Port"
$healthUrl = "$url/healthz"
$browserJob = $null
if ($OpenBrowser) {
    $browserJob = Start-Job -ScriptBlock {
        param(
            [string]$TargetUrl,
            [string]$TargetHealthUrl
        )

        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline) {
            try {
                $response = Invoke-RestMethod -Uri $TargetHealthUrl -Method Get -TimeoutSec 3
                if ($response.ok) {
                    Start-Process $TargetUrl | Out-Null
                    return
                }
            }
            catch {
            }
            Start-Sleep -Milliseconds 500
        }
    } -ArgumentList $url, $healthUrl
}

Write-Host "[workflow] web => $url"
Write-Host "[workflow] press Ctrl+C to stop."
$webExitCode = 0
try {
    & python scripts/bin/workflow_web_server.py --root $runtimeRootPath --entry-script $entryScriptPath --host $BindHost --port $Port --focus "Phase0: web 对话 + 训练工作流"
    $webExitCode = $LASTEXITCODE
}
finally {
    if ($browserJob) {
        Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
    }
}
if ($webExitCode -eq 73) {
    exit 73
}
if ($webExitCode -ne 0) {
    throw "web server exited with code $webExitCode"
}
