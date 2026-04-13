param(
    [string]$BaseUrl = "http://127.0.0.1:8090",
    [string]$TicketId = "asg-20260327-223335-b79f27",
    [string]$MainlineScheduleId = "sch-20260405-56eee156",
    [string]$PatrolScheduleId = "sch-20260405-67a89536",
    [string]$RunningNodeId = "node-sti-20260413-91bf50d7",
    [string]$ReadyNodeId = "node-sti-20260413-2047bcc6",
    [string]$RunningRunId = "arun-20260413-114317-7413d0",
    [string]$OldBaseline = "prod=20260413-103306",
    [string]$ExpectedBaseline = "prod=20260413-112439",
    [string]$ExpectedWorkspaceHead = "18c77de",
    [string]$UpgradeEffectiveAt = "2026-04-13T11:43:09+08:00",
    [string]$ExpectedMainlineTriggerAt = "2026-04-13T11:56:00+08:00",
    [string]$ExpectedPatrolTriggerAt = "2026-04-13T12:00:00+08:00",
    [string]$ObserveUntil = "2026-04-13T12:00:30+08:00",
    [int]$PollIntervalSeconds = 10,
    [int]$HttpTimeoutSec = 45,
    [int]$HttpRetryCount = 3,
    [int]$HttpRetryBackoffSeconds = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($env:TEST_ARTIFACTS_DIR)) {
    throw "TEST_ARTIFACTS_DIR is not set. Run this script via test-session-manager."
}

$artifactsDir = $env:TEST_ARTIFACTS_DIR
New-Item -Path $artifactsDir -ItemType Directory -Force | Out-Null

$taskRoot = Join-Path -Path "C:/work/J-Agents/.output/tasks" -ChildPath $TicketId
$auditPath = Join-Path -Path $taskRoot -ChildPath "audit/audit.jsonl"
$observeUntilDt = [DateTimeOffset]::Parse($ObserveUntil)
$expectedMainlineTriggerAtDt = [DateTimeOffset]::Parse($ExpectedMainlineTriggerAt)
$expectedPatrolTriggerAtDt = [DateTimeOffset]::Parse($ExpectedPatrolTriggerAt)

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [AllowEmptyString()]
        [string]$Content
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Save-JsonArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        $Object
    )

    $path = Join-Path -Path $artifactsDir -ChildPath $Name
    $json = $Object | ConvertTo-Json -Depth 100
    Write-Utf8File -Path $path -Content $json
    return $path
}

function Save-TextArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [AllowEmptyString()]
        [string]$Content
    )

    $path = Join-Path -Path $artifactsDir -ChildPath $Name
    Write-Utf8File -Path $path -Content $Content
    return $path
}

function Get-PropertyValue {
    param(
        $Object,
        [Parameter(Mandatory = $true)]
        [string]$PropertyName
    )

    if ($null -eq $Object) {
        return $null
    }

    $property = $Object.PSObject.Properties[$PropertyName]
    if ($null -eq $property) {
        return $null
    }

    return $property.Value
}

function Get-StringContains {
    param(
        [AllowNull()]
        [string]$Value,
        [Parameter(Mandatory = $true)]
        [string]$Needle
    )

    if ([string]::IsNullOrEmpty($Value)) {
        return $false
    }

    return $Value.Contains($Needle)
}

function Get-NonEmptyStrings {
    param(
        [AllowEmptyCollection()]
        [object[]]$Values = @()
    )

    $result = New-Object System.Collections.Generic.List[string]
    foreach ($value in $Values) {
        if ($null -eq $value) {
            continue
        }

        $text = [string]$value
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }

        $result.Add($text) | Out-Null
    }

    return @($result)
}

function Invoke-JsonGet {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string]$RelativePath,
        [int]$TimeoutSec = $HttpTimeoutSec,
        [int]$RetryCount = $HttpRetryCount,
        [int]$RetryBackoffSeconds = $HttpRetryBackoffSeconds
    )

    $uri = "{0}{1}" -f $BaseUrl.TrimEnd("/"), $RelativePath
    $lastError = $null

    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        try {
            Write-Host ("[http] {0} attempt={1} uri={2}" -f $Label, $attempt, $uri)
            $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec $TimeoutSec
            Save-TextArtifact -Name ("{0}.raw.txt" -f $Label) -Content $response.Content | Out-Null
            $parsed = $response.Content | ConvertFrom-Json
            Save-JsonArtifact -Name ("{0}.json" -f $Label) -Object $parsed | Out-Null
            return [pscustomobject]@{
                uri = $uri
                status_code = [int]$response.StatusCode
                body = $parsed
            }
        }
        catch {
            $lastError = $_
            Save-TextArtifact -Name ("{0}.error.txt" -f $Label) -Content ($_ | Out-String) | Out-Null
            if ($attempt -lt $RetryCount) {
                Start-Sleep -Seconds ($RetryBackoffSeconds * $attempt)
            }
        }
    }

    throw $lastError
}

