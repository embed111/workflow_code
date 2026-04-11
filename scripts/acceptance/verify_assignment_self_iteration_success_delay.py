#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import assignment_service, schedule_service

    root = workspace_root / ".test" / "runtime-self-iteration-success-delay"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    ws.ensure_tables(root)

    conn = assignment_service.connect_db(root)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_registry(agent_id,agent_name,workspace_path,runtime_status,updated_at)
            VALUES (?,?,?,?,?)
            """,
            ("workflow", "workflow", str(workspace_root), "idle", "2099-01-01T00:00:00+08:00"),
        )
        conn.commit()
    finally:
        conn.close()

    fixed_now = datetime.fromisoformat("2026-04-08T02:13:48+08:00")
    task_record = {"ticket_id": "asg-success-delay", "is_test_data": False}
    node_record = {"node_id": "node-success-delay", "assigned_agent_id": "workflow", "record_state": "active"}

    with patch.object(assignment_service, "now_local", return_value=fixed_now), patch.object(
        schedule_service,
        "_now_bj",
        return_value=fixed_now,
    ):
        result = assignment_service._assignment_queue_self_iteration_schedule(
            root,
            task_record=task_record,
            node_record=node_record,
            result_summary="success delay probe",
            success=True,
        )
        schedules = schedule_service.list_schedules(root)
        items = list(schedules.get("items") or [])
        self_item = next(item for item in items if str(item.get("schedule_name") or "").strip() == "[持续迭代] workflow")
        wake_item = next(item for item in items if "主线巡检" in str(item.get("schedule_name") or "").strip())

        assert str(result.get("next_trigger_at") or "").strip() == "2026-04-08T02:28:00+08:00", result
        assert str(result.get("backup_next_trigger_at") or "").strip() == "2026-04-08T03:28:00+08:00", result
        assert str(self_item.get("next_trigger_at") or "").strip() == str(result.get("next_trigger_at") or "").strip(), {
            "result": result,
            "schedule": self_item,
        }
        assert str(wake_item.get("next_trigger_at") or "").strip() == str(result.get("backup_next_trigger_at") or "").strip(), {
            "result": result,
            "backup_schedule": wake_item,
        }

    print(
        json.dumps(
            {
                "ok": True,
                "self_iteration_schedule_id": str(result.get("schedule_id") or "").strip(),
                "self_iteration_next_trigger_at": str(result.get("next_trigger_at") or "").strip(),
                "pm_wake_schedule_id": str(result.get("backup_schedule_id") or "").strip(),
                "pm_wake_next_trigger_at": str(result.get("backup_next_trigger_at") or "").strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
