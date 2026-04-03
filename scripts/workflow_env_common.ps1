Set-StrictMode -Version Latest

$script:WorkflowUtf8NoBom = New-Object System.Text.UTF8Encoding($false)

$script:WorkflowEnvPorts = @{
    dev  = 8091
    test = 8092
    prod = 8090
}

$script:WorkflowVersionTimeZoneId = 'China Standard Time'

$script:WorkflowCopyExcludeDirs = @(
    '.git',
    '.running',
    '.runtime',
    '.test',
    '.tmp',
    '.tmp*',
    '.codex',
    'state',
    'logs',
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache'
)

$script:WorkflowCopyExcludeFiles = @(
    '.tmp*'
)

function ConvertTo-WorkflowPlainData {
    param(
        [Parameter(ValueFromPipeline = $true)]
        [AllowNull()]
        [object]$Value
    )

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [string] -or $Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [bool]) {
        return $Value
    }
    if ($Value -is [datetime]) {
        return $Value.ToString('o')
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = @{}
        foreach ($key in $Value.Keys) {
            $result[[string]$key] = ConvertTo-WorkflowPlainData $Value[$key]
        }
        return $result
    }
    $properties = @()
    try {
        $properties = @($Value.PSObject.Properties)
    }
    catch {
        $properties = @()
    }
    if ($properties.Count -gt 0) {
        $result = @{}
        foreach ($prop in $properties) {
            $result[[string]$prop.Name] = ConvertTo-WorkflowPlainData $prop.Value
        }
        return $result
    }
    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $items = @()
        foreach ($item in $Value) {
            $items += ,(ConvertTo-WorkflowPlainData $item)
        }
        return $items
    }
    return [string]$Value
}

function Get-WorkflowVersionTimestamp {
    $utcNow = [DateTime]::UtcNow
    try {
        $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById($script:WorkflowVersionTimeZoneId)
        return [System.TimeZoneInfo]::ConvertTimeFromUtc($utcNow, $tz).ToString('yyyyMMdd-HHmmss')
    }
    catch {
        return (Get-Date).ToString('yyyyMMdd-HHmmss')
    }
}

function Read-WorkflowJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter()]
        [object]$Default = $null
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return ConvertTo-WorkflowPlainData $Default
    }
    try {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return ConvertTo-WorkflowPlainData $Default
        }
        return ConvertTo-WorkflowPlainData ($raw | ConvertFrom-Json)
    }
    catch {
        return ConvertTo-WorkflowPlainData $Default
    }
}

function Write-WorkflowJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$Payload
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $json = ConvertTo-WorkflowPlainData $Payload | ConvertTo-Json -Depth 32
    [System.IO.File]::WriteAllText($Path, ($json + [Environment]::NewLine), $script:WorkflowUtf8NoBom)
}

function Append-WorkflowJsonLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$Payload
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $line = ConvertTo-WorkflowPlainData $Payload | ConvertTo-Json -Depth 32 -Compress
    [System.IO.File]::AppendAllText($Path, ($line + [Environment]::NewLine), $script:WorkflowUtf8NoBom)
}

function Get-WorkflowSourceRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptRoot
    )

    return [System.IO.Path]::GetFullPath((Join-Path $ScriptRoot '..'))
}

function Get-WorkflowRunningRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    return (Join-Path $SourceRoot '.running')
}

function Get-WorkflowControlRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    return (Join-Path (Get-WorkflowRunningRoot -SourceRoot $SourceRoot) 'control')
}

function Get-WorkflowEnvironmentPort {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test', 'prod')]
        [string]$Environment
    )

    return [int]$script:WorkflowEnvPorts[$Environment]
}

function Get-WorkflowEnvironmentManifestPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test', 'prod')]
        [string]$Environment
    )

    return (Join-Path (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'envs') ($Environment + '.json'))
}

function Get-WorkflowEnvironmentRuntimeRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test', 'prod')]
        [string]$Environment
    )

    return (Join-Path (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'runtime') $Environment)
}

function Get-WorkflowEnvironmentPidFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test', 'prod')]
        [string]$Environment
    )

    return (Join-Path (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'pids') ($Environment + '.pid'))
}

function Get-WorkflowEnvironmentInstanceFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test', 'prod')]
        [string]$Environment
    )

    return (Join-Path (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'instances') ($Environment + '.json'))
}

function Get-WorkflowEnvironmentLogRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test', 'prod')]
        [string]$Environment
    )

    return (Join-Path (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'logs') $Environment)
}

function Get-WorkflowNormalizedFullPath {
    param(
        [Parameter()]
        [AllowEmptyString()]
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ''
    }
    try {
        return [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    }
    catch {
        return ''
    }
}

function Test-WorkflowSamePath {
    param(
        [Parameter()]
        [AllowEmptyString()]
        [string]$Left,
        [Parameter()]
        [AllowEmptyString()]
        [string]$Right
    )

    $leftPath = Get-WorkflowNormalizedFullPath -Path $Left
    $rightPath = Get-WorkflowNormalizedFullPath -Path $Right
    if ([string]::IsNullOrWhiteSpace($leftPath) -or [string]::IsNullOrWhiteSpace($rightPath)) {
        return $false
    }
    return [string]::Equals($leftPath, $rightPath, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-WorkflowEnvironmentLocalDeploymentMarkerPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test', 'prod')]
        [string]$Environment
    )

    return (Join-Path (Join-Path (Get-WorkflowRunningRoot -SourceRoot $SourceRoot) $Environment) '.workflow-local-deployment.json')
}

function Write-WorkflowLocalDeploymentMarker {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Descriptor,
        [Parameter(Mandatory = $true)]
        [string]$Version,
        [Parameter(Mandatory = $true)]
        [string]$DeployedAt
    )

    $markerPath = Get-WorkflowEnvironmentLocalDeploymentMarkerPath `
        -SourceRoot ([string]$Descriptor.source_root) `
        -Environment ([string]$Descriptor.environment)
    Write-WorkflowJson -Path $markerPath -Payload @{
        environment   = [string]$Descriptor.environment
        version       = $Version
        deployed_at   = $DeployedAt
        source_root   = [string]$Descriptor.source_root
        deploy_root   = [string]$Descriptor.deploy_root
        control_root  = [string]$Descriptor.control_root
        runtime_root  = [string]$Descriptor.runtime_root
        manifest_path = [string]$Descriptor.manifest_path
        marker_kind   = 'local_deployment'
    }
    return $markerPath
}

function Get-WorkflowGitRepositoryRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCommand) {
        return ''
    }
    try {
        $output = & $gitCommand.Source -C $SourceRoot rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -ne 0) {
            return ''
        }
        $gitRoot = [string]($output | Select-Object -First 1)
        return (Get-WorkflowNormalizedFullPath -Path $gitRoot.Trim())
    }
    catch {
        return ''
    }
}

function Get-WorkflowProdGitProtectedPathspecs {
    return @(
        '.running/prod',
        '.running/control/runtime/prod',
        '.running/control/envs/prod.json',
        '.running/control/instances/prod.json',
        '.running/control/pids/prod.pid',
        '.running/control/logs/prod',
        '.running/control/prod-candidate.json',
        '.running/control/prod-last-action.json',
        '.running/control/prod-upgrade-request.json',
        '.running/control/deployment-events.jsonl'
    )
}