function Copy-TextFileIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [Parameter(Mandatory = $true)]
        [string]$TargetName
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        return $false
    }

    $content = Get-Content -LiteralPath $SourcePath -Raw
    Save-TextArtifact -Name $TargetName -Content $content | Out-Null
    return $true
}

function Copy-RunFiles {
    param(
        [AllowNull()]
        [string]$RunId,
        [Parameter(Mandatory = $true)]
        [string]$Prefix
    )

    $result = [ordered]@{
        run_id = $RunId
        run_dir = $null
        files = [ordered]@{}
    }

    if ([string]::IsNullOrWhiteSpace($RunId)) {
        return $result
    }

    $runDir = Join-Path -Path (Join-Path -Path $taskRoot -ChildPath "runs") -ChildPath $RunId
    $result.run_dir = $runDir

    foreach ($name in @("run.json", "result.json", "stdout.txt", "stderr.txt", "events.log", "prompt.txt")) {
        $sourcePath = Join-Path -Path $runDir -ChildPath $name
        $targetName = "{0}-{1}" -f $Prefix, $name
        $copied = Copy-TextFileIfExists -SourcePath $sourcePath -TargetName $targetName
        $result.files[$name] = [ordered]@{
            source = $sourcePath
            copied = $copied
            artifact = if ($copied) { $targetName } else { $null }
        }
    }

    return $result
}

function Copy-NodeFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodeId,
        [Parameter(Mandatory = $true)]
        [string]$TargetName
    )

    $nodePath = Join-Path -Path (Join-Path -Path $taskRoot -ChildPath "nodes") -ChildPath ("{0}.json" -f $NodeId)
    $copied = Copy-TextFileIfExists -SourcePath $nodePath -TargetName $TargetName
    return [ordered]@{
        node_id = $NodeId
        node_path = $nodePath
        copied = $copied
        artifact = if ($copied) { $TargetName } else { $null }
    }
}

function Get-BaselineSnapshot {
    param(
        [AllowNull()]
        [string]$Text
    )

    return [ordered]@{
        baseline_old_seen = Get-StringContains -Value $Text -Needle $OldBaseline
        baseline_expected_seen = Get-StringContains -Value $Text -Needle $ExpectedBaseline
        workspace_head_seen = Get-StringContains -Value $Text -Needle ("workspace_head={0}" -f $ExpectedWorkspaceHead)
    }
}

function Get-NodeAssessment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string]$NodeId,
        [AllowNull()]
        [string]$KnownRunId
    )

    $statusDetail = Invoke-JsonGet -Label ("{0}-status-detail" -f $Label) -RelativePath ("/api/assignments/{0}/status-detail?node_id={1}&include_test_data=0" -f $TicketId, [uri]::EscapeDataString($NodeId))
    $nodeFileCopy = Copy-NodeFile -NodeId $NodeId -TargetName ("{0}-node.json" -f $Label)
    $nodeJson = $null
    if ($nodeFileCopy.copied) {
        $nodeJson = (Get-Content -LiteralPath $nodeFileCopy.node_path -Raw) | ConvertFrom-Json
    }

    $nodeGoal = Get-PropertyValue -Object $nodeJson -PropertyName "node_goal"
    $latestRunId = Get-PropertyValue -Object $statusDetail.body -PropertyName "latest_run_id"
    if ([string]::IsNullOrWhiteSpace($latestRunId)) {
        $latestRunId = $KnownRunId
    }

    $runFiles = Copy-RunFiles -RunId $latestRunId -Prefix ("{0}-run" -f $Label)
    $baselineSnapshot = Get-BaselineSnapshot -Text $nodeGoal

    return [ordered]@{
        label = $Label
        node_id = $NodeId
        status_detail = [ordered]@{
            status = Get-PropertyValue -Object $statusDetail.body -PropertyName "status"
            runtime_status = Get-PropertyValue -Object $statusDetail.body -PropertyName "runtime_status"
            latest_run_id = Get-PropertyValue -Object $statusDetail.body -PropertyName "latest_run_id"
            latest_event_at = Get-PropertyValue -Object $statusDetail.body -PropertyName "latest_event_at"
            planned_trigger_at = Get-PropertyValue -Object $statusDetail.body -PropertyName "planned_trigger_at"
            updated_at = Get-PropertyValue -Object $statusDetail.body -PropertyName "updated_at"
        }
        node_file = $nodeFileCopy
        node_status = Get-PropertyValue -Object $nodeJson -PropertyName "status"
        node_created_at = Get-PropertyValue -Object $nodeJson -PropertyName "created_at"
        node_updated_at = Get-PropertyValue -Object $nodeJson -PropertyName "updated_at"
        node_goal_snapshot = [ordered]@{
            baseline_old_seen = $baselineSnapshot.baseline_old_seen
            baseline_expected_seen = $baselineSnapshot.baseline_expected_seen
            workspace_head_seen = $baselineSnapshot.workspace_head_seen
        }
        run_files = $runFiles
    }
}

