#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import schedule_service

    root = workspace_root / ".test" / "runtime-schedule-upgrade-drain-recovery"
    if root.exists():
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
    try:
        created = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "[持续迭代] workflow",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "verify queued trigger waits during prod upgrade drain",
                "execution_checklist": "1) drain active\n2) queued trigger stays waiting\n3) drain lifted\n4) recovery resumes dispatch",
                "done_definition": "queued trigger only resumes after upgrade drain lifted",
                "priority": "P1",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": "2026-04-11T20:00:00+08:00"},
                },
            },
        )
    finally:
        schedule_service._load_available_agents = original_load_agents

    schedule_id = str(created.get("schedule_id") or "").strip()
    now_minute = schedule_service._minute_floor(schedule_service._now_bj())
    planned_trigger_at = (now_minute - timedelta(minutes=5)).isoformat(timespec="seconds")
    trigger_id = "sti-upgrade-drain-wait"
    trigger_message = "[upgrade_drain_active:candidate_newer_pending_idle_window] 已存在更高 prod candidate，冻结新派发为 idle watcher 创造升级空窗。"

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
                trigger_id,
                schedule_id,
                planned_trigger_at,
                f"定时 {planned_trigger_at[:16].replace('T', ' ')}",
                "[]",
                1,
                "queued",
                trigger_message,
                "asg-upgrade-drain",
                "node-upgrade-drain",
                "[持续迭代] workflow",
                "workflow",
                "verify queued trigger waits during prod upgrade drain",
                "keep waiting",
                "resume after drain",
                "continuous-improvement-report.md",
                "none",
                "",
                planned_trigger_at,
                planned_trigger_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    calls: list[dict[str, str]] = []
    original_start = schedule_service._start_schedule_trigger_processing
    original_assignment_runtime_status = schedule_service._assignment_runtime_status
    original_drain_state = schedule_service._schedule_prod_upgrade_dispatch_drain_state

    def fake_start(cfg_obj, **kwargs):
        calls.append(
            {
                "schedule_id": str(kwargs.get("schedule", {}).get("schedule_id") or "").strip(),
                "trigger_instance_id": str(kwargs.get("trigger_instance_id") or "").strip(),
            }
        )
        return True

    def fake_assignment_runtime_status(root_path, *, ticket_id: str, node_id: str, persist_repair: bool = False):
        return {
            "assignment_status": "ready",
            "assignment_status_text": "待开始",
            "result_status": "queued",
        }

    schedule_service._start_schedule_trigger_processing = fake_start
    schedule_service._assignment_runtime_status = fake_assignment_runtime_status
    schedule_service._schedule_prod_upgrade_dispatch_drain_state = lambda: {
        "active": True,
        "code": "candidate_newer_pending_idle_window",
        "reason": "已存在更高 prod candidate，冻结新派发为 idle watcher 创造升级空窗。",
    }
    try:
        blocked_result = schedule_service._resume_pending_schedule_triggers(cfg, operator="test-upgrade-drain")
    finally:
        schedule_service._schedule_prod_upgrade_dispatch_drain_state = original_drain_state

    assert int(blocked_result.get("resumed_count") or 0) == 0, blocked_result
    assert not calls, calls

    schedule_service._schedule_prod_upgrade_dispatch_drain_state = lambda: {
        "active": False,
        "code": "",
        "reason": "",
    }
    try:
        resumed_result = schedule_service._resume_pending_schedule_triggers(cfg, operator="test-upgrade-drain")
    finally:
        schedule_service._start_schedule_trigger_processing = original_start
        schedule_service._assignment_runtime_status = original_assignment_runtime_status
        schedule_service._schedule_prod_upgrade_dispatch_drain_state = original_drain_state

    resumed_ids = {str(item.get("trigger_instance_id") or "").strip() for item in list(resumed_result.get("items") or [])}
    assert int(resumed_result.get("resumed_count") or 0) == 1, resumed_result
    assert resumed_ids == {trigger_id}, resumed_result
    assert {item["trigger_instance_id"] for item in calls} == {trigger_id}, calls

    print(
        json.dumps(
            {
                "ok": True,
                "blocked_result": blocked_result,
                "resumed_result": resumed_result,
                "calls": calls,
                "trigger_message": trigger_message,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
