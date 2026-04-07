#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str((workspace_root / "src").resolve()))

    from workflow_app.server.api import runtime_upgrade

    cfg = SimpleNamespace(root=Path("C:/runtime-root"))
    state = object()
    raw_metrics = {
        "running_task_count": 0,
        "running_agent_count": 0,
        "active_execution_count": 0,
        "agent_call_count": 0,
    }
    workboard = {
        "assignment_workboard_summary": {
            "running_task_count": 1,
            "queued_task_count": 0,
            "failed_task_count": 0,
            "blocked_task_count": 0,
        },
        "assignment_workboard_agents": [
            {
                "agent_id": "workflow",
                "agent_name": "workflow",
                "running": [{"node_id": "node-1"}],
            }
        ],
    }
    with patch.object(runtime_upgrade.ws, "active_runtime_task_count", return_value=0), patch.object(
        runtime_upgrade.ws, "current_show_test_data", return_value=False
    ), patch.object(runtime_upgrade.ws, "get_assignment_runtime_metrics", return_value=raw_metrics), patch(
        "workflow_app.server.api.dashboard._workboard_payload", return_value=workboard
    ):
        running_task_count, agent_call_count, gate_meta = runtime_upgrade._running_gate_payload(cfg, state)

    assert running_task_count == 1, (running_task_count, agent_call_count)
    assert agent_call_count == 1, (running_task_count, agent_call_count)
    assert not bool(gate_meta.get("running_gate_exclusion_requested")), gate_meta
    print(
        json.dumps(
            {
                "ok": True,
                "running_task_count": running_task_count,
                "agent_call_count": agent_call_count,
                "gate_meta": gate_meta,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