function Parse-TriggerTime {
    param(
        [AllowNull()]
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    try {
        return [DateTimeOffset]::Parse($Value)
    }
    catch {
        return $null
    }
}

function Get-TriggerSnapshot {
    param(
        [Parameter(Mandatory = $true)]
        $ScheduleBody,
        [Parameter(Mandatory = $true)]
        [DateTimeOffset]$ExpectedAt
    )

    $recentTriggers = @(Get-PropertyValue -Object $ScheduleBody -PropertyName "recent_triggers")
    if ($recentTriggers.Count -eq 0) {
        return $null
    }

    $selected = $recentTriggers |
        Where-Object {
            $planned = Parse-TriggerTime -Value (Get-PropertyValue -Object $_ -PropertyName "planned_trigger_at")
            ($null -ne $planned) -and ($planned -eq $ExpectedAt)
        } |
        Select-Object -First 1

    if ($null -eq $selected) {
        return $null
    }

    $launchSummarySnapshot = Get-PropertyValue -Object $selected -PropertyName "launch_summary_snapshot"
    $baselineSnapshot = Get-BaselineSnapshot -Text $launchSummarySnapshot

    return [ordered]@{
        observed = $true
        trigger_instance_id = Get-PropertyValue -Object $selected -PropertyName "trigger_instance_id"
        planned_trigger_at = Get-PropertyValue -Object $selected -PropertyName "planned_trigger_at"
        trigger_status = Get-PropertyValue -Object $selected -PropertyName "trigger_status"
        trigger_message = Get-PropertyValue -Object $selected -PropertyName "trigger_message"
        assignment_ticket_id = Get-PropertyValue -Object $selected -PropertyName "assignment_ticket_id"
        assignment_node_id = Get-PropertyValue -Object $selected -PropertyName "assignment_node_id"
        assignment_node_name = Get-PropertyValue -Object $selected -PropertyName "assignment_node_name"
        launch_summary_snapshot = $launchSummarySnapshot
        baseline_old_seen = $baselineSnapshot.baseline_old_seen
        baseline_expected_seen = $baselineSnapshot.baseline_expected_seen
        workspace_head_seen = $baselineSnapshot.workspace_head_seen
    }
}

function Expand-TriggerEvidence {
    param(
        [AllowNull()]
        $TriggerSnapshot,
        [Parameter(Mandatory = $true)]
        [string]$LabelPrefix
    )

    if ($null -eq $TriggerSnapshot) {
        return [ordered]@{
            observed = $false
        }
    }

    $nodeId = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "assignment_node_id"
    $statusDetail = $null
    if (-not [string]::IsNullOrWhiteSpace($nodeId)) {
        $statusDetail = Invoke-JsonGet -Label ("{0}-status-detail" -f $LabelPrefix) -RelativePath ("/api/assignments/{0}/status-detail?node_id={1}&include_test_data=0" -f $TicketId, [uri]::EscapeDataString($nodeId))
    }

    $nodeFile = $null
    $nodeJson = $null
    if (-not [string]::IsNullOrWhiteSpace($nodeId)) {
        $nodeFile = Copy-NodeFile -NodeId $nodeId -TargetName ("{0}-node.json" -f $LabelPrefix)
        if ($nodeFile.copied) {
            $nodeJson = (Get-Content -LiteralPath $nodeFile.node_path -Raw) | ConvertFrom-Json
        }
    }

    $latestRunId = if ($null -ne $statusDetail) { Get-PropertyValue -Object $statusDetail.body -PropertyName "latest_run_id" } else { $null }
    $runFiles = Copy-RunFiles -RunId $latestRunId -Prefix ("{0}-run" -f $LabelPrefix)

    return [ordered]@{
        observed = $true
        trigger_instance_id = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "trigger_instance_id"
        planned_trigger_at = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "planned_trigger_at"
        trigger_status = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "trigger_status"
        trigger_message = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "trigger_message"
        assignment_ticket_id = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "assignment_ticket_id"
        assignment_node_id = $nodeId
        assignment_node_name = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "assignment_node_name"
        launch_summary_snapshot = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "launch_summary_snapshot"
        baseline_old_seen = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "baseline_old_seen"
        baseline_expected_seen = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "baseline_expected_seen"
        workspace_head_seen = Get-PropertyValue -Object $TriggerSnapshot -PropertyName "workspace_head_seen"
        status_detail = if ($null -ne $statusDetail) {
            [ordered]@{
                status = Get-PropertyValue -Object $statusDetail.body -PropertyName "status"
                runtime_status = Get-PropertyValue -Object $statusDetail.body -PropertyName "runtime_status"
                latest_run_id = Get-PropertyValue -Object $statusDetail.body -PropertyName "latest_run_id"
                latest_event_at = Get-PropertyValue -Object $statusDetail.body -PropertyName "latest_event_at"
                updated_at = Get-PropertyValue -Object $statusDetail.body -PropertyName "updated_at"
            }
        }
        else {
            $null
        }
        node_file = $nodeFile
        node_status = if ($null -ne $nodeJson) { Get-PropertyValue -Object $nodeJson -PropertyName "status" } else { $null }
        node_created_at = if ($null -ne $nodeJson) { Get-PropertyValue -Object $nodeJson -PropertyName "created_at" } else { $null }
        run_files = $runFiles
    }
}

function Read-AuditLines {
    param(
        [string[]]$Patterns = @()
    )

    $filteredPatterns = Get-NonEmptyStrings -Values $Patterns
    if ($filteredPatterns.Count -eq 0) {
        return @()
    }

    if (-not (Test-Path -LiteralPath $auditPath)) {
        return @()
    }

    $lines = Get-Content -LiteralPath $auditPath
    return $lines | Where-Object {
        $line = $_
        foreach ($pattern in $filteredPatterns) {
            if ($line -like ("*{0}*" -f $pattern)) {
                return $true
            }
        }

        return $false
    }
}

function Get-TriggerAuditPatterns {
    param(
        [AllowNull()]
        $TriggerEvidence
    )

    if ($null -eq $TriggerEvidence) {
        return @()
    }

    if (-not (Get-PropertyValue -Object $TriggerEvidence -PropertyName "observed")) {
        return @()
    }

    return Get-NonEmptyStrings -Values @(
        Get-PropertyValue -Object $TriggerEvidence -PropertyName "trigger_instance_id",
        Get-PropertyValue -Object $TriggerEvidence -PropertyName "assignment_node_id",
        Get-PropertyValue -Object (Get-PropertyValue -Object $TriggerEvidence -PropertyName "status_detail") -PropertyName "latest_run_id"
    )
}

$pollSnapshots = New-Object System.Collections.Generic.List[object]
$latestMainlineSchedule = $null
$latestPatrolSchedule = $null
$observedMainlineTrigger = $null
$observedPatrolTrigger = $null

do {
    $now = [DateTimeOffset]::Now

    # Poll schedules only during the observation window; heavy status-detail capture happens once at the end.
    $mainlineSchedule = Invoke-JsonGet -Label "04-mainline-schedule" -RelativePath ("/api/schedules/{0}" -f $MainlineScheduleId)
    $patrolSchedule = Invoke-JsonGet -Label "05-patrol-schedule" -RelativePath ("/api/schedules/{0}" -f $PatrolScheduleId)
    $latestMainlineSchedule = $mainlineSchedule.body
    $latestPatrolSchedule = $patrolSchedule.body

    $mainlineTrigger = Get-TriggerSnapshot -ScheduleBody $mainlineSchedule.body -ExpectedAt $expectedMainlineTriggerAtDt
    $patrolTrigger = Get-TriggerSnapshot -ScheduleBody $patrolSchedule.body -ExpectedAt $expectedPatrolTriggerAtDt

    if ($null -ne $mainlineTrigger) {
        $observedMainlineTrigger = $mainlineTrigger
    }

    if ($null -ne $patrolTrigger) {
        $observedPatrolTrigger = $patrolTrigger
    }

    $pollSnapshots.Add([ordered]@{
        observed_at = $now.ToString("o")
        mainline_expected_trigger_found = ($null -ne $mainlineTrigger)
        patrol_expected_trigger_found = ($null -ne $patrolTrigger)
        mainline_trigger_status = if ($null -ne $mainlineTrigger) { Get-PropertyValue -Object $mainlineTrigger -PropertyName "trigger_status" } else { $null }
        patrol_trigger_status = if ($null -ne $patrolTrigger) { Get-PropertyValue -Object $patrolTrigger -PropertyName "trigger_status" } else { $null }
        mainline_recent_trigger_ids = @(@(Get-PropertyValue -Object $mainlineSchedule.body -PropertyName "recent_triggers") | ForEach-Object { Get-PropertyValue -Object $_ -PropertyName "trigger_instance_id" })
        patrol_recent_trigger_ids = @(@(Get-PropertyValue -Object $patrolSchedule.body -PropertyName "recent_triggers") | ForEach-Object { Get-PropertyValue -Object $_ -PropertyName "trigger_instance_id" })
    }) | Out-Null

    if ($now -lt $observeUntilDt) {
        Start-Sleep -Seconds $PollIntervalSeconds
    }
} until ($now -ge $observeUntilDt)

$healthz = Invoke-JsonGet -Label "01-healthz" -RelativePath "/healthz"
$status = Invoke-JsonGet -Label "02-api-status" -RelativePath "/api/status"
$runtimeUpgrade = Invoke-JsonGet -Label "03-runtime-upgrade-status" -RelativePath "/api/runtime-upgrade/status"
$runningAssessment = Get-NodeAssessment -Label "06-running-mainline" -NodeId $RunningNodeId -KnownRunId $RunningRunId
$readyAssessment = Get-NodeAssessment -Label "07-ready-patrol" -NodeId $ReadyNodeId -KnownRunId $null
$observedMainlineEvidence = Expand-TriggerEvidence -TriggerSnapshot $observedMainlineTrigger -LabelPrefix "11-mainline-post-upgrade-trigger"
$observedPatrolEvidence = Expand-TriggerEvidence -TriggerSnapshot $observedPatrolTrigger -LabelPrefix "12-patrol-post-upgrade-trigger"

$auditPatterns = Get-NonEmptyStrings -Values @(
    $RunningNodeId,
    $ReadyNodeId,
    $RunningRunId,
    "sti-20260413-91bf50d7",
    "sti-20260413-2047bcc6",
    "2026-04-13T11:43:09+08:00",
    "20260413-112439",
    "20260413-103306",
    "sti-20260413-9d748706",
    "sti-20260413-f70e7360"
)
$auditPatterns += Get-TriggerAuditPatterns -TriggerEvidence $observedMainlineEvidence
$auditPatterns += Get-TriggerAuditPatterns -TriggerEvidence $observedPatrolEvidence

$auditLines = Read-AuditLines -Patterns $auditPatterns
$auditLines = @($auditLines | Select-Object -Unique)
Save-TextArtifact -Name "13-audit-lines.txt" -Content ($auditLines -join [Environment]::NewLine) | Out-Null
Save-JsonArtifact -Name "14-poll-snapshots.json" -Object $pollSnapshots | Out-Null

$mainlineScheduleLaunchSummary = Get-PropertyValue -Object (Get-PropertyValue -Object $latestMainlineSchedule -PropertyName "schedule") -PropertyName "launch_summary"
$patrolScheduleLaunchSummary = Get-PropertyValue -Object (Get-PropertyValue -Object $latestPatrolSchedule -PropertyName "schedule") -PropertyName "launch_summary"

$mainlineExpectedSnapshotSeen = ($observedMainlineEvidence.observed -and $observedMainlineEvidence.baseline_expected_seen -and $observedMainlineEvidence.workspace_head_seen)
$patrolExpectedSnapshotSeen = ($observedPatrolEvidence.observed -and $observedPatrolEvidence.baseline_expected_seen -and $observedPatrolEvidence.workspace_head_seen)

$summary = [ordered]@{
    collected_at = (Get-Date).ToString("o")
    base_url = $BaseUrl
    ticket_id = $TicketId
    collection_strategy = [ordered]@{
        trigger_polling = "schedule_only_during_observation_window"
        heavy_capture = "status-detail_node_run_after_observe_window"
        http_timeout_sec = $HttpTimeoutSec
        http_retry_count = $HttpRetryCount
    }
    observe_window = [ordered]@{
        upgrade_effective_at = $UpgradeEffectiveAt
        expected_mainline_trigger_at = $ExpectedMainlineTriggerAt
        expected_patrol_trigger_at = $ExpectedPatrolTriggerAt
        observe_until = $ObserveUntil
        poll_interval_seconds = $PollIntervalSeconds
    }
    expectations = [ordered]@{
        old_baseline = $OldBaseline
        expected_baseline = $ExpectedBaseline
        expected_workspace_head = $ExpectedWorkspaceHead
    }
    healthz = [ordered]@{
        ok = Get-PropertyValue -Object $healthz.body -PropertyName "ok"
        ts = Get-PropertyValue -Object $healthz.body -PropertyName "ts"
    }
    api_status = [ordered]@{
        running_task_count = Get-PropertyValue -Object $status.body -PropertyName "running_task_count"
        queued_task_count = Get-PropertyValue -Object $status.body -PropertyName "queued_task_count"
        truth_mismatch_count = Get-PropertyValue -Object $status.body -PropertyName "truth_mismatch_count"
        workflow_running_count = Get-PropertyValue -Object $status.body -PropertyName "workflow_running_count"
        workflow_queued_count = Get-PropertyValue -Object $status.body -PropertyName "workflow_queued_count"
        workflow_mainline_handoff_pending = Get-PropertyValue -Object $status.body -PropertyName "workflow_mainline_handoff_pending"
    }
    runtime_upgrade = [ordered]@{
        current_version = Get-PropertyValue -Object $runtimeUpgrade.body -PropertyName "current_version"
        candidate_version = Get-PropertyValue -Object $runtimeUpgrade.body -PropertyName "candidate_version"
        candidate_is_newer = Get-PropertyValue -Object $runtimeUpgrade.body -PropertyName "candidate_is_newer"
        request_pending = Get-PropertyValue -Object $runtimeUpgrade.body -PropertyName "request_pending"
        can_upgrade = Get-PropertyValue -Object $runtimeUpgrade.body -PropertyName "can_upgrade"
        blocking_reason_code = Get-PropertyValue -Object $runtimeUpgrade.body -PropertyName "blocking_reason_code"
        running_task_count = Get-PropertyValue -Object $runtimeUpgrade.body -PropertyName "running_task_count"
        last_action = Get-PropertyValue -Object $runtimeUpgrade.body -PropertyName "last_action"
    }
    schedule_baseline = [ordered]@{
        mainline = Get-BaselineSnapshot -Text $mainlineScheduleLaunchSummary
        patrol = Get-BaselineSnapshot -Text $patrolScheduleLaunchSummary
    }
    target_nodes = [ordered]@{
        running_mainline = $runningAssessment
        ready_patrol = $readyAssessment
    }
    post_upgrade_triggers = [ordered]@{
        mainline_1156 = $observedMainlineEvidence
        patrol_1200 = $observedPatrolEvidence
    }
    overall = [ordered]@{
        mainline_expected_trigger_observed = [bool]$observedMainlineEvidence.observed
        patrol_expected_trigger_observed = [bool]$observedPatrolEvidence.observed
        mainline_expected_snapshot_seen = $mainlineExpectedSnapshotSeen
        patrol_expected_snapshot_seen = $patrolExpectedSnapshotSeen
        all_expected_snapshots_seen = ($mainlineExpectedSnapshotSeen -and $patrolExpectedSnapshotSeen)
    }
    audit_lines_artifact = "13-audit-lines.txt"
    poll_snapshots_artifact = "14-poll-snapshots.json"
}

Save-JsonArtifact -Name "00-summary.json" -Object $summary | Out-Null
Write-Output ("CollectedArtifactsDir={0}" -f $artifactsDir)
