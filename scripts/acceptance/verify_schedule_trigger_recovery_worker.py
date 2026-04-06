#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import schedule_service

    root = Path.cwd() / ".test" / "runtime-schedule-trigger-recovery"
    if root.exists():
        import shutil

        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(Path("D:/code/AI/J-Agents").resolve()),
                "artifact_root": str((root / "artifacts-root").resolve()),
                "task_artifact_root": str((root / "artifacts-root").resolve()),
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

    def create_schedule(date_text: str) -> str:
        schedule = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "[持续迭代] workflow",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "self iteration",
                "execution_checklist": "keep going",
                "done_definition": "done",
                "priority": "P2",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": date_text},
                },
            },
        )
        return str(schedule.get("schedule_id") or "").strip()

    try:
        schedule_missing_id = create_schedule("2026-04-06T20:00:00+08:00")
        schedule_active_id = create_schedule("2026-04-06T20:05:00+08:00")
        schedule_done_id = create_schedule("2026-04-06T20:10:00+08:00")
        schedule_running_id = create_schedule("2026-04-06T20:15:00+08:00")
        schedule_recent_failed_id = create_schedule("2026-04-06T20:20:00+08:00")
    finally:
        schedule_service._load_available_agents = original_load_agents

    now_minute = schedule_service._minute_floor(schedule_service._now_bj())
    trigger_missing_at = (now_minute - timedelta(minutes=5)).isoformat(timespec="seconds")
    trigger_active_at = (now_minute - timedelta(minutes=4)).isoformat(timespec="seconds")
    trigger_running_at = (now_minute - timedelta(minutes=3)).isoformat(timespec="seconds")
    trigger_done_at = (now_minute - timedelta(minutes=2)).isoformat(timespec="seconds")
    trigger_recent_failed_at = (now_minute - timedelta(minutes=1)).isoformat(timespec="seconds")

    conn = schedule_service.connect_db(root)
    try:
        rows = [
            (
                "sti-recover-missing",
                schedule_missing_id,
                trigger_missing_at,
                f"定时 {trigger_missing_at[:16].replace('T', ' ')}",
                "dispatch_failed",
                "smoke baseline expired",
                "",
                "",
                trigger_missing_at,
                (now_minute - timedelta(minutes=4, seconds=30)).isoformat(timespec="seconds"),
            ),
            (
                "sti-recover-active",
                schedule_active_id,
                trigger_active_at,
                f"定时 {trigger_active_at[:16].replace('T', ' ')}",
                "queued",
                "dispatch_requested",
                "asg-active",
                "node-active",
                trigger_active_at,
                (now_minute - timedelta(minutes=3, seconds=30)).isoformat(timespec="seconds"),
            ),
            (
                "sti-recover-done",
                schedule_done_id,
                trigger_done_at,
                f"定时 {trigger_done_at[:16].replace('T', ' ')}",
                "queued",
                "dispatch_requested",
                "asg-done",
                "node-done",
                trigger_done_at,
                (now_minute - timedelta(minutes=1, seconds=30)).isoformat(timespec="seconds"),
            ),
            (
                "sti-recover-running",
                schedule_running_id,
                trigger_running_at,
                f"定时 {trigger_running_at[:16].replace('T', ' ')}",
                "running",
                "dispatch_requested",
                "asg-running",
                "node-running",
                trigger_running_at,
                (now_minute - timedelta(minutes=2, seconds=30)).isoformat(timespec="seconds"),
            ),
            (
                "sti-recover-recent-failed",
                schedule_recent_failed_id,
                trigger_recent_failed_at,
                f"定时 {trigger_recent_failed_at[:16].replace('T', ' ')}",
                "dispatch_failed",
                "smoke baseline expired",
                "",
                "",
                trigger_recent_failed_at,
                (now_minute - timedelta(seconds=20)).isoformat(timespec="seconds"),
            ),
        ]
        conn.executemany(
            """
            INSERT INTO schedule_trigger_instances(
                trigger_instance_id,schedule_id,planned_trigger_at,trigger_rule_summary,trigger_rule_keys_json,merged_rule_count,
                trigger_status,trigger_message,assignment_ticket_id,assignment_node_id,schedule_name_snapshot,assigned_agent_id_snapshot,
                launch_summary_snapshot,execution_checklist_snapshot,done_definition_snapshot,expected_artifact_snapshot,
                delivery_mode_snapshot,delivery_receiver_agent_id_snapshot,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    trigger_id,
                    schedule_ref,
                    planned_trigger_at,
                    trigger_rule_summary,
                    "[]",
                    1,
                    trigger_status,
                    trigger_message,
                    assignment_ticket_id,
                    assignment_node_id,
                    "[持续迭代] workflow",
                    "workflow",
                    "self iteration",
                    "keep going",
                    "done",
                    "continuous-improvement-report.md",
                    "none",
                    "",
                    created_at,
                    updated_at,
                )
                for (
                    trigger_id,
                    schedule_ref,
                    planned_trigger_at,
                    trigger_rule_summary,
                    trigger_status,
                    trigger_message,
                    assignment_ticket_id,
                    assignment_node_id,
                    created_at,
                    updated_at,
                ) in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()

    calls = []
    original_start = schedule_service._start_schedule_trigger_processing
    original_assignment_runtime_status = schedule_service._assignment_runtime_status
    original_start_limit = schedule_service.SCHEDULE_TRIGGER_RECOVERY_START_LIMIT_PER_PASS

    def fake_start(cfg_obj, **kwargs):
        calls.append(
            {
                "schedule_id": str(kwargs.get("schedule", {}).get("schedule_id") or "").strip(),
                "trigger_instance_id": str(kwargs.get("trigger_instance_id") or "").strip(),
            }
        )
        return True

    def fake_assignment_runtime_status(root_path, *, ticket_id: str, node_id: str):
        key = (str(ticket_id or "").strip(), str(node_id or "").strip())
        if key == ("asg-active", "node-active"):
            return {"assignment_status": "ready", "assignment_status_text": "待开始", "result_status": "queued"}
        if key == ("asg-running", "node-running"):
            return {"assignment_status": "running", "assignment_status_text": "进行中", "result_status": "running"}
        if key == ("asg-done", "node-done"):
            return {"assignment_status": "failed", "assignment_status_text": "失败", "result_status": "failed"}
        return {}

    schedule_service._start_schedule_trigger_processing = fake_start
    schedule_service._assignment_runtime_status = fake_assignment_runtime_status
    schedule_service.SCHEDULE_TRIGGER_RECOVERY_START_LIMIT_PER_PASS = 10
    try:
        result = schedule_service._resume_pending_schedule_triggers(cfg, operator="test-recover")
    finally:
        schedule_service._start_schedule_trigger_processing = original_start
        schedule_service._assignment_runtime_status = original_assignment_runtime_status
        schedule_service.SCHEDULE_TRIGGER_RECOVERY_START_LIMIT_PER_PASS = original_start_limit

    resumed_ids = {item["trigger_instance_id"] for item in result.get("items") or []}
    assert int(result.get("resumed_count") or 0) == 2, result
    assert resumed_ids == {"sti-recover-missing", "sti-recover-active"}, result
    assert {item["trigger_instance_id"] for item in calls} == resumed_ids, calls
    print(json.dumps({"ok": True, "result": result, "calls": calls}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