function Invoke-WorkflowGitSkipWorktree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$GitRoot,
        [Parameter(Mandatory = $true)]
        [string[]]$RelativePaths
    )

    $gitCommand = (Get-Command git -ErrorAction Stop).Source
    $paths = @(
        $RelativePaths |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
            ForEach-Object { [string]$_ } |
            Sort-Object -Unique
    )
    if ($paths.Count -eq 0) {
        return 0
    }
    $updatedCount = 0
    $chunk = New-Object System.Collections.Generic.List[string]
    $chunkCharCount = 0
    foreach ($relativePath in $paths) {
        $pathLength = ([string]$relativePath).Length + 1
        if ($chunk.Count -gt 0 -and ($chunk.Count -ge 60 -or ($chunkCharCount + $pathLength) -gt 6000)) {
            & $gitCommand -C $GitRoot update-index --skip-worktree -- @($chunk.ToArray()) 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "git update-index --skip-worktree failed in $GitRoot"
            }
            $updatedCount += $chunk.Count
            $chunk.Clear()
            $chunkCharCount = 0
        }
        $chunk.Add($relativePath)
        $chunkCharCount += $pathLength
    }
    if ($chunk.Count -gt 0) {
        & $gitCommand -C $GitRoot update-index --skip-worktree -- @($chunk.ToArray()) 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "git update-index --skip-worktree failed in $GitRoot"
        }
        $updatedCount += $chunk.Count
        $chunk.Clear()
        $chunkCharCount = 0
    }
    return $updatedCount
}

function Protect-WorkflowProdGitRuntimeState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    $gitRoot = Get-WorkflowGitRepositoryRoot -SourceRoot $SourceRoot
    if ([string]::IsNullOrWhiteSpace($gitRoot)) {
        return @{
            ok            = $true
            applied       = $false
            reason        = 'git_unavailable_or_not_repo'
            git_root      = ''
            tracked_count = 0
            updated_count = 0
        }
    }
    $gitCommand = (Get-Command git -ErrorAction Stop).Source
    $trackedFiles = @()
    try {
        $trackedFiles = & $gitCommand -C $gitRoot -c core.quotePath=false ls-files -- @(Get-WorkflowProdGitProtectedPathspecs) 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "git ls-files failed in $gitRoot"
        }
    }
    catch {
        return @{
            ok            = $false
            applied       = $false
            reason        = 'git_ls_files_failed'
            error         = $_.Exception.Message
            git_root      = $gitRoot
            tracked_count = 0
            updated_count = 0
        }
    }
    $uniqueTracked = @(
        $trackedFiles |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
            ForEach-Object { ([string]$_).Trim() } |
            Sort-Object -Unique
    )
    if ($uniqueTracked.Count -eq 0) {
        return @{
            ok            = $true
            applied       = $false
            reason        = 'no_tracked_prod_runtime_paths'
            git_root      = $gitRoot
            tracked_count = 0
            updated_count = 0
        }
    }
    try {
        $updatedCount = Invoke-WorkflowGitSkipWorktree -GitRoot $gitRoot -RelativePaths $uniqueTracked
        return @{
            ok            = $true
            applied       = $true
            reason        = 'protected'
            git_root      = $gitRoot
            tracked_count = $uniqueTracked.Count
            updated_count = $updatedCount
        }
    }
    catch {
        return @{
            ok            = $false
            applied       = $false
            reason        = 'git_update_index_failed'
            error         = $_.Exception.Message
            git_root      = $gitRoot
            tracked_count = $uniqueTracked.Count
            updated_count = 0
        }
    }
}

function Get-WorkflowProdCandidatePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    return (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'prod-candidate.json')
}

function Get-WorkflowCandidateVersionRank {
    param(
        [Parameter()]
        [hashtable]$Candidate = @{}
    )

    foreach ($key in @('version_rank', 'current_version_rank', 'version', 'current_version')) {
        $value = [string]$Candidate[$key]
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
    }
    return ''
}

function Test-WorkflowCandidateComplete {
    param(
        [Parameter()]
        [hashtable]$Candidate = @{}
    )

    $evidencePath = [string]$Candidate['evidence_path']
    $candidateAppRoot = [string]$Candidate['candidate_app_root']
    if ([string]::IsNullOrWhiteSpace($evidencePath) -or [string]::IsNullOrWhiteSpace($candidateAppRoot)) {
        return $false
    }
    return (Test-Path -LiteralPath $evidencePath) -and (Test-Path -LiteralPath $candidateAppRoot)
}

function Get-WorkflowTestManifestCandidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    $manifestPath = Get-WorkflowEnvironmentManifestPath -SourceRoot $SourceRoot -Environment 'test'
    $manifest = Read-WorkflowJson -Path $manifestPath -Default @{}
    $testGateStatus = [string]$manifest['latest_test_gate_status']
    if ((-not [string]::IsNullOrWhiteSpace($testGateStatus)) -and ($testGateStatus.Trim().ToLowerInvariant() -ne 'passed')) {
        return @{}
    }
    $version = [string]$manifest['latest_candidate_version']
    $candidateAppRoot = [string]$manifest['latest_candidate_path']
    $evidencePath = [string]$manifest['latest_test_gate_evidence']
    if ([string]::IsNullOrWhiteSpace($version) -or [string]::IsNullOrWhiteSpace($candidateAppRoot) -or [string]::IsNullOrWhiteSpace($evidencePath)) {
        return @{}
    }
    $controlRoot = [string]$manifest['control_root']
    $candidateMetaPath = ''
    if (-not [string]::IsNullOrWhiteSpace($controlRoot)) {
        $candidateMetaPath = [System.IO.Path]::GetFullPath((Join-Path (Join-Path $controlRoot 'candidates') (Join-Path $version 'candidate.json')))
    }
    return @{
        version              = $version.Trim()
        version_rank         = $version.Trim()
        source_environment   = 'test'
        test_batch_id        = ('test-gate-' + $version.Trim())
        passed_at            = [string]$manifest['latest_candidate_created_at']
        evidence_path        = [System.IO.Path]::GetFullPath($evidencePath)
        candidate_app_root   = [System.IO.Path]::GetFullPath($candidateAppRoot)
        candidate_meta_path  = $candidateMetaPath
        source_root          = [string]$manifest['source_root']
        source_control_root  = $controlRoot
        source_manifest_path = [string]$manifest['manifest_path']
    }
}

function Sync-WorkflowProdCandidateFromTest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    $candidatePath = Get-WorkflowProdCandidatePath -SourceRoot $SourceRoot
    $localCandidate = Read-WorkflowJson -Path $candidatePath -Default @{}
    $testCandidate = Get-WorkflowTestManifestCandidate -SourceRoot $SourceRoot
    $localRank = Get-WorkflowCandidateVersionRank -Candidate $localCandidate
    $testRank = Get-WorkflowCandidateVersionRank -Candidate $testCandidate
    $localComplete = Test-WorkflowCandidateComplete -Candidate $localCandidate
    $testComplete = Test-WorkflowCandidateComplete -Candidate $testCandidate

    $preferred = $localCandidate
    $preferTestCandidate = $false
    if (($testCandidate.Count -gt 0) -and $testComplete) {
        if (-not $localComplete) {
            $preferTestCandidate = $true
        }
        elseif ($testRank -gt $localRank) {
            $preferTestCandidate = $true
        }
        elseif (($testRank -eq $localRank) -and ($localCandidate.Count -eq 0)) {
            $preferTestCandidate = $true
        }
    }
    if ($preferTestCandidate) {
        $preferred = $testCandidate
        Write-WorkflowJson -Path $candidatePath -Payload $preferred
    }
    if ($preferred.Count -gt 0) {
        $preferred['candidate_record_path'] = $candidatePath
    }
    return $preferred
}

function Get-WorkflowProdUpgradeRequestPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    return (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'prod-upgrade-request.json')
}

function Get-WorkflowProdLastActionPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    return (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'prod-last-action.json')
}

function Get-WorkflowDeploymentEventsPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    return (Join-Path (Get-WorkflowControlRoot -SourceRoot $SourceRoot) 'deployment-events.jsonl')
}

function Get-WorkflowRuntimeConfigPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeRoot
    )

    return (Join-Path (Join-Path $RuntimeRoot 'state') 'runtime-config.json')
}

function Get-WorkflowRuntimeConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeRoot
    )

    return (Read-WorkflowJson -Path (Get-WorkflowRuntimeConfigPath -RuntimeRoot $RuntimeRoot) -Default @{})
}

function Write-WorkflowRuntimeConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeRoot,
        [Parameter(Mandatory = $true)]
        [hashtable]$Patch
    )

    $existing = Get-WorkflowRuntimeConfig -RuntimeRoot $RuntimeRoot
    $next = @{}
    foreach ($pair in $existing.GetEnumerator()) {
        $next[$pair.Key] = $pair.Value
    }
    foreach ($pair in $Patch.GetEnumerator()) {
        $next[$pair.Key] = $pair.Value
    }
    Write-WorkflowJson -Path (Get-WorkflowRuntimeConfigPath -RuntimeRoot $RuntimeRoot) -Payload $next
    return $next
}

function Ensure-WorkflowControlDirs {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    $controlRoot = Get-WorkflowControlRoot -SourceRoot $SourceRoot
    @(
        $controlRoot,
        (Join-Path $controlRoot 'envs'),
        (Join-Path $controlRoot 'runtime'),
        (Join-Path $controlRoot 'logs'),
        (Join-Path $controlRoot 'pids'),
        (Join-Path $controlRoot 'instances'),
        (Join-Path $controlRoot 'candidates'),
        (Join-Path $controlRoot 'backups'),
        (Join-Path $controlRoot 'reports')
    ) | ForEach-Object {
        New-Item -ItemType Directory -Path $_ -Force | Out-Null
    }
}

function Copy-WorkflowTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [Parameter(Mandatory = $true)]
        [string]$TargetPath,
        [Parameter()]
        [string[]]$ExcludeDirs = @(),
        [Parameter()]
        [string[]]$ExcludeFiles = @()
    )

    New-Item -ItemType Directory -Path $TargetPath -Force | Out-Null
    $args = @(
        $SourcePath,
        $TargetPath,
        '/MIR',
        '/R:1',
        '/W:1',
        '/NFL',
        '/NDL',
        '/NJH',
        '/NJS',
        '/NP'
    )
    if ($ExcludeDirs.Count -gt 0) {
        $args += '/XD'
        $args += $ExcludeDirs
    }
    if ($ExcludeFiles.Count -gt 0) {
        $args += '/XF'
        $args += $ExcludeFiles
    }
    & robocopy @args | Out-Null
    $robocopyExitCode = $LASTEXITCODE
    if ($robocopyExitCode -gt 7) {
        throw "robocopy failed with exit code $robocopyExitCode"
    }
    $global:LASTEXITCODE = 0
}

function Get-WorkflowDefaultArtifactRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot
    )

    $sourceConfig = Read-WorkflowJson -Path (Join-Path $SourceRoot '.runtime\state\runtime-config.json') -Default @{}
    $configured = [string]($sourceConfig['artifact_root'])
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        return [System.IO.Path]::GetFullPath($configured)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Split-Path $SourceRoot -Parent) '.output'))
}

function Get-WorkflowDerivedArtifactRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseArtifactRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test')]
        [string]$Environment
    )

    $trimmed = $BaseArtifactRoot.TrimEnd('\', '/')
    $leaf = Split-Path $trimmed -Leaf
    $parent = Split-Path $trimmed -Parent
    if ([string]::IsNullOrWhiteSpace($leaf)) {
        return [System.IO.Path]::GetFullPath((Join-Path $trimmed ("workflow-output-" + $Environment)))
    }
    return [System.IO.Path]::GetFullPath((Join-Path $parent ($leaf + '-' + $Environment)))
}

