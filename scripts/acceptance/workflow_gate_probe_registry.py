#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScriptProbeDefinition:
    key: str
    relative_path: str
    failure_message: str
    runner: str = "python"

    def command_prefix(self) -> list[str]:
        if self.runner == "python":
            return [sys.executable]
        if self.runner == "node":
            return ["node"]
        raise ValueError(f"unsupported probe runner: {self.runner}")


SCRIPT_PROBE_DEFINITIONS: tuple[ScriptProbeDefinition, ...] = (
    ScriptProbeDefinition(
        key="runtime_upgrade_running_gate_fallback",
        relative_path="scripts/acceptance/verify_runtime_upgrade_running_gate_fallback.py",
        failure_message="runtime upgrade running gate fallback failed",
    ),
    ScriptProbeDefinition(
        key="runtime_upgrade_self_exclusion",
        relative_path="scripts/acceptance/verify_runtime_upgrade_self_exclusion.py",
        failure_message="runtime upgrade self exclusion probe failed",
    ),
    ScriptProbeDefinition(
        key="runtime_upgrade_dispatch_drain",
        relative_path="scripts/acceptance/verify_runtime_upgrade_dispatch_drain.py",
        failure_message="runtime upgrade dispatch drain probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_self_upgrade_loopback",
        relative_path="scripts/acceptance/verify_assignment_self_upgrade_loopback.py",
        failure_message="assignment self upgrade loopback probe failed",
    ),
    ScriptProbeDefinition(
        key="apply_prod_candidate_when_idle",
        relative_path="scripts/acceptance/verify_apply_prod_candidate_when_idle.py",
        failure_message="apply prod candidate when idle probe failed",
    ),
    ScriptProbeDefinition(
        key="stop_workflow_env",
        relative_path="scripts/acceptance/verify_stop_workflow_env.py",
        failure_message="stop workflow env probe failed",
    ),
    ScriptProbeDefinition(
        key="prod_auto_upgrade_single_check_helper",
        relative_path="scripts/acceptance/verify_prod_auto_upgrade_single_check_helper.py",
        failure_message="prod auto upgrade single-check helper probe failed",
    ),
    ScriptProbeDefinition(
        key="runtime_upgrade_drain_hit_single_check",
        relative_path="scripts/acceptance/verify_runtime_upgrade_drain_hit_single_check.py",
        failure_message="runtime upgrade drain hit single-check probe failed",
    ),
    ScriptProbeDefinition(
        key="release_boundary_local_root_sync_policy",
        relative_path="scripts/acceptance/verify_release_boundary_local_root_sync_policy.py",
        failure_message="release boundary local root sync policy probe failed",
    ),
    ScriptProbeDefinition(
        key="runtime_process_instance_fallback",
        relative_path="scripts/acceptance/verify_runtime_process_instance_fallback.py",
        failure_message="runtime process instance fallback probe failed",
    ),
    ScriptProbeDefinition(
        key="schedule_trigger_recovery_waits_for_running_slot",
        relative_path="scripts/acceptance/verify_schedule_trigger_recovery_worker.py",
        failure_message="schedule trigger recovery probe failed",
    ),
    ScriptProbeDefinition(
        key="schedule_assignment_runtime_reconciliation",
        relative_path="scripts/acceptance/verify_schedule_assignment_runtime_reconciliation.py",
        failure_message="schedule assignment runtime reconciliation probe failed",
    ),
    ScriptProbeDefinition(
        key="schedule_trigger_terminal_status_repair",
        relative_path="scripts/acceptance/verify_schedule_trigger_terminal_status_repair.py",
        failure_message="schedule trigger terminal status repair probe failed",
    ),
    ScriptProbeDefinition(
        key="schedule_exhausted_once_plan_repair",
        relative_path="scripts/acceptance/verify_schedule_exhausted_once_plan_repair.py",
        failure_message="schedule exhausted once plan repair probe failed",
    ),
    ScriptProbeDefinition(
        key="schedule_pending_trigger_replaced_by_newer",
        relative_path="scripts/acceptance/verify_schedule_pending_trigger_replaced_by_newer.py",
        failure_message="schedule pending trigger replacement probe failed",
    ),
    ScriptProbeDefinition(
        key="schedule_upgrade_drain_recovery",
        relative_path="scripts/acceptance/verify_schedule_upgrade_drain_recovery.py",
        failure_message="schedule upgrade drain recovery probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_transient_retry",
        relative_path="scripts/acceptance/verify_assignment_transient_startup_retry.py",
        failure_message="assignment transient retry probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_workspace_memory_bootstrap",
        relative_path="scripts/acceptance/verify_assignment_workspace_memory_bootstrap.py",
        failure_message="assignment workspace memory bootstrap probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_workspace_memory_writeback",
        relative_path="scripts/acceptance/verify_assignment_workspace_memory_writeback.py",
        failure_message="assignment workspace memory writeback probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_stale_role_creation_lock_repair",
        relative_path="scripts/acceptance/verify_assignment_stale_role_creation_lock_repair.py",
        failure_message="assignment stale role creation lock repair probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_normalized_ticket_fast_path",
        relative_path="scripts/acceptance/verify_assignment_normalized_ticket_fast_path.py",
        failure_message="assignment normalized ticket fast path probe failed",
    ),
    ScriptProbeDefinition(
        key="schedule_runtime_status_file_fast_path",
        relative_path="scripts/acceptance/verify_schedule_runtime_status_file_fast_path.py",
        failure_message="schedule runtime status file fast path probe failed",
    ),
    ScriptProbeDefinition(
        key="schedule_runtime_status_persist_repair",
        relative_path="scripts/acceptance/verify_schedule_runtime_status_persist_repair.py",
        failure_message="schedule runtime status persist repair probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_run_record_db_sync",
        relative_path="scripts/acceptance/verify_assignment_run_record_db_sync.py",
        failure_message="assignment run record db sync probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_stale_recovery_cleanup_and_memory",
        relative_path="scripts/acceptance/verify_assignment_stale_recovery_cleanup_and_memory.py",
        failure_message="assignment stale recovery cleanup and memory probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_stale_runtime_upgrade_recovery",
        relative_path="scripts/acceptance/verify_assignment_stale_runtime_upgrade_recovery.py",
        failure_message="assignment stale runtime upgrade recovery probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_execution_activity_timeout",
        relative_path="scripts/acceptance/verify_assignment_execution_activity_timeout.py",
        failure_message="assignment execution activity timeout probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_stale_run_recovery",
        relative_path="scripts/acceptance/verify_assignment_stale_run_recovery.py",
        failure_message="assignment stale run recovery probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_stale_failure_context_preserved",
        relative_path="scripts/acceptance/verify_assignment_stale_failure_context_preserved.py",
        failure_message="assignment stale failure context preserved probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_stale_structured_result_preserved",
        relative_path="scripts/acceptance/verify_assignment_stale_structured_result_preserved.py",
        failure_message="assignment stale structured result preserved probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_mainline_visibility",
        relative_path="scripts/acceptance/verify_assignment_mainline_visibility.py",
        failure_message="assignment mainline visibility probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_center_mainline_visibility",
        relative_path="scripts/acceptance/verify_assignment_center_mainline_visibility.js",
        failure_message="assignment center mainline visibility probe failed",
        runner="node",
    ),
    ScriptProbeDefinition(
        key="assignment_workboard_signal_cards",
        relative_path="scripts/acceptance/verify_assignment_workboard_signal_cards.js",
        failure_message="assignment workboard signal cards probe failed",
        runner="node",
    ),
    ScriptProbeDefinition(
        key="assignment_finalize_idempotency",
        relative_path="scripts/acceptance/verify_assignment_finalize_idempotency.py",
        failure_message="assignment finalize idempotency probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_stale_terminal_projection_guard",
        relative_path="scripts/acceptance/verify_assignment_stale_terminal_projection_guard.py",
        failure_message="assignment stale terminal projection guard probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_status_detail_default_node",
        relative_path="scripts/acceptance/verify_assignment_status_detail_default_node.py",
        failure_message="assignment status detail default node probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_provider_liveness_guard",
        relative_path="scripts/acceptance/verify_assignment_provider_liveness_guard.py",
        failure_message="assignment provider liveness guard probe failed",
    ),
    ScriptProbeDefinition(
        key="dashboard_active_agent_count",
        relative_path="scripts/acceptance/verify_dashboard_active_agent_count.py",
        failure_message="dashboard active agent count probe failed",
    ),
    ScriptProbeDefinition(
        key="pm_version_truth_source",
        relative_path="scripts/acceptance/verify_pm_version_truth_source.py",
        failure_message="pm version truth source probe failed",
    ),
    ScriptProbeDefinition(
        key="dashboard_pending_upstream_blockers",
        relative_path="scripts/acceptance/verify_dashboard_pending_upstream_blockers.py",
        failure_message="dashboard pending upstream blockers probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_runtime_metrics_node_fallback",
        relative_path="scripts/acceptance/verify_assignment_runtime_metrics_node_fallback.py",
        failure_message="assignment runtime metrics node fallback probe failed",
    ),
    ScriptProbeDefinition(
        key="role_workspace_memory_governance",
        relative_path="scripts/acceptance/verify_role_workspace_memory_governance.py",
        failure_message="role workspace memory governance probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_self_iteration_plan_reference",
        relative_path="scripts/acceptance/verify_assignment_self_iteration_plan_reference.py",
        failure_message="assignment self iteration plan reference probe failed",
    ),
    ScriptProbeDefinition(
        key="assignment_self_iteration_schedule_alignment",
        relative_path="scripts/acceptance/verify_assignment_self_iteration_schedule_alignment.py",
        failure_message="assignment self iteration schedule alignment probe failed",
    ),
    ScriptProbeDefinition(
        key="self_iteration_backup_schedule_on_smoke_block",
        relative_path="scripts/acceptance/verify_self_iteration_backup_schedule_on_smoke_block.py",
        failure_message="self iteration backup schedule on smoke block probe failed",
    ),
    ScriptProbeDefinition(
        key="prod_watchdog_pending_upgrade_fallback",
        relative_path="scripts/acceptance/verify_prod_watchdog_pending_upgrade_fallback.py",
        failure_message="prod watchdog pending upgrade fallback probe failed",
    ),
)


def run_script_probe(repo_root: Path, definition: ScriptProbeDefinition) -> tuple[bool, dict[str, object]]:
    probe = (repo_root / definition.relative_path).resolve()
    proc = subprocess.run(
        [*definition.command_prefix(), str(probe)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    detail: dict[str, object] = {
        "script": probe.as_posix(),
        "returncode": int(proc.returncode),
    }
    stdout = str(proc.stdout or "").strip()
    stderr = str(proc.stderr or "").strip()
    if stdout:
        try:
            detail["payload"] = json.loads(stdout)
        except Exception:
            detail["stdout"] = stdout
    if stderr:
        detail["stderr"] = stderr
    payload = detail.get("payload") if isinstance(detail.get("payload"), dict) else {}
    ok = proc.returncode == 0 and bool((payload or {}).get("ok", proc.returncode == 0))
    return ok, detail
