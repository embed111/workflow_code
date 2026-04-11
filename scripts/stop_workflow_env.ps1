param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('dev', 'test', 'prod')]
    [string]$Environment,
    [string]$BindHost = '',
    [int]$Port = 0,
    [switch]$AllowProdStop,
    [int]$WaitTimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'workflow_env_common.ps1')

function Get-RunningProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PidFile
    )

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }
    $text = ''
    try {
        $text = (Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8).Trim()
    }
    catch {
        return $null
    }
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }
    $pidValue = 0
    if (-not [int]::TryParse($text, [ref]$pidValue)) {
        return $null
    }
    try {
        return Get-Process -Id $pidValue -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Get-ListeningProcess {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    try {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    }
    catch {
        return $null
    }
    if (-not $listener) {
        return $null
    }
    try {
        return Get-Process -Id ([int]$listener.OwningProcess) -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Get-RunningProcessCommandLine {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    try {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        return [string]$process.CommandLine
    }
    catch {
        return ''
    }
}

function Test-ProcessMatchesDescriptor {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Descriptor,
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process
    )

    $instance = Read-WorkflowJson -Path ([string]$Descriptor.instance_file) -Default @{}
    if ($instance.Count -gt 0) {
        if ([string]$instance['environment'] -ne [string]$Descriptor.environment) {
            return @{ match = $false; reason = 'instance_environment_mismatch' }
        }
        if (-not (Test-WorkflowSamePath -Left ([string]$instance['control_root']) -Right ([string]$Descriptor.control_root))) {
            return @{ match = $false; reason = 'instance_control_root_mismatch' }
        }
        if (-not (Test-WorkflowSamePath -Left ([string]$instance['deploy_root']) -Right ([string]$Descriptor.deploy_root))) {
            return @{ match = $false; reason = 'instance_deploy_root_mismatch' }
        }
        if (-not (Test-WorkflowSamePath -Left ([string]$instance['manifest_path']) -Right ([string]$Descriptor.manifest_path))) {
            return @{ match = $false; reason = 'instance_manifest_path_mismatch' }
        }
    }

    $commandLine = Get-RunningProcessCommandLine -ProcessId $Process.Id
    if (-not [string]::IsNullOrWhiteSpace($commandLine) -and $commandLine -match 'workflow_web_server\.py') {
        $runtimeRootPattern = [regex]::Escape([string]$Descriptor.runtime_root)
        if ($commandLine -notmatch $runtimeRootPattern) {
            return @{ match = $false; reason = 'process_runtime_root_mismatch' }
        }
        return @{ match = $true; reason = 'trusted_workflow_process'; command_line = $commandLine }
    }

    return @{ match = $false; reason = 'process_identity_unverified'; command_line = $commandLine }
}

function Remove-DescriptorStateFiles {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Descriptor
    )

    $removed = @()
    foreach ($path in @([string]$Descriptor.pid_file, [string]$Descriptor.instance_file)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            if (-not (Test-Path -LiteralPath $path)) {
                $removed += $path
            }
        }
    }
    return $removed
}

function Wait-PortReleased {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [int]$TimeoutSeconds = 15
    )

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-ListeningProcess -Port $Port)) {
            return $true
        }
        Start-Sleep -Milliseconds 300
    }
    return (-not (Get-ListeningProcess -Port $Port))
}

$sourceRoot = Get-WorkflowSourceRoot -ScriptRoot $PSScriptRoot
if ($Environment -eq 'prod' -and -not $AllowProdStop) {
    throw 'direct prod stop is disabled by default; pass -AllowProdStop for explicit maintenance'
}

$descriptor = Resolve-WorkflowEnvironmentDescriptor `
    -SourceRoot $sourceRoot `
    -Environment $Environment `
    -BindHost $BindHost `
    -Port $Port

$candidates = @{}
$runningProcess = Get-RunningProcess -PidFile ([string]$descriptor.pid_file)
if ($runningProcess) {
    $candidates[[string]$runningProcess.Id] = $runningProcess
}
$listeningProcess = Get-ListeningProcess -Port ([int]$descriptor.port)
if ($listeningProcess) {
    $candidates[[string]$listeningProcess.Id] = $listeningProcess
}

if ($candidates.Count -eq 0) {
    $removedStateFiles = Remove-DescriptorStateFiles -Descriptor $descriptor
    $payload = @{
        ok = $true
        environment = $Environment
        status = 'already_stopped'
        port = [int]$descriptor.port
        removed_state_files = $removedStateFiles
    }
    $payload | ConvertTo-Json -Depth 10
    exit 0
}

$trusted = @()
$rejected = @()
foreach ($process in $candidates.Values) {
    $matchState = Test-ProcessMatchesDescriptor -Descriptor $descriptor -Process $process
    if ([bool]$matchState.match) {
        $trusted += ,@{
            process = $process
            reason = [string]$matchState.reason
            command_line = [string]$matchState.command_line
        }
        continue
    }
    $rejected += ,@{
        pid = [int]$process.Id
        name = [string]$process.ProcessName
        reason = [string]$matchState.reason
    }
}

if ($trusted.Count -eq 0) {
    $detail = @{
        environment = $Environment
        port = [int]$descriptor.port
        rejected = $rejected
    } | ConvertTo-Json -Depth 10 -Compress
    throw "environment $Environment listener exists but none matched descriptor; fail-closed: $detail"
}

$stopped = @()
foreach ($entry in $trusted) {
    $process = [System.Diagnostics.Process]$entry.process
    try {
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
    }
    catch {
        throw "failed to stop environment $Environment process PID=$($process.Id): $($_.Exception.Message)"
    }
    $stopped += ,@{
        pid = [int]$process.Id
        name = [string]$process.ProcessName
        trusted_by = [string]$entry.reason
    }
}

if (-not (Wait-PortReleased -Port ([int]$descriptor.port) -TimeoutSeconds $WaitTimeoutSeconds)) {
    throw "environment $Environment port $($descriptor.port) is still listening after stop request"
}

$removedStateFiles = Remove-DescriptorStateFiles -Descriptor $descriptor
$payload = @{
    ok = $true
    environment = $Environment
    status = 'stopped'
    port = [int]$descriptor.port
    stopped_processes = $stopped
    removed_state_files = $removedStateFiles
}
$payload | ConvertTo-Json -Depth 10
exit 0
