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
    from workflow_app.server.services.pm_version_board_service import load_pm_version_board

    board = load_pm_version_board(workspace_root)
    assert board.get("ok"), board
    active_version = str(board.get("active_version") or "").strip()
    assert active_version, board
    requirements = list(board.get("requirements") or [])
    owners = list(board.get("owners") or [])
    summary = dict(board.get("summary") or {})
    activation_summary = dict(board.get("activation_summary") or {})

    assert requirements, board
    assert owners, board
    assert int(summary.get("total") or 0) == len(requirements), summary
    assert int(summary.get("owner_count") or 0) == len(owners), summary
    assert all(str(item.get("requirement_id") or "").startswith(f"{active_version}-R") for item in requirements), requirements
    assert str(activation_summary.get("next_activation_candidate") or "").strip() == "V3", activation_summary
    assert bool(activation_summary.get("next_activation_ready")), activation_summary
    assert not list(activation_summary.get("hard_failures") or []), activation_summary

    cfg = SimpleNamespace(root=workspace_root, agent_search_root=workspace_root.as_posix())
    state = SimpleNamespace()
    handler = _CaptureHandler()

    mocked_workboard = {
        "assignment_workboard_agents": [],
        "assignment_workboard_summary": {},
        "schedule_workboard_preview": [],
        "schedule_plan_count": 0,
        "schedule_total": 0,
        "active_agent_count": 0,
        "queued_task_count": 0,
        "failed_task_count": 0,
        "blocked_task_count": 0,
        "workflow_mainline_handoff_pending": False,
        "workflow_mainline_handoff_note": "",
        "workflow_mainline_starvation_signal": False,
        "workflow_mainline_starvation_state": "",
        "workflow_mainline_starvation_note": "",
    }
    mocked_runtime = {
        "running_task_count": 0,
        "running_agent_count": 0,
        "active_execution_count": 0,
        "agent_call_count": 0,
    }
    mocked_truth = {
        "active_version": active_version,
        "active_slot": "pm-plan",
        "active_version_source": "pm_version_plan",
        "runtime_active_version": "disabled",
        "runtime_active_slot": "disabled",
        "truth_mismatch_count": 0,
        "truth_mismatch_items": [],
        "pm_version_status": {
            "active_version": active_version,
            "active_version_title": str(board.get("active_version_title") or "").strip(),
            "active_version_file": str(board.get("source_relative_path") or "").strip(),
            "lane": str(board.get("lane") or "").strip(),
            "lifecycle_stage": str(board.get("lifecycle_stage") or "").strip(),
            "baseline": str(board.get("baseline") or "").strip(),
        },
    }

    with (
        patch.object(dashboard_api, "_workboard_payload", return_value=mocked_workboard),
        patch.object(dashboard_api, "_assignment_runtime_with_workboard_fallback", return_value=mocked_runtime),
        patch.object(dashboard_api, "_runtime_goal_payload", return_value={}),
        patch.object(dashboard_api, "load_pm_version_board", return_value=board),
        patch.object(dashboard_api, "load_effective_pm_version_status", return_value={}),
        patch.object(dashboard_api, "build_pm_version_truth_payload", return_value=mocked_truth),
        patch.object(dashboard_api.ws, "active_runtime_task_count", return_value=0),
        patch.object(dashboard_api.ws, "current_show_test_data", return_value=False),
        patch.object(dashboard_api.ws, "get_assignment_runtime_metrics", return_value=mocked_runtime),
        patch.object(dashboard_api.ws, "pending_counts", return_value=(0, 0)),
        patch.object(dashboard_api.ws, "show_test_data_policy_fields", return_value={"show_test_data": False, "show_test_data_source": "environment_policy", "environment": "prod"}),
        patch.object(dashboard_api.ws, "list_available_agents", return_value=[{"agent_id": "workflow"}]),
        patch.object(dashboard_api.ws, "AB_FEATURE_ENABLED", False),
        patch.object(dashboard_api.ws, "dashboard", return_value={"ok": True}),
    ):
        handled = dashboard_api.try_handle_get(
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
        assert handled, "status route not handled"
        assert handler.status_code == 200, handler.payload
        assert dict(handler.payload.get("pm_version_board") or {}).get("active_version") == active_version, handler.payload
        assert len(list((handler.payload.get("pm_version_board") or {}).get("requirements") or [])) == len(requirements), handler.payload

        handler = _CaptureHandler()
        handled = dashboard_api.try_handle_get(
            handler,
            cfg,
            state,
            {
                "path": "/api/dashboard",
                "query": {},
                "root_ready": True,
                "root_error": "",
                "root_text": workspace_root.as_posix(),
            },
        )
        assert handled, "dashboard route not handled"
        assert handler.status_code == 200, handler.payload
        assert dict(handler.payload.get("pm_version_board") or {}).get("active_version") == active_version, handler.payload
        assert str(((handler.payload.get("pm_version_board") or {}).get("activation_summary") or {}).get("next_activation_candidate") or "").strip() == "V3", handler.payload

    print(
        json.dumps(
            {
                "ok": True,
                "active_version": active_version,
                "requirement_count": len(requirements),
                "owner_count": len(owners),
                "next_activation_candidate": activation_summary.get("next_activation_candidate"),
                "next_activation_ready": activation_summary.get("next_activation_ready"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