function Resolve-WorkflowEnvironmentDescriptor {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet('dev', 'test', 'prod')]
        [string]$Environment,
        [Parameter()]
        [string]$AgentSearchRoot = '',
        [Parameter()]
        [string]$ArtifactRoot = '',
        [Parameter()]
        [string]$BindHost = '',
        [Parameter()]
        [int]$Port = 0
    )

    Ensure-WorkflowControlDirs -SourceRoot $SourceRoot
    $runningRoot = Get-WorkflowRunningRoot -SourceRoot $SourceRoot
    $deployRoot = Join-Path $runningRoot $Environment
    $runtimeRoot = Get-WorkflowEnvironmentRuntimeRoot -SourceRoot $SourceRoot -Environment $Environment
    $manifestPath = Get-WorkflowEnvironmentManifestPath -SourceRoot $SourceRoot -Environment $Environment
    $manifest = Read-WorkflowJson -Path $manifestPath -Default @{}
    $runtimeConfig = Get-WorkflowRuntimeConfig -RuntimeRoot $runtimeRoot
    $sourceConfig = Read-WorkflowJson -Path (Join-Path $SourceRoot '.runtime\state\runtime-config.json') -Default @{}
    $prodRuntimeRoot = Get-WorkflowEnvironmentRuntimeRoot -SourceRoot $SourceRoot -Environment 'prod'
    $prodRuntimeConfig = Get-WorkflowRuntimeConfig -RuntimeRoot $prodRuntimeRoot
    $prodArtifactBase = if (-not [string]::IsNullOrWhiteSpace([string]$prodRuntimeConfig['artifact_root'])) {
        [string]$prodRuntimeConfig['artifact_root']
    }
    else {
        Get-WorkflowDefaultArtifactRoot -SourceRoot $SourceRoot
    }

    $resolvedAgentRoot = if (-not [string]::IsNullOrWhiteSpace($AgentSearchRoot)) {
        $AgentSearchRoot
    }
    elseif (-not [string]::IsNullOrWhiteSpace([string]$runtimeConfig['agent_search_root'])) {
        [string]$runtimeConfig['agent_search_root']
    }
    elseif (-not [string]::IsNullOrWhiteSpace([string]$sourceConfig['agent_search_root'])) {
        [string]$sourceConfig['agent_search_root']
    }
    else {
        [System.IO.Path]::GetFullPath((Split-Path $SourceRoot -Parent))
    }

    $resolvedArtifactRoot = if (-not [string]::IsNullOrWhiteSpace($ArtifactRoot)) {
        $ArtifactRoot
    }
    elseif (-not [string]::IsNullOrWhiteSpace([string]$runtimeConfig['artifact_root'])) {
        [string]$runtimeConfig['artifact_root']
    }
    elseif ($Environment -eq 'prod') {
        $prodArtifactBase
    }
    else {
        Get-WorkflowDerivedArtifactRoot -BaseArtifactRoot $prodArtifactBase -Environment $Environment
    }

    $resolvedHost = if (-not [string]::IsNullOrWhiteSpace($BindHost)) {
        $BindHost
    }
    elseif (-not [string]::IsNullOrWhiteSpace([string]$manifest['host'])) {
        [string]$manifest['host']
    }
    else {
        '127.0.0.1'
    }

    $resolvedPort = if ($Port -gt 0) {
        $Port
    }
    elseif ([int]($manifest['port']) -gt 0) {
        [int]$manifest['port']
    }
    else {
        Get-WorkflowEnvironmentPort -Environment $Environment
    }

    $versionText = [string]$manifest['current_version']
    if ([string]::IsNullOrWhiteSpace($versionText)) {
        $versionText = ''
    }

    return @{
        environment     = $Environment
        source_root     = [System.IO.Path]::GetFullPath($SourceRoot)
        running_root    = [System.IO.Path]::GetFullPath($runningRoot)
        control_root    = [System.IO.Path]::GetFullPath((Get-WorkflowControlRoot -SourceRoot $SourceRoot))
        deploy_root     = [System.IO.Path]::GetFullPath($deployRoot)
        runtime_root    = [System.IO.Path]::GetFullPath($runtimeRoot)
        host            = $resolvedHost
        port            = [int]$resolvedPort
        agent_search_root = [System.IO.Path]::GetFullPath($resolvedAgentRoot)
        artifact_root   = [System.IO.Path]::GetFullPath($resolvedArtifactRoot)
        manifest_path   = [System.IO.Path]::GetFullPath($manifestPath)
        pid_file        = [System.IO.Path]::GetFullPath((Get-WorkflowEnvironmentPidFile -SourceRoot $SourceRoot -Environment $Environment))
        instance_file   = [System.IO.Path]::GetFullPath((Get-WorkflowEnvironmentInstanceFile -SourceRoot $SourceRoot -Environment $Environment))
        log_root        = [System.IO.Path]::GetFullPath((Get-WorkflowEnvironmentLogRoot -SourceRoot $SourceRoot -Environment $Environment))
        version         = $versionText
    }
}

