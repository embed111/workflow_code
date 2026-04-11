#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class _CaptureHandler:
    def __init__(self) -> None:
        self.status_code = 0
        self.payload: dict[str, object] = {}

    def send_json(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = int(status_code)
        self.payload = dict(payload or {})


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.api import dashboard as dashboard_api
    from workflow_app.server.infra import audit_runtime
    from workflow_app.server.services.pm_version_status_service import (
        build_pm_version_truth_payload,
        format_pm_version_prompt_lines,
        load_pm_version_status,
    )

    plan_status = load_pm_version_status(workspace_root)
    assert plan_status.get("ok"), plan_status
    assert str(plan_status.get("active_version") or "").strip(), plan_status
    assert str(plan_status.get("lane") or "").strip(), plan_status
    assert str(plan_status.get("lifecycle_stage") or "").strip(), plan_status
    assert str(plan_status.get("baseline") or "").strip(), plan_status
    assert str(plan_status.get("source_path") or "").strip().endswith(
        "docs/workflow/governance/PM版本推进计划.md"
    ), plan_status

    prompt_lines = format_pm_version_prompt_lines(plan_status)
    prompt_text = "\n".join(prompt_lines)
    assert "当前版本快照：" in prompt_text, prompt_text
    assert f"active_version={plan_status['active_version']}" in prompt_text, prompt_text

    truth_payload = build_pm_version_truth_payload(
        reported_active_version="disabled",
        reported_active_slot="disabled",
        plan_status=plan_status,
    )
    assert truth_payload["active_version"] == plan_status["active_version"], truth_payload
    assert truth_payload["active_version_source"] == "pm_version_plan", truth_payload
    assert int(truth_payload["truth_mismatch_count"] or 0) == 1, truth_payload

    cfg = SimpleNamespace(root=workspace_root, agent_search_root=workspace_root.as_posix())
    handler = _CaptureHandler()
    state = SimpleNamespace()

    with (
        patch.object(dashboard_api, "_workboard_payload", return_value={"assignment_workboard_agents": [], "assignment_workboard_summary": {}, "schedule_workboard_preview": [], "schedule_plan_count": 0, "schedule_total": 0, "active_agent_count": 0, "queued_task_count": 0, "failed_task_count": 0, "blocked_task_count": 0, "workflow_mainline_handoff_pending": False, "workflow_mainline_handoff_note": ""}),
        patch.object(dashboard_api, "_assignment_runtime_with_workboard_fallback", return_value={"running_task_count": 0, "running_agent_count": 0, "active_execution_count": 0, "agent_call_count": 0}),
        patch.object(dashboard_api, "_runtime_goal_payload", return_value={}),
        patch.object(dashboard_api.ws, "active_runtime_task_count", return_value=0),
        patch.object(dashboard_api.ws, "current_show_test_data", return_value=False),
        patch.object(dashboard_api.ws, "get_assignment_runtime_metrics", return_value={"running_task_count": 0, "running_agent_count": 0, "active_execution_count": 0, "agent_call_count": 0}),
        patch.object(dashboard_api.ws, "pending_counts", return_value=(0, 0)),
        patch.object(dashboard_api.ws, "show_test_data_policy_fields", return_value={"show_test_data": False, "show_test_data_source": "environment_policy", "environment": "prod"}),
        patch.object(dashboard_api.ws, "list_available_agents", return_value=[{"agent_id": "workflow"}]),
        patch.object(dashboard_api.ws, "AB_FEATURE_ENABLED", False),
    ):
        ok = dashboard_api.try_handle_get(
            handler,
            cfg,
            state,
            {
                "path": "/api/status",
                "root_ready": True,
                "root_error": "",
                "root_text": workspace_root.as_posix(),
            },
        )
    assert ok, "dashboard status route not handled"
    assert handler.status_code == 200, handler.payload
    assert handler.payload.get("active_version") == plan_status["active_version"], handler.payload
    assert handler.payload.get("active_version_source") == "pm_version_plan", handler.payload
    assert int(handler.payload.get("truth_mismatch_count") or 0) == 1, handler.payload
    assert dict(handler.payload.get("pm_version_status") or {}).get("active_version") == plan_status["active_version"], handler.payload

    with (
        patch.object(audit_runtime, "pending_counts", return_value=(1, 0)),
        patch.object(audit_runtime, "latest_results", return_value=("decision", "training")),
        patch.object(audit_runtime, "agent_search_root_state", return_value=(True, "")),
        patch.object(audit_runtime, "list_available_agents", return_value=[{"agent_id": "workflow"}]),
        patch.object(audit_runtime, "policy_closure_stats", return_value={}),
        patch.object(audit_runtime, "new_sessions_24h", return_value=0),
        patch.object(audit_runtime, "AB_FEATURE_ENABLED", False),
    ):
        dashboard_payload = audit_runtime.dashboard(cfg, include_test_data=False)
    assert dashboard_payload["active_version"] == plan_status["active_version"], dashboard_payload
    assert dashboard_payload["active_version_source"] == "pm_version_plan", dashboard_payload
    assert int(dashboard_payload["truth_mismatch_count"] or 0) == 1, dashboard_payload
    assert dict(dashboard_payload.get("pm_version_status") or {}).get("baseline") == plan_status["baseline"], dashboard_payload

    print(
        json.dumps(
            {
                "ok": True,
                "active_version": plan_status["active_version"],
                "lane": plan_status["lane"],
                "lifecycle_stage": plan_status["lifecycle_stage"],
                "baseline": plan_status["baseline"],
                "prompt_lines": prompt_lines,
                "status_truth": {
                    "active_version": handler.payload.get("active_version"),
                    "active_version_source": handler.payload.get("active_version_source"),
                    "truth_mismatch_count": handler.payload.get("truth_mismatch_count"),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
