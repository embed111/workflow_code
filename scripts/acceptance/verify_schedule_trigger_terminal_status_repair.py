#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import schedule_service

    root = Path.cwd() / ".test" / "runtime-schedule-trigger-terminal-status-repair"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(Path("C:/work/J-Agents").resolve()),
                "artifact_root": artifact_root.as_posix(),
                "task_artifact_root": artifact_root.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = type("Cfg", (), {"root": root, "runtime_environment": "prod"})()

    original_load_agents = schedule_service._load_available_agents
    schedule_service._load_available_agents = lambda _cfg: [{"agent_id": "workflow", "agent_name": "workflow"}]
    try:
        schedule = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "[持续迭代] workflow",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "repair terminal trigger truth",
                "execution_checklist": "1) stale running trigger\n2) read detail\n3) project terminal truth without mutating storage",
                "done_definition": "detail should show terminal truth while GET stays read-only",
                "priority": "P1",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": "2026-04-08T04:14:00+08:00"},
                },
            },
        )
    finally:
        schedule_service._load_available_agents = original_load_agents

    schedule_id = str(schedule.get("schedule_id") or "").strip()
    trigger_instance_id = "sti-terminal-truth-repair"
    planned_trigger_at = "2026-04-08T04:14:00+08:00"
    created_at = "2026-04-08T04:14:01+08:00"
    conn = schedule_service.connect_db(root)
    try:
        conn.execute(
            """
            INSERT INTO schedule_trigger_instances(
                trigger_instance_id,schedule_id,planned_trigger_at,trigger_rule_summary,trigger_rule_keys_json,merged_rule_count,
                trigger_status,trigger_message,assignment_ticket_id,assignment_node_id,schedule_name_snapshot,assigned_agent_id_snapshot,
                launch_summary_snapshot,execution_checklist_snapshot,done_definition_snapshot,expected_artifact_snapshot,
                delivery_mode_snapshot,delivery_receiver_agent_id_snapshot,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trigger_instance_id,
                schedule_id,
                planned_trigger_at,
                "定时 2026-04-08 04:14",
                "[]",
                1,
                "running",
                "dispatch_requested",
                "asg-terminal-truth",
                "node-terminal-truth",
                "[持续迭代] workflow",
                "workflow",
                "repair terminal trigger truth",
                "1) stale running trigger\n2) read detail\n3) project terminal truth without mutating storage",
                "detail should show terminal truth while GET stays read-only",
                "continuous-improvement-report.md",
                "none",
                "",
                created_at,
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    original_assignment_runtime_status = schedule_service._assignment_runtime_status

    def fake_assignment_runtime_status(root_path, *, ticket_id: str, node_id: str, persist_repair: bool = False):
        if str(ticket_id or "").strip() == "asg-terminal-truth" and str(node_id or "").strip() == "node-terminal-truth":
            return {
                "assignment_status": "failed",
                "assignment_status_text": "执行失败",
                "assignment_graph_name": "任务中心全局主图",
                "assignment_node_name": "[持续迭代] workflow",
                "result_status": "failed",
                "result_status_text": schedule_service.SCHEDULE_RESULT_TEXT["failed"],
            }
        return {}

    schedule_service._assignment_runtime_status = fake_assignment_runtime_status
    try:
        detail = schedule_service.get_schedule_detail(root, schedule_id)
    finally:
        schedule_service._assignment_runtime_status = original_assignment_runtime_status

    recent = list(detail.get("recent_triggers") or [])
    assert recent, detail
    latest = dict(recent[0] or {})
    assert latest.get("trigger_instance_id") == trigger_instance_id, latest
    assert latest.get("trigger_status") == "failed", latest
    assert latest.get("trigger_message") == "执行失败", latest
    assert str(detail.get("schedule", {}).get("last_result_status") or "") == "failed", detail

    conn = schedule_service.connect_db(root)
    try:
        stored = conn.execute(
            """
            SELECT trigger_status,trigger_message,updated_at
            FROM schedule_trigger_instances
            WHERE trigger_instance_id=?
            LIMIT 1
            """,
            (trigger_instance_id,),
        ).fetchone()
    finally:
        conn.close()

    assert stored is not None, trigger_instance_id
    assert str(stored["trigger_status"] or "").strip().lower() == "running", dict(stored)
    assert str(stored["trigger_message"] or "").strip() == "dispatch_requested", dict(stored)

    print(
        json.dumps(
            {
                "ok": True,
                "schedule_id": schedule_id,
                "trigger_instance_id": trigger_instance_id,
                "recent_trigger": latest,
                "stored_row": dict(stored),
                "storage_mutated_by_get": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
