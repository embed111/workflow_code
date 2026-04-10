#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import assignment_service

    observed: dict[str, object] = {}

    def fake_run_row_is_live(run: dict[str, object], *, active_run_ids, now_dt, grace_seconds: int) -> bool:
        observed["active_run_ids"] = sorted(str(item or "") for item in list(active_run_ids or []))
        observed["grace_seconds"] = int(grace_seconds or 0)
        observed["checked_run_status"] = str(run.get("status") or "")
        observed["checked_node_id"] = str(run.get("node_id") or "")
        return True

    with patch.object(assignment_service, "_active_assignment_run_ids", return_value=[], create=True), patch.object(
        assignment_service,
        "_assignment_ensure_workflow_ui_global_graph_ticket",
        return_value="asg-workflow-ui",
    ), patch.object(
        assignment_service,
        "_assignment_list_ticket_ids_lightweight",
        return_value=["asg-live"],
    ), patch.object(
        assignment_service,
        "_assignment_load_task_record_lightweight",
        return_value={"ticket_id": "asg-live", "record_state": "active", "is_test_data": False},
    ), patch.object(
        assignment_service,
        "_assignment_task_visible",
        return_value=True,
    ), patch.object(
        assignment_service,
        "_assignment_is_hidden_workflow_ui_graph_ticket",
        return_value=False,
    ), patch.object(
        assignment_service,
        "_assignment_load_run_records",
        return_value=[{"run_id": "run-live", "node_id": "node-live", "status": "running"}],
    ) as load_runs_mock, patch.object(
        assignment_service,
        "_assignment_run_row_is_live",
        side_effect=fake_run_row_is_live,
    ) as run_is_live_mock, patch.object(
        assignment_service,
        "_assignment_node_record_path",
        return_value=Path("C:/runtime-root/tasks/asg-live/nodes/node-live.json"),
    ), patch.object(
        assignment_service,
        "_assignment_read_json",
        return_value={"assigned_agent_id": "workflow"},
    ) as read_json_mock:
        payload = assignment_service._assignment_system_running_state(
            Path("C:/runtime-root"),
            include_test_data=False,
        )

    assert payload["running_agents"] == {"workflow"}, payload
    assert int(payload["running_node_count"] or 0) == 1, payload
    assert observed["active_run_ids"] == [], observed
    assert observed["checked_run_status"] == "running", observed
    assert observed["checked_node_id"] == "node-live", observed
    assert load_runs_mock.called, "live run records should still be scanned when active_run_ids is empty"
    assert run_is_live_mock.called, "live run probe should execute when active_run_ids is empty"
    assert read_json_mock.called, "node agent lookup should still happen for file-backed live runs"

    print(
        json.dumps(
            {
                "ok": True,
                "payload": {
                    "running_agents": sorted(payload["running_agents"]),
                    "running_node_count": payload["running_node_count"],
                },
                "observed": observed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
