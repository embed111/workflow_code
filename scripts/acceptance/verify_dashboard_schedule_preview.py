#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.api import dashboard
    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import schedule_service

    runtime_root = workspace_root / ".test" / "runtime-dashboard-schedule-preview"
    artifact_root = runtime_root / ".artifacts"
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    (runtime_root / "state").mkdir(parents=True, exist_ok=True)
    (artifact_root / "tasks" / "asg-preview" / "nodes").mkdir(parents=True, exist_ok=True)

    original_ws_resolver = getattr(ws, "resolve_artifact_root_path", None)
    original_schedule_resolver = getattr(schedule_service, "resolve_artifact_root_path", None)
    ws.resolve_artifact_root_path = lambda _root: artifact_root
    schedule_service.resolve_artifact_root_path = lambda _root: artifact_root

    try:
        schedule_service._ensure_schedule_tables(runtime_root)
        conn = schedule_service.connect_db(runtime_root)
        try:
            conn.execute(
                """
                INSERT INTO schedule_plans(
                    schedule_id,schedule_name,enabled,assigned_agent_id,assigned_agent_name,launch_summary,execution_checklist,done_definition,
                    priority,expected_artifact,delivery_mode,delivery_receiver_agent_id,delivery_receiver_agent_name,rule_sets_json,timezone,
                    next_trigger_at,last_trigger_at,last_result_status,last_result_ticket_id,last_result_node_id,created_by,updated_by,deleted_at,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "sch-preview-running",
                    "[持续迭代] workflow",
                    1,
                    "workflow",
                    "workflow",
                    "running preview",
                    "",
                    "",
                    2,
                    "continuous-improvement-report.md",
                    "none",
                    "",
                    "",
                    json.dumps([{"rule_type": "once", "date_times": ["2026-04-06T19:30:00+08:00"]}], ensure_ascii=False),
                    "Asia/Shanghai",
                    "2026-04-06T19:30:00+08:00",
                    "2026-04-06T19:16:00+08:00",
                    "queued",
                    "asg-preview",
                    "node-sti-preview-running",
                    "test",
                    "test",
                    "",
                    "2026-04-06T19:16:01+08:00",
                    "2026-04-06T19:16:40+08:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO schedule_plans(
                    schedule_id,schedule_name,enabled,assigned_agent_id,assigned_agent_name,launch_summary,execution_checklist,done_definition,
                    priority,expected_artifact,delivery_mode,delivery_receiver_agent_id,delivery_receiver_agent_name,rule_sets_json,timezone,
                    next_trigger_at,last_trigger_at,last_result_status,last_result_ticket_id,last_result_node_id,created_by,updated_by,deleted_at,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "sch-preview-failed",
                    "pm持续唤醒 - workflow 主线巡检",
                    1,
                    "workflow",
                    "workflow",
                    "failed preview",
                    "",
                    "",
                    2,
                    "pm-awake-summary.md",
                    "none",
                    "",
                    "",
                    json.dumps([{"rule_type": "daily", "times": ["21:30"]}], ensure_ascii=False),
                    "Asia/Shanghai",
                    "2026-04-06T21:30:00+08:00",
                    "2026-04-06T18:30:00+08:00",
                    "queued",
                    "asg-preview",
                    "node-sti-preview-failed",
                    "test",
                    "test",
                    "",
                    "2026-04-06T18:30:01+08:00",
                    "2026-04-06T18:47:17+08:00",
                ),
            )
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
                    "sti-preview-running",
                    "sch-preview-running",
                    "2026-04-06T19:16:00+08:00",
                    "定时 2026-04-06 19:16",
                    "[]",
                    1,
                    "queued",
                    "待开始",
                    "asg-preview",
                    "node-sti-preview-running",
                    "[持续迭代] workflow",
                    "workflow",
                    "running preview",
                    "",
                    "",
                    "continuous-improvement-report.md",
                    "none",
                    "",
                    "2026-04-06T19:16:00+08:00",
                    "2026-04-06T19:16:00+08:00",
                ),
            )
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
                    "sti-preview-failed",
                    "sch-preview-failed",
                    "2026-04-06T18:30:00+08:00",
                    "每日 18:30",
                    "[]",
                    1,
                    "queued",
                    "待开始",
                    "asg-preview",
                    "node-sti-preview-failed",
                    "pm持续唤醒 - workflow 主线巡检",
                    "workflow",
                    "failed preview",
                    "",
                    "",
                    "pm-awake-summary.md",
                    "none",
                    "",
                    "2026-04-06T18:30:00+08:00",
                    "2026-04-06T18:30:00+08:00",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        _write_json(
            artifact_root / "tasks" / "asg-preview" / "task.json",
            {
                "ticket_id": "asg-preview",
                "graph_name": "任务中心全局主图",
                "source_workflow": "workflow-ui",
                "external_request_id": "workflow-ui-global-graph-v1",
                "record_state": "active",
            },
        )
        _write_json(
            artifact_root / "tasks" / "asg-preview" / "nodes" / "node-sti-preview-running.json",
            {
                "node_id": "node-sti-preview-running",
                "node_name": "[持续迭代] workflow / 2026-04-06 19:16:00",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "source_schedule_id": "sch-preview-running",
                "trigger_instance_id": "sti-preview-running",
                "status": "running",
                "status_text": "进行中",
                "record_state": "active",
            },
        )
        _write_json(
            artifact_root / "tasks" / "asg-preview" / "nodes" / "node-sti-preview-failed.json",
            {
                "node_id": "node-sti-preview-failed",
                "node_name": "pm持续唤醒 - workflow 主线巡检 / 2026-04-06 18:30:00",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "source_schedule_id": "sch-preview-failed",
                "trigger_instance_id": "sti-preview-failed",
                "status": "failed",
                "status_text": "失败",
                "record_state": "active",
            },
        )

        cfg = type("Cfg", (), {"root": runtime_root})()
        preview_items, preview_total = dashboard._schedule_preview_payload(cfg)
        preview_by_id = {str(item.get("schedule_id") or "").strip(): item for item in preview_items}

        running_item = dict(preview_by_id.get("sch-preview-running") or {})
        failed_item = dict(preview_by_id.get("sch-preview-failed") or {})

        assert preview_total == 2, {"preview_total": preview_total, "preview_items": preview_items}
        assert str(running_item.get("last_result_status") or "").strip() == "running", running_item
        assert str(running_item.get("last_result_status_text") or "").strip() == "运行中", running_item
        assert str(failed_item.get("last_result_status") or "").strip() == "failed", failed_item
        assert str(failed_item.get("last_result_status_text") or "").strip() == "已失败", failed_item

        print(
            json.dumps(
                {
                    "ok": True,
                    "preview_total": preview_total,
                    "preview_statuses": {
                        "sch-preview-running": running_item.get("last_result_status"),
                        "sch-preview-failed": failed_item.get("last_result_status"),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        if callable(original_ws_resolver):
            ws.resolve_artifact_root_path = original_ws_resolver
        if callable(original_schedule_resolver):
            schedule_service.resolve_artifact_root_path = original_schedule_resolver


if __name__ == "__main__":
    raise SystemExit(main())
