#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path


def _write_runtime_config(root: Path) -> None:
    artifact_root = (root / "artifacts-root").resolve()
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(Path("D:/code/AI/J-Agents").resolve()),
                "artifact_root": artifact_root.as_posix(),
                "task_artifact_root": artifact_root.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import assignment_service, schedule_service

    runtime_root = workspace_root / ".test" / "runtime-workflow-mainline-handoff-priority"
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    _write_runtime_config(runtime_root)

    cfg = type(
        "Cfg",
        (),
        {
            "root": runtime_root,
            "agent_search_root": Path("D:/code/AI/J-Agents").resolve(),
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()

    original_schedule_load_agents = schedule_service._load_available_agents
    original_assignment_list_agents = assignment_service.list_available_agents
    original_start = schedule_service._start_schedule_trigger_processing
    original_worker = assignment_service._assignment_execution_worker
    original_start_limit = schedule_service.SCHEDULE_TRIGGER_RECOVERY_START_LIMIT_PER_PASS

    schedule_service._load_available_agents = lambda _cfg: [{"agent_id": "workflow", "agent_name": "workflow"}]
    assignment_service.list_available_agents = lambda _cfg, analyze_policy=False: [
        {"agent_id": "workflow", "agent_name": "workflow"}
    ]

    recovery_calls: list[dict[str, str]] = []

    def fake_start(cfg_obj, **kwargs):
        recovery_calls.append(
            {
                "schedule_id": str(kwargs.get("schedule", {}).get("schedule_id") or "").strip(),
                "trigger_instance_id": str(kwargs.get("trigger_instance_id") or "").strip(),
            }
        )
        return True

    def fake_worker(**_kwargs):
        return

    schedule_service._start_schedule_trigger_processing = fake_start
    assignment_service._assignment_execution_worker = fake_worker
    schedule_service.SCHEDULE_TRIGGER_RECOVERY_START_LIMIT_PER_PASS = 10
    try:
        future_once_at = (schedule_service._minute_floor(schedule_service._now_bj()) + timedelta(minutes=30)).isoformat(timespec="seconds")

        mainline_schedule = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "[持续迭代] workflow",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "mainline",
                "execution_checklist": "keep going",
                "done_definition": "done",
                "priority": "P1",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": future_once_at},
                },
            },
        )
        patrol_schedule = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "pm持续唤醒 - workflow 主线巡检",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "patrol",
                "execution_checklist": "observe",
                "done_definition": "done",
                "priority": "P1",
                "expected_artifact": "workflow-pm-wake-summary",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": future_once_at},
                },
            },
        )
        mainline_schedule_id = str(mainline_schedule.get("schedule_id") or "").strip()
        patrol_schedule_id = str(patrol_schedule.get("schedule_id") or "").strip()
        assert mainline_schedule_id and patrol_schedule_id

        now_minute = schedule_service._minute_floor(schedule_service._now_bj())
        mainline_trigger_at = (now_minute - timedelta(minutes=4)).isoformat(timespec="seconds")
        patrol_trigger_at = (now_minute - timedelta(minutes=4)).isoformat(timespec="seconds")

        conn = schedule_service.connect_db(runtime_root)
        try:
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
                        "sti-mainline-priority",
                        mainline_schedule_id,
                        mainline_trigger_at,
                        "workflow-mainline",
                        "[]",
                        1,
                        "queued",
                        "dispatch_requested",
                        "",
                        "",
                        "[持续迭代] workflow",
                        "workflow",
                        "mainline",
                        "keep going",
                        "done",
                        "continuous-improvement-report.md",
                        "none",
                        "",
                        mainline_trigger_at,
                        mainline_trigger_at,
                    ),
                    (
                        "sti-patrol-priority",
                        patrol_schedule_id,
                        patrol_trigger_at,
                        "workflow-patrol",
                        "[]",
                        1,
                        "queued",
                        "dispatch_requested",
                        "",
                        "",
                        "pm持续唤醒 - workflow 主线巡检",
                        "workflow",
                        "patrol",
                        "observe",
                        "done",
                        "workflow-pm-wake-summary",
                        "none",
                        "",
                        patrol_trigger_at,
                        patrol_trigger_at,
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        recovery_result = schedule_service._resume_pending_schedule_triggers(cfg, operator="test-recover")
        recovered_schedule_ids = [item["schedule_id"] for item in recovery_calls]
        assert recovered_schedule_ids[:2] == [mainline_schedule_id, patrol_schedule_id], recovery_calls
        assert int(recovery_result.get("resumed_count") or 0) == 2, recovery_result

        graph = ws.create_assignment_graph(
            cfg,
            {
                "graph_name": "workflow handoff priority",
                "source_workflow": "workflow-ui",
                "summary": "verify mainline dispatch beats patrol when workflow agent is free",
                "review_mode": "none",
                "external_request_id": "workflow-mainline-handoff-priority-v1",
                "operator": "test",
            },
        )
        ticket_id = str(graph.get("ticket_id") or "").strip()
        assert ticket_id, graph

        ws.create_assignment_node(
            cfg,
            ticket_id,
            {
                "node_id": "node-mainline-ready",
                "node_name": "[持续迭代] workflow / 2026-04-12 19:00",
                "assigned_agent_id": "workflow",
                "priority": "P1",
                "node_goal": "mainline handoff",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "operator": "test",
            },
            include_test_data=False,
        )
        ws.create_assignment_node(
            cfg,
            ticket_id,
            {
                "node_id": "node-patrol-ready",
                "node_name": "pm持续唤醒 - workflow 主线巡检 / 2026-04-12 19:00",
                "assigned_agent_id": "workflow",
                "priority": "P1",
                "node_goal": "patrol handoff",
                "expected_artifact": "workflow-pm-wake-summary",
                "delivery_mode": "none",
                "operator": "test",
            },
            include_test_data=False,
        )

        task_path = ws._assignment_graph_record_path(runtime_root, ticket_id)
        task_record = ws._assignment_read_json(task_path)
        task_record["scheduler_state"] = "running"
        task_record["updated_at"] = "2026-04-12T19:00:00+08:00"
        ws._assignment_write_json(task_path, task_record)
        for node_id in ("node-mainline-ready", "node-patrol-ready"):
            node_path = ws._assignment_node_record_path(runtime_root, ticket_id, node_id)
            node_record = ws._assignment_read_json(node_path)
            node_record["status"] = "ready"
            node_record["status_text"] = ws._node_status_text("ready")
            node_record["updated_at"] = "2026-04-12T19:00:00+08:00"
            ws._assignment_write_json(node_path, node_record)

        dispatch_result = ws.dispatch_assignment_next(
            runtime_root,
            ticket_id_text=ticket_id,
            operator="schedule-worker",
            include_test_data=False,
        )
        dispatched = [dict(item) for item in list(dispatch_result.get("dispatched") or [])]
        skipped = [dict(item) for item in list(dispatch_result.get("skipped") or [])]
        assert [str(item.get("node_id") or "").strip() for item in dispatched] == ["node-mainline-ready"], dispatch_result
        assert any(
            str(item.get("node_id") or "").strip() == "node-patrol-ready"
            and str(item.get("code") or "").strip() == "agent_busy"
            for item in skipped
        ), dispatch_result
    finally:
        schedule_service._load_available_agents = original_schedule_load_agents
        assignment_service.list_available_agents = original_assignment_list_agents
        schedule_service._start_schedule_trigger_processing = original_start
        assignment_service._assignment_execution_worker = original_worker
        schedule_service.SCHEDULE_TRIGGER_RECOVERY_START_LIMIT_PER_PASS = original_start_limit

    print(
        json.dumps(
            {
                "ok": True,
                "recovery_order": recovered_schedule_ids[:2],
                "dispatch_node_ids": [str(item.get("node_id") or "").strip() for item in dispatched],
                "skipped": skipped,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