function Assert-WorkflowArtifactIsolation {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Descriptor
    )

    $environment = [string]$Descriptor.environment
    if ($environment -eq 'prod') {
        return
    }
    $sourceRoot = [string]$Descriptor.source_root
    $prodManifest = Read-WorkflowJson -Path (Get-WorkflowEnvironmentManifestPath -SourceRoot $sourceRoot -Environment 'prod') -Default @{}
    $prodConfig = Get-WorkflowRuntimeConfig -RuntimeRoot (Get-WorkflowEnvironmentRuntimeRoot -SourceRoot $sourceRoot -Environment 'prod')
    $prodArtifactRoot = if (-not [string]::IsNullOrWhiteSpace([string]$prodManifest['artifact_root'])) {
        [System.IO.Path]::GetFullPath([string]$prodManifest['artifact_root'])
    }
    elseif (-not [string]::IsNullOrWhiteSpace([string]$prodConfig['artifact_root'])) {
        [System.IO.Path]::GetFullPath([string]$prodConfig['artifact_root'])
    }
    else {
        Get-WorkflowDefaultArtifactRoot -SourceRoot $sourceRoot
    }
    $currentArtifactRoot = [System.IO.Path]::GetFullPath([string]$Descriptor.artifact_root)
    if ($currentArtifactRoot.TrimEnd('\', '/') -ieq $prodArtifactRoot.TrimEnd('\', '/')) {
        throw "环境 $environment 的任务产物路径与 prod 冲突：$currentArtifactRoot。请改用独立路径后再部署或启动。"
    }
}

function Write-WorkflowEnvironmentManifest {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Descriptor,
        [Parameter()]
        [hashtable]$Extra = @{}
    )

    $existing = Read-WorkflowJson -Path ([string]$Descriptor.manifest_path) -Default @{}
    $payload = @{}
    foreach ($pair in $existing.GetEnumerator()) {
        $payload[$pair.Key] = $pair.Value
    }
    foreach ($pair in $Descriptor.GetEnumerator()) {
        $payload[$pair.Key] = $pair.Value
    }
    foreach ($pair in $Extra.GetEnumerator()) {
        $payload[$pair.Key] = $pair.Value
    }
    $payload['updated_at'] = (Get-Date).ToUniversalTime().ToString('o')
    Write-WorkflowJson -Path ([string]$Descriptor.manifest_path) -Payload $payload
    return $payload
}

function Write-WorkflowDeploymentEvent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [hashtable]$Payload
    )

    $row = @{}
    foreach ($pair in $Payload.GetEnumerator()) {
        $row[$pair.Key] = $pair.Value
    }
    if (-not $row.ContainsKey('timestamp')) {
        $row['timestamp'] = (Get-Date).ToUniversalTime().ToString('o')
    }
    Append-WorkflowJsonLine -Path (Get-WorkflowDeploymentEventsPath -SourceRoot $SourceRoot) -Payload $row
}
