param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8090,
    [string]$RuntimeRoot = ".runtime",
    [string]$RuntimeEnvironment = "",
    [string]$RuntimeControlRoot = "",
    [string]$RuntimeManifestPath = "",
    [string]$RuntimeVersion = "",
    [string]$RuntimePidFile = "",
    [string]$RuntimeInstanceFile = "",
    [string]$RuntimeDeployRoot = "",
    [switch]$SkipBackfill,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot 'workflow_env_common.ps1')

$workspaceRoot = Get-WorkflowSourceRoot -ScriptRoot $PSScriptRoot
$workspaceDir = Get-Item -LiteralPath $workspaceRoot
$isDeployedCopy = $workspaceDir.Parent -and $workspaceDir.Parent.Name -eq '.running'

if (-not $isDeployedCopy) {
    & (Join-Path $workspaceRoot 'scripts\start_workflow_env.ps1') `
        -Environment prod `
        -BindHost $BindHost `
        -Port $Port `
        -SkipBackfill:$SkipBackfill `
        -OpenBrowser:$OpenBrowser
    exit $LASTEXITCODE
}

$deploymentMetaPath = Join-Path $workspaceRoot '.workflow-deployment.json'
$deploymentMeta = Read-WorkflowJson -Path $deploymentMetaPath -Default @{}
$environment = if (-not [string]::IsNullOrWhiteSpace($RuntimeEnvironment)) {
    $RuntimeEnvironment
} else {
    [string]$deploymentMeta['environment']
}
if ([string]::IsNullOrWhiteSpace($environment)) {
    $environment = [string]$workspaceDir.Name
}
$controlRoot = if (-not [string]::IsNullOrWhiteSpace($RuntimeControlRoot)) {
    [System.IO.Path]::GetFullPath($RuntimeControlRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot '..\control'))
}
$manifestPath = if (-not [string]::IsNullOrWhiteSpace($RuntimeManifestPath)) {
    [System.IO.Path]::GetFullPath($RuntimeManifestPath)
} else {
    Join-Path (Join-Path $controlRoot 'envs') ($environment + '.json')
}
$manifest = Read-WorkflowJson -Path $manifestPath -Default @{}

$effectiveHost = if ([string]::IsNullOrWhiteSpace($BindHost) -and -not [string]::IsNullOrWhiteSpace([string]$manifest['host'])) {
    [string]$manifest['host']
} else {
    $BindHost
}
if ([string]::IsNullOrWhiteSpace($effectiveHost)) {
    $effectiveHost = '127.0.0.1'
}

$effectivePort = if ($Port -eq 8090 -and [int]($manifest['port']) -gt 0) {
    [int]$manifest['port']
} else {
    $Port
}

$effectiveRuntimeRoot = $RuntimeRoot
if ($RuntimeRoot -eq '.runtime' -and -not [string]::IsNullOrWhiteSpace([string]$manifest['runtime_root'])) {
    $effectiveRuntimeRoot = [string]$manifest['runtime_root']
}

[Environment]::SetEnvironmentVariable('WORKFLOW_RUNTIME_ENV', $environment, 'Process')
[Environment]::SetEnvironmentVariable('WORKFLOW_RUNTIME_CONTROL_ROOT', $controlRoot, 'Process')
[Environment]::SetEnvironmentVariable('WORKFLOW_RUNTIME_MANIFEST_PATH', $manifestPath, 'Process')
$effectiveDeployRoot = if (-not [string]::IsNullOrWhiteSpace($RuntimeDeployRoot)) {
    [System.IO.Path]::GetFullPath($RuntimeDeployRoot)
} else {
    $workspaceRoot
}
[Environment]::SetEnvironmentVariable('WORKFLOW_RUNTIME_DEPLOY_ROOT', $effectiveDeployRoot, 'Process')
$effectiveVersion = if (-not [string]::IsNullOrWhiteSpace($RuntimeVersion)) {
    $RuntimeVersion
} else {
    [string]$deploymentMeta['version']
}
if (-not [string]::IsNullOrWhiteSpace($effectiveVersion)) {
    [Environment]::SetEnvironmentVariable('WORKFLOW_RUNTIME_VERSION', $effectiveVersion, 'Process')
}
$effectivePidFile = if (-not [string]::IsNullOrWhiteSpace($RuntimePidFile)) { $RuntimePidFile } else { [string]$manifest['pid_file'] }
if (-not [string]::IsNullOrWhiteSpace($effectivePidFile)) {
    [Environment]::SetEnvironmentVariable('WORKFLOW_RUNTIME_PID_FILE', $effectivePidFile, 'Process')
}
$effectiveInstanceFile = if (-not [string]::IsNullOrWhiteSpace($RuntimeInstanceFile)) { $RuntimeInstanceFile } else { [string]$manifest['instance_file'] }
if (-not [string]::IsNullOrWhiteSpace($effectiveInstanceFile)) {
    [Environment]::SetEnvironmentVariable('WORKFLOW_RUNTIME_INSTANCE_FILE', $effectiveInstanceFile, 'Process')
}

$runtimeConfigPatch = @{}
if (-not [string]::IsNullOrWhiteSpace([string]$manifest['agent_search_root'])) {
    $runtimeConfigPatch['agent_search_root'] = [string]$manifest['agent_search_root']
}
$manifestArtifactRoot = if (-not [string]::IsNullOrWhiteSpace([string]$manifest['task_artifact_root'])) {
    [string]$manifest['task_artifact_root']
} else {
    [string]$manifest['artifact_root']
}
if (-not [string]::IsNullOrWhiteSpace($manifestArtifactRoot)) {
    $runtimeConfigPatch['artifact_root'] = $manifestArtifactRoot
    $runtimeConfigPatch['task_artifact_root'] = $manifestArtifactRoot
}
if ($manifest.ContainsKey('show_test_data')) {
    $runtimeConfigPatch['show_test_data'] = [bool]$manifest['show_test_data']
}
if ($runtimeConfigPatch.Count -gt 0) {
    Write-WorkflowRuntimeConfig -RuntimeRoot $effectiveRuntimeRoot -Patch $runtimeConfigPatch | Out-Null
}

& (Join-Path $PSScriptRoot "dev/launch_workflow.ps1") `
    -BindHost $effectiveHost `
    -Port $effectivePort `
    -RuntimeRoot $effectiveRuntimeRoot `
    -SkipBackfill:$SkipBackfill `
    -OpenBrowser:$OpenBrowser
exit $LASTEXITCODE
