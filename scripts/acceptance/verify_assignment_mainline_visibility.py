#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_ticket(root: Path, *, ticket_id: str, nodes: list[dict]) -> None:
    artifact_root = (root / "artifacts-root").resolve()
    task_root = artifact_root / "tasks" / ticket_id
    _write_json(
        task_root / "task.json",
        {
            "ticket_id": ticket_id,
            "graph_name": "assignment-mainline-visibility",
            "source_workflow": "workflow-ui",
            "summary": "verify workflow mainline visibility and display fallback",
            "review_mode": "none",
            "global_concurrency_limit": 5,
            "record_state": "active",
            "is_test_data": False,
            "external_request_id": "assignment-mainline-visibility-v1",
            "scheduler_state": "running",
            "pause_note": "",
            "created_at": "2026-04-09T12:00:00+08:00",
            "updated_at": "2026-04-09T12:00:00+08:00",
        },
    )
    for node in nodes:
        _write_json(task_root / "nodes" / f"{node['node_id']}.json", node)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.api import dashboard as dashboard_api
    from workflow_app.server.bootstrap import web_server_runtime as ws

    runtime_root = (repo_root / ".test" / "runtime-assignment-mainline-visibility").resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    (runtime_root / "state").mkdir(parents=True, exist_ok=True)
    artifact_root = (runtime_root / "artifacts-root").resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        runtime_root / "state" / "runtime-config.json",
        {
            "show_test_data": False,
            "agent_search_root": "C:/work/J-Agents",
            "artifact_root": artifact_root.as_posix(),
            "task_artifact_root": artifact_root.as_posix(),
        },
    )

    ticket_id = "asg-assignment-mainline-visibility"
    patrol_node_id = "node-patrol-running"
    mainline_node_id = "node-mainline-ready"
    failed_node_id = "node-garbled-failed"
    _seed_ticket(
        runtime_root,
        ticket_id=ticket_id,
        nodes=[
            {
                "ticket_id": ticket_id,
                "node_id": patrol_node_id,
                "node_name": "pm持续唤醒 - workflow 主线巡检 / 2026-04-09 12:22:00",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "expected_artifact": "workflow-pm-wake-summary",
                "status": "running",
                "status_text": "进行中",
                "priority": 1,
                "priority_label": "P1",
                "record_state": "active",
                "created_at": "2026-04-09T12:22:00+08:00",
                "updated_at": "2026-04-09T12:30:00+08:00",
            },
            {
                "ticket_id": ticket_id,
                "node_id": mainline_node_id,
                "node_name": "[持续迭代] workflow / 2026-04-09 12:40:00",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "expected_artifact": "continuous-improvement-report.md",
                "status": "ready",
                "status_text": "待开始",
                "priority": 2,
                "priority_label": "P2",
                "record_state": "active",
                "created_at": "2026-04-09T12:40:00+08:00",
                "updated_at": "2026-04-09T12:40:00+08:00",
            },
            {
                "ticket_id": ticket_id,
                "node_id": failed_node_id,
                "node_name": "V1-P4 prod ??????",
                "assigned_agent_id": "workflow_qualitymate",
                "assigned_agent_name": "workflow_qualitymate",
                "expected_artifact": "qualitymate-prod-quality-report.md",
                "status": "failed",
                "status_text": "失败",
                "priority": 1,
                "priority_label": "P1",
                "record_state": "active",
                "created_at": "2026-04-09T11:20:00+08:00",
                "updated_at": "2026-04-09T11:21:00+08:00",
                "completed_at": "2026-04-09T11:21:00+08:00",
                "failure_reason": "quality failed",
            },
        ],
    )

    original_live_keys = ws._assignment_live_run_keys_from_files
    original_live_node_ids = ws._assignment_live_node_ids_for_ticket
    try:
        ws._assignment_live_run_keys_from_files = lambda *args, **kwargs: {(ticket_id, patrol_node_id)}
        ws._assignment_live_node_ids_for_ticket = lambda *args, **kwargs: {patrol_node_id}

        status_detail = ws.get_assignment_status_detail(
            runtime_root,
            ticket_id,
            include_test_data=False,
        )
        selected_node = dict(status_detail.get("selected_node") or {})
        assert str(selected_node.get("node_id") or "").strip() == mainline_node_id, selected_node
        assert bool(selected_node.get("is_workflow_mainline")), selected_node

        graph_payload = ws.get_assignment_graph(
            runtime_root,
            ticket_id,
            include_test_data=False,
        )
        failed_node = next(
            (
                item
                for item in list(graph_payload.get("nodes") or [])
                if str(item.get("node_id") or "").strip() == failed_node_id
            ),
            {},
        )
        assert str(failed_node.get("node_name") or "").strip() == "qualitymate-prod-quality-report.md", failed_node

        cfg = type("Cfg", (), {"root": runtime_root})()
        workboard = dashboard_api._workboard_payload(cfg, include_test_data=False)
        workflow_group = next(
            (
                item
                for item in list(workboard.get("assignment_workboard_agents") or [])
                if str(item.get("agent_id") or "").strip() == "workflow"
            ),
            {},
        )
        assert bool(workflow_group.get("workflow_mainline_handoff_pending")), workflow_group
        assert "[持续迭代] workflow" in str(workflow_group.get("workflow_mainline_handoff_note") or ""), workflow_group
    finally:
        ws._assignment_live_run_keys_from_files = original_live_keys
        ws._assignment_live_node_ids_for_ticket = original_live_node_ids

    print(
        json.dumps(
            {
                "ok": True,
                "selected_node_id": selected_node.get("node_id"),
                "sanitized_failed_name": failed_node.get("node_name"),
                "workflow_mainline_handoff_pending": workflow_group.get("workflow_mainline_handoff_pending"),
                "workflow_mainline_handoff_note": workflow_group.get("workflow_mainline_handoff_note"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
