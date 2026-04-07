#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assert(condition: bool, message: str, payload: object | None = None) -> None:
    if condition:
        return
    raise AssertionError(f"{message}: {payload!r}")


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import schedule_service

    runtime_root = workspace_root / ".test" / "runtime-schedule-text-repair"
    artifact_root = runtime_root / ".artifacts"
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    (runtime_root / "state").mkdir(parents=True, exist_ok=True)

    original_resolver = getattr(schedule_service, "resolve_artifact_root_path", None)
    original_loader = getattr(schedule_service, "_load_available_agents", None)
    original_now = getattr(schedule_service, "_now_bj", None)
    schedule_service.resolve_artifact_root_path = lambda _root: artifact_root
    schedule_service._load_available_agents = lambda _cfg: [{"agent_id": "workflow", "agent_name": "workflow"}]
    schedule_service._now_bj = lambda: datetime(2026, 4, 7, 9, 0, tzinfo=schedule_service.BEIJING_TZ)

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
                    "sch-self-iter-bad",
                    "[????] workflow",
                    1,
                    "workflow",
                    "workflow",
                    "????????????",
                    "",
                    "",
                    1,
                    "continuous-improvement-report.md",
                    "none",
                    "",
                    "",
                    json.dumps([{"rule_type": "once", "date_times": ["2026-04-07T17:45:00+08:00"]}], ensure_ascii=False),
                    "Asia/Shanghai",
                    "2026-04-07T17:45:00+08:00",
                    "2026-04-07T17:10:00+08:00",
                    "running",
                    "asg-repair",
                    "node-self-iter",
                    "test",
                    "test",
                    "",
                    "2026-04-07T17:10:00+08:00",
                    "2026-04-07T17:10:00+08:00",
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
                    "sch-pm-wake-bad",
                    "",
                    1,
                    "workflow",
                    "workflow",
                    "",
                    "",
                    "",
                    1,
                    "workflow-pm-wake-summary",
                    "none",
                    "",
                    "",
                    json.dumps([{"rule_type": "once", "date_times": ["2026-04-07T17:40:00+08:00"]}], ensure_ascii=False),
                    "Asia/Shanghai",
                    "2026-04-07T17:40:00+08:00",
                    "",
                    "pending",
                    "",
                    "",
                    "test",
                    "test",
                    "",
                    "2026-04-07T17:10:00+08:00",
                    "2026-04-07T17:10:00+08:00",
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
                    "sti-self-iter",
                    "sch-self-iter-bad",
                    "2026-04-07T17:10:00+08:00",
                    "定时 2026-04-07 17:10",
                    "[]",
                    1,
                    "running",
                    "dispatch_requested",
                    "asg-repair",
                    "node-self-iter",
                    "",
                    "workflow",
                    "",
                    "",
                    "",
                    "continuous-improvement-report.md",
                    "none",
                    "",
                    "2026-04-07T17:10:00+08:00",
                    "2026-04-07T17:10:00+08:00",
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
                    "sti-pm-wake",
                    "sch-pm-wake-bad",
                    "2026-04-07T15:59:00+08:00",
                    "定时 2026-04-07 15:59",
                    "[]",
                    1,
                    "succeeded",
                    "dispatch_requested",
                    "asg-repair",
                    "node-pm-wake",
                    "pm???? - workflow ????",
                    "workflow",
                    "",
                    "",
                    "",
                    "workflow-pm-wake-summary",
                    "none",
                    "",
                    "2026-04-07T15:59:00+08:00",
                    "2026-04-07T15:59:00+08:00",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        _write_json(
            artifact_root / "tasks" / "asg-repair" / "task.json",
            {
                "ticket_id": "asg-repair",
                "graph_name": "任务中心全局主图",
                "source_workflow": "workflow-ui",
                "external_request_id": "workflow-ui-global-graph-v1",
                "record_state": "active",
            },
        )
        _write_json(
            artifact_root / "tasks" / "asg-repair" / "nodes" / "node-self-iter.json",
            {
                "node_id": "node-self-iter",
                "node_name": "[持续迭代] workflow / 2026-04-07 17:10:00",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "source_schedule_id": "sch-self-iter-bad",
                "trigger_instance_id": "sti-self-iter",
                "status": "running",
                "status_text": "进行中",
                "record_state": "active",
            },
        )
        _write_json(
            artifact_root / "tasks" / "asg-repair" / "nodes" / "node-pm-wake.json",
            {
                "node_id": "node-pm-wake",
                "node_name": "pm持续唤醒 - workflow 主线巡检 / 2026-04-07 15:59:00",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "source_schedule_id": "sch-pm-wake-bad",
                "trigger_instance_id": "sti-pm-wake",
                "status": "succeeded",
                "status_text": "已完成",
                "record_state": "active",
            },
        )

        cfg = type("Cfg", (), {"root": runtime_root})()
        preview = schedule_service.list_schedule_preview(runtime_root)
        schedule_list = schedule_service.list_schedules(runtime_root)
        detail = schedule_service.get_schedule_detail(runtime_root, "sch-self-iter-bad")
        calendar = schedule_service.get_schedule_calendar(runtime_root, month="2026-04")

        preview_by_id = {str(item.get("schedule_id") or ""): item for item in list(preview.get("items") or [])}
        list_by_id = {str(item.get("schedule_id") or ""): item for item in list(schedule_list.get("items") or [])}
        detail_schedule = dict(detail.get("schedule") or {})
        recent_triggers = list(detail.get("recent_triggers") or [])
        calendar_day = next(
            (item for item in list(calendar.get("days") or []) if str(item.get("date") or "") == "2026-04-07"),
            {},
        )

        _assert(
            preview_by_id["sch-self-iter-bad"]["schedule_name"] == "[持续迭代] workflow",
            "preview self-iteration schedule should repair title",
            preview_by_id.get("sch-self-iter-bad"),
        )
        _assert(
            list_by_id["sch-pm-wake-bad"]["schedule_name"] == "pm持续唤醒 - workflow 主线巡检",
            "list should repair pm wake title",
            list_by_id.get("sch-pm-wake-bad"),
        )
        _assert(
            "版本计划" in str(detail_schedule.get("launch_summary") or ""),
            "detail should repair self-iteration summary",
            detail_schedule,
        )
        _assert(
            recent_triggers and recent_triggers[0].get("schedule_name_snapshot") == "[持续迭代] workflow",
            "recent trigger snapshot should repair self-iteration title",
            recent_triggers,
        )
        calendar_plan_names = {str(item.get("schedule_name") or "") for item in list(calendar_day.get("plans") or [])}
        calendar_result_names = {str(item.get("schedule_name_snapshot") or "") for item in list(calendar_day.get("results") or [])}
        _assert(
            "[持续迭代] workflow" in calendar_plan_names,
            "calendar plans should use repaired self-iteration title",
            calendar_day,
        )
        _assert(
            "pm持续唤醒 - workflow 主线巡检" in calendar_result_names,
            "calendar results should use repaired pm wake title",
            calendar_day,
        )

        update_body = {
            "operator": "test",
            "schedule_name": "[????] workflow",
            "launch_summary": "????????????",
            "execution_checklist": "????????",
            "done_definition": "????????",
        }
        schedule_service.update_schedule(cfg, "sch-self-iter-bad", update_body)
        updated_detail = schedule_service.get_schedule_detail(runtime_root, "sch-self-iter-bad")
        updated_schedule = dict(updated_detail.get("schedule") or {})
        _assert(
            updated_schedule.get("schedule_name") == "[持续迭代] workflow",
            "update should refuse to persist repaired title back to question marks",
            updated_schedule,
        )
        _assert(
            "版本计划" in str(updated_schedule.get("launch_summary") or ""),
            "update should keep repaired launch summary",
            updated_schedule,
        )

        print(
            json.dumps(
                {
                    "ok": True,
                    "preview_total": preview.get("total"),
                    "list_total": schedule_list.get("total"),
                    "detail_schedule_name": detail_schedule.get("schedule_name"),
                    "updated_schedule_name": updated_schedule.get("schedule_name"),
                    "calendar_plan_names": sorted(calendar_plan_names),
                    "calendar_result_names": sorted(calendar_result_names),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        if callable(original_resolver):
            schedule_service.resolve_artifact_root_path = original_resolver
        if callable(original_loader):
            schedule_service._load_available_agents = original_loader
        if callable(original_now):
            schedule_service._now_bj = original_now


if __name__ == "__main__":
    raise SystemExit(main())
