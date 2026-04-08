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

    root = Path.cwd() / ".test" / "runtime-schedule-exhausted-once-plan-repair"
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
        stale_schedule = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "pm持续唤醒 - workflow 主线巡检",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "stale once plan should retire after terminal result",
                "execution_checklist": "1) read detail\n2) project once-plan retirement\n3) preview filters stale plan",
                "done_definition": "detail and preview agree the stale plan is inactive while GET stays read-only",
                "priority": "P1",
                "expected_artifact": "workflow-pm-wake-summary",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": "2026-04-07T15:59:00+08:00"},
                },
            },
        )
        active_schedule = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "[持续迭代] workflow",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "future once plan should remain active",
                "execution_checklist": "1) keep enabled\n2) remain visible in preview",
                "done_definition": "active future once plan stays active",
                "priority": "P2",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": "2026-04-09T09:00:00+08:00"},
                },
            },
        )
    finally:
        schedule_service._load_available_agents = original_load_agents

    stale_schedule_id = str(stale_schedule.get("schedule_id") or "").strip()
    active_schedule_id = str(active_schedule.get("schedule_id") or "").strip()
    trigger_instance_id = "sti-exhausted-once-plan"
    assignment_ticket_id = "asg-exhausted-once-plan"
    assignment_node_id = "node-exhausted-once-plan"

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
                stale_schedule_id,
                "2026-04-07T15:59:00+08:00",
                "定时 2026-04-07 15:59",
                "[]",
                1,
                "running",
                "dispatch_requested",
                assignment_ticket_id,
                assignment_node_id,
                "pm持续唤醒 - workflow 主线巡检",
                "workflow",
                "stale once plan should retire after terminal result",
                "1) read detail\n2) project once-plan retirement\n3) preview filters stale plan",
                "detail and preview agree the stale plan is inactive while GET stays read-only",
                "workflow-pm-wake-summary",
                "none",
                "",
                "2026-04-07T15:59:01+08:00",
                "2026-04-07T15:59:01+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    original_assignment_runtime_status = schedule_service._assignment_runtime_status

    def fake_assignment_runtime_status(root_path, *, ticket_id: str, node_id: str):
        if str(ticket_id or "").strip() == assignment_ticket_id and str(node_id or "").strip() == assignment_node_id:
            return {
                "assignment_status": "succeeded",
                "assignment_status_text": "已完成",
                "assignment_graph_name": "任务中心全局主图",
                "assignment_node_name": "pm持续唤醒 - workflow 主线巡检 / 2026-04-07 15:59:00",
                "result_status": "succeeded",
                "result_status_text": schedule_service.SCHEDULE_RESULT_TEXT["succeeded"],
            }
        return {}

    schedule_service._assignment_runtime_status = fake_assignment_runtime_status
    try:
        detail = schedule_service.get_schedule_detail(root, stale_schedule_id)
        preview = schedule_service.list_schedule_preview(root, limit=8)
        listed = schedule_service.list_schedules(root)
    finally:
        schedule_service._assignment_runtime_status = original_assignment_runtime_status

    stale_detail = dict(detail.get("schedule") or {})
    recent = list(detail.get("recent_triggers") or [])
    assert stale_detail.get("enabled") is False, stale_detail
    assert stale_detail.get("next_trigger_at") == "", stale_detail
    assert stale_detail.get("next_trigger_text") == "停用中", stale_detail
    assert stale_detail.get("last_result_status") == "succeeded", stale_detail
    assert recent and dict(recent[0] or {}).get("trigger_status") == "succeeded", recent

    preview_items = list(preview.get("items") or [])
    assert int(preview.get("total") or 0) == 1, preview
    assert [str(item.get("schedule_id") or "").strip() for item in preview_items] == [active_schedule_id], preview

    listed_items = {str(item.get("schedule_id") or "").strip(): dict(item) for item in list(listed.get("items") or [])}
    assert listed_items.get(stale_schedule_id, {}).get("enabled") is False, listed_items
    assert listed_items.get(active_schedule_id, {}).get("enabled") is True, listed_items

    conn = schedule_service.connect_db(root)
    try:
        stale_row = conn.execute(
            """
            SELECT enabled,next_trigger_at,last_trigger_at,last_result_status,last_result_ticket_id,last_result_node_id
            FROM schedule_plans
            WHERE schedule_id=?
            LIMIT 1
            """,
            (stale_schedule_id,),
        ).fetchone()
    finally:
        conn.close()

    assert stale_row is not None, stale_schedule_id
    stored_row = dict(stale_row)
    assert int(stored_row.get("enabled") or 0) == 1, stored_row
    assert str(stored_row.get("next_trigger_at") or "").strip() == "", stored_row
    assert str(stored_row.get("last_trigger_at") or "").strip() == "", stored_row
    assert str(stored_row.get("last_result_status") or "").strip().lower() == "pending", stored_row
    assert str(stored_row.get("last_result_ticket_id") or "").strip() == "", stored_row
    assert str(stored_row.get("last_result_node_id") or "").strip() == "", stored_row

    print(
        json.dumps(
            {
                "ok": True,
                "stale_schedule_id": stale_schedule_id,
                "active_schedule_id": active_schedule_id,
                "detail_schedule": stale_detail,
                "preview": preview,
                "stored_row": stored_row,
                "storage_mutated_by_get": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
