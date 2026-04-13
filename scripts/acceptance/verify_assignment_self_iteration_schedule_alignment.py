#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

WATCHDOG_TIMES_TEXT = ",".join(f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in range(0, 60, 20))


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import assignment_service, schedule_assignment_bridge, schedule_service

    root = workspace_root / ".test" / "runtime-self-iteration-schedule-alignment"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    ws.ensure_tables(root)
    cfg = type(
        "Cfg",
        (),
        {
            "root": root,
            "agent_search_root": Path("D:/code/AI/J-Agents").resolve(),
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()

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
    task_record = {"ticket_id": "asg-alignment", "is_test_data": False}
    node_record = {"node_id": "node-alignment", "assigned_agent_id": "workflow", "record_state": "active"}

    with patch.object(assignment_service, "now_local", return_value=fixed_now), patch.object(
        schedule_service,
        "_now_bj",
        return_value=fixed_now,
    ):
        stale_mainline = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "[持续迭代] workflow",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "stale mainline",
                "execution_checklist": "keep going",
                "done_definition": "done",
                "priority": "P1",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": "2026-04-08T02:33:00+08:00"},
                },
            },
        )
        stale_wake = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "pm持续唤醒 - workflow 主线巡检",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "stale watchdog",
                "execution_checklist": "observe",
                "done_definition": "done",
                "priority": "P2",
                "expected_artifact": "workflow-pm-wake-summary",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": "2026-04-08T02:40:00+08:00"},
                },
            },
        )
        stale_mainline_id = str(stale_mainline.get("schedule_id") or "").strip()
        stale_wake_id = str(stale_wake.get("schedule_id") or "").strip()
        conn = schedule_service.connect_db(root)
        try:
            conn.execute(
                "UPDATE schedule_plans SET priority=?, updated_by=?, updated_at=? WHERE schedule_id=?",
                (2, "test-stale-mainline", fixed_now.isoformat(timespec="seconds"), stale_mainline_id),
            )
            conn.execute(
                "UPDATE schedule_plans SET priority=?, updated_by=?, updated_at=? WHERE schedule_id=?",
                (1, "test-stale-patrol", fixed_now.isoformat(timespec="seconds"), stale_wake_id),
            )
            conn.commit()
        finally:
            conn.close()

        result = assignment_service._assignment_queue_self_iteration_schedule(
            root,
            task_record=task_record,
            node_record=node_record,
            result_summary="alignment probe",
            success=False,
        )
        schedules = schedule_service.list_schedules(root)
        items = list(schedules.get("items") or [])
        self_item = next(item for item in items if str(item.get("schedule_name") or "").strip() == "[持续迭代] workflow")
        wake_item = next(item for item in items if "主线巡检" in str(item.get("schedule_name") or "").strip())

        assert str(result.get("schedule_id") or "").strip() == stale_mainline_id, result
        assert str(result.get("backup_schedule_id") or "").strip() == stale_wake_id, result
        assert str(result.get("next_trigger_at") or "").strip() == "2026-04-08T02:23:00+08:00", result
        assert str(result.get("backup_next_trigger_at") or "").strip() == "2026-04-08T02:20:00+08:00", result
        assert str(self_item.get("next_trigger_at") or "").strip() == str(result.get("next_trigger_at") or "").strip(), {
            "result": result,
            "schedule": self_item,
        }
        assert str(self_item.get("priority") or "").strip() == "P1", self_item
        assert str(wake_item.get("next_trigger_at") or "").strip() == str(result.get("backup_next_trigger_at") or "").strip(), {
            "result": result,
            "backup_schedule": wake_item,
        }
        assert str(wake_item.get("priority") or "").strip() == "P2", wake_item
        wake_editor_inputs = wake_item.get("editor_rule_inputs") if isinstance(wake_item.get("editor_rule_inputs"), dict) else {}
        wake_daily = wake_editor_inputs.get("daily") if isinstance(wake_editor_inputs.get("daily"), dict) else {}
        wake_once = wake_editor_inputs.get("once") if isinstance(wake_editor_inputs.get("once"), dict) else {}
        assert bool(wake_daily.get("enabled")), wake_item
        assert str(wake_daily.get("times_text") or "").strip() == WATCHDOG_TIMES_TEXT, wake_item
        assert not bool(wake_once.get("enabled")), wake_item

        conn = schedule_service.connect_db(root)
        try:
            conn.execute(
                "UPDATE schedule_plans SET priority=?, updated_by=?, updated_at=? WHERE schedule_id=?",
                (2, "test-stale-mainline-bridge", fixed_now.isoformat(timespec="seconds"), stale_mainline_id),
            )
            conn.execute(
                "UPDATE schedule_plans SET priority=?, updated_by=?, updated_at=? WHERE schedule_id=?",
                (1, "test-stale-patrol-bridge", fixed_now.isoformat(timespec="seconds"), stale_wake_id),
            )
            conn.commit()
        finally:
            conn.close()

        repaired_mainline = schedule_service.get_schedule_detail(root, stale_mainline_id).get("schedule") or {}
        repaired_wake = schedule_service.get_schedule_detail(root, stale_wake_id).get("schedule") or {}
        stale_mainline_trigger_id = f"sti-mainline-stale-priority-{stale_mainline_id}"
        stale_wake_trigger_id = f"sti-patrol-stale-priority-{stale_wake_id}"
        mainline_node_ref = schedule_assignment_bridge.create_schedule_node(
            cfg,
            repaired_mainline,
            trigger_instance_id=stale_mainline_trigger_id,
            planned_trigger_at="2026-04-08T02:54:00+08:00",
            trigger_rule_summary="stale mainline bridge",
        )
        wake_node_ref = schedule_assignment_bridge.create_schedule_node(
            cfg,
            repaired_wake,
            trigger_instance_id=stale_wake_trigger_id,
            planned_trigger_at="2026-04-08T02:40:00+08:00",
            trigger_rule_summary="stale patrol bridge",
        )
        mainline_node = ws._assignment_read_json(
            ws._assignment_node_record_path(root, str(mainline_node_ref.get("ticket_id") or "").strip(), str(mainline_node_ref.get("node_id") or "").strip())
        )
        wake_node = ws._assignment_read_json(
            ws._assignment_node_record_path(root, str(wake_node_ref.get("ticket_id") or "").strip(), str(wake_node_ref.get("node_id") or "").strip())
        )
        assert int(mainline_node.get("priority") or 0) == 1, mainline_node
        assert int(wake_node.get("priority") or 0) == 2, wake_node

    print(
        json.dumps(
            {
                "ok": True,
                "self_iteration_schedule_id": str(result.get("schedule_id") or "").strip(),
                "self_iteration_next_trigger_at": str(result.get("next_trigger_at") or "").strip(),
                "self_iteration_priority": str(self_item.get("priority") or "").strip(),
                "pm_wake_schedule_id": str(result.get("backup_schedule_id") or "").strip(),
                "pm_wake_next_trigger_at": str(result.get("backup_next_trigger_at") or "").strip(),
                "pm_wake_priority": str(wake_item.get("priority") or "").strip(),
                "stale_mainline_node_priority": int(mainline_node.get("priority") or 0),
                "stale_patrol_node_priority": int(wake_node.get("priority") or 0),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
