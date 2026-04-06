#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import schedule_service

    root = Path.cwd() / ".test" / "runtime-smoke-guard-recovery"
    if root.exists():
        import shutil

        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    artifact_root = (root / "artifacts-root").resolve()
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(Path("D:/code/AI/J-Agents").resolve()),
                "artifact_root": str(artifact_root),
                "task_artifact_root": str(artifact_root),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
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

    schedule = schedule_service.create_schedule(
        cfg,
        {
            "operator": "test",
            "schedule_name": "生产 smoke 基线 recovery",
            "enabled": True,
            "assigned_agent_id": "workflow",
            "launch_summary": "生产基线 smoke：验证定时命中到任务中心真实执行链",
            "execution_checklist": "1) 命中 schedule\n2) 建单并生成节点\n3) 自动派发\n4) 状态回写到计划详情",
            "done_definition": "计划详情可看到 trigger、assignment_ticket/node、最近结果状态和回写时间",
            "priority": "P1",
            "expected_artifact": "smoke-report",
            "delivery_mode": "none",
            "rule_sets": {
                "monthly": {"enabled": False},
                "weekly": {"enabled": False},
                "daily": {"enabled": False},
                "once": {"enabled": True, "date_times_text": "2026-04-06T15:54:00+08:00"},
            },
        },
    )
    schedule_id = str(schedule.get("schedule_id") or "").strip()
    newer_pending_schedule = schedule_service.create_schedule(
        cfg,
        {
            "operator": "test",
            "schedule_name": "生产 smoke 基线 newer-pending",
            "enabled": True,
            "assigned_agent_id": "workflow",
            "launch_summary": "生产基线 smoke：验证定时命中到任务中心真实执行链",
            "execution_checklist": "1) 命中 schedule\n2) 建单并生成节点\n3) 自动派发\n4) 状态回写到计划详情",
            "done_definition": "计划详情可看到 trigger、assignment_ticket/node、最近结果状态和回写时间",
            "priority": "P1",
            "expected_artifact": "smoke-report",
            "delivery_mode": "none",
            "rule_sets": {
                "monthly": {"enabled": False},
                "weekly": {"enabled": False},
                "daily": {"enabled": False},
                "once": {"enabled": True, "date_times_text": "2026-04-06T16:20:00+08:00"},
            },
        },
    )
    newer_schedule_id = str(newer_pending_schedule.get("schedule_id") or "").strip()
    trigger_id = "sti-test-smoke-recovery"
    planned_trigger_at = "2026-04-06T15:54:00+08:00"

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "任务中心全局主图",
            "source_workflow": "workflow-ui",
            "summary": "任务中心手动创建（全局主图）",
            "review_mode": "none",
            "external_request_id": "workflow-ui-global-graph-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_id": "node-sti-test-smoke-recovery",
            "node_name": "生产 smoke 基线 recovery / 2026-04-06 15:54:00",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "smoke baseline recovery",
            "expected_artifact": "smoke-report",
            "delivery_mode": "none",
            "source_schedule_id": schedule_id,
            "planned_trigger_at": planned_trigger_at,
            "trigger_instance_id": trigger_id,
            "trigger_rule_summary": "定时 2026-04-06 15:54",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "succeeded"
    node_payload["status_text"] = "已完成"
    node_payload["completed_at"] = "2026-04-06T16:11:34+08:00"
    node_payload["success_reason"] = "smoke passed"
    node_payload["updated_at"] = "2026-04-06T16:11:34+08:00"
    ws._assignment_write_json(node_path, node_payload)

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
                "定时 2026-04-06 15:54",
                "[]",
                1,
                "dispatch_requested",
                "dispatch_requested",
                ticket_id,
                node_id,
                "生产 smoke 基线 recovery",
                "workflow",
                "生产基线 smoke：验证定时命中到任务中心真实执行链",
                "1) 命中 schedule",
                "计划详情可看到 trigger、assignment_ticket/node、最近结果状态和回写时间",
                "smoke-report",
                "none",
                "",
                "2026-04-06T15:54:27+08:00",
                "2026-04-06T16:03:53+08:00",
            ),
        )
        conn.execute(
            """
            UPDATE schedule_plans
            SET last_trigger_at=?,last_result_status=?,last_result_ticket_id=?,last_result_node_id=?,updated_at=?
            WHERE schedule_id=?
            """,
            (
                planned_trigger_at,
                "running",
                ticket_id,
                node_id,
                "2026-04-06T16:03:53+08:00",
                schedule_id,
            ),
        )
        conn.execute(
            """
            UPDATE schedule_plans
            SET last_trigger_at=?,last_result_status=?,updated_at=?
            WHERE schedule_id=?
            """,
            (
                "2026-04-06T16:20:00+08:00",
                "running",
                "2026-04-06T16:20:05+08:00",
                newer_schedule_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    latest_path = root / ".test" / "schedule_smoke_baseline.latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "pass": False,
                "executed_at": "2026-04-06T15:54:52+08:00",
                "schedule_id": schedule_id,
                "latest_result_status": "pending",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ok, reason, report = schedule_service._smoke_baseline_valid(root, max_age_minutes=240)
    assert ok, {"reason": reason, "report": report}
    assert bool(report.get("pass")), report
    assert str(report.get("schedule_id") or "").strip() == schedule_id, report
    assert str(report.get("latest_result_status") or "").strip().lower() == "succeeded", report

    updated = json.loads(latest_path.read_text(encoding="utf-8"))
    assert bool(updated.get("pass")), updated
    assert str(updated.get("latest_result_status") or "").strip().lower() == "succeeded", updated

    print(
        json.dumps(
            {
                "ok": True,
                "schedule_id": schedule_id,
                "trigger_id": trigger_id,
                "report": updated,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
