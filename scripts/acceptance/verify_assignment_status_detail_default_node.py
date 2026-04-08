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
    nodes_root = task_root / "nodes"
    _write_json(
        task_root / "task.json",
        {
            "ticket_id": ticket_id,
            "graph_name": f"status-detail-default-{ticket_id}",
            "source_workflow": "acceptance",
            "summary": "verify assignment status-detail default selected node",
            "review_mode": "none",
            "global_concurrency_limit": 5,
            "record_state": "active",
            "is_test_data": False,
            "external_request_id": f"status-detail-default-{ticket_id}",
            "scheduler_state": "running",
            "pause_note": "",
            "created_at": "2026-04-08T20:00:00+08:00",
            "updated_at": "2026-04-08T20:00:00+08:00",
        },
    )
    for node in nodes:
        _write_json(nodes_root / f"{node['node_id']}.json", node)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    runtime_root = (repo_root / ".test" / "runtime-assignment-status-detail-default-node").resolve()
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

    _seed_ticket(
        runtime_root,
        ticket_id="asg-status-detail-default-running",
        nodes=[
            {
                "ticket_id": "asg-status-detail-default-running",
                "node_id": "node-old-failed",
                "node_name": "old failed",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "status": "failed",
                "status_text": "失败",
                "priority": 1,
                "priority_label": "P1",
                "record_state": "active",
                "created_at": "2026-04-08T19:00:00+08:00",
                "updated_at": "2026-04-08T19:01:00+08:00",
                "completed_at": "2026-04-08T19:01:00+08:00",
                "failure_reason": "old failed node",
            },
            {
                "ticket_id": "asg-status-detail-default-running",
                "node_id": "node-new-succeeded",
                "node_name": "new succeeded",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "status": "succeeded",
                "status_text": "已成功",
                "priority": 2,
                "priority_label": "P2",
                "record_state": "active",
                "created_at": "2026-04-08T20:00:00+08:00",
                "updated_at": "2026-04-08T20:02:00+08:00",
                "completed_at": "2026-04-08T20:02:00+08:00",
                "success_reason": "new succeeded node",
            },
            {
                "ticket_id": "asg-status-detail-default-running",
                "node_id": "node-current-running",
                "node_name": "current running",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "status": "running",
                "status_text": "进行中",
                "priority": 2,
                "priority_label": "P2",
                "record_state": "active",
                "created_at": "2026-04-08T20:30:00+08:00",
                "updated_at": "2026-04-08T20:35:00+08:00",
            },
        ],
    )
    _seed_ticket(
        runtime_root,
        ticket_id="asg-status-detail-default-terminal",
        nodes=[
            {
                "ticket_id": "asg-status-detail-default-terminal",
                "node_id": "node-terminal-failed",
                "node_name": "terminal failed",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "status": "failed",
                "status_text": "失败",
                "priority": 1,
                "priority_label": "P1",
                "record_state": "active",
                "created_at": "2026-04-08T19:00:00+08:00",
                "updated_at": "2026-04-08T19:01:00+08:00",
                "completed_at": "2026-04-08T19:01:00+08:00",
                "failure_reason": "older failure",
            },
            {
                "ticket_id": "asg-status-detail-default-terminal",
                "node_id": "node-terminal-succeeded",
                "node_name": "terminal succeeded",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "status": "succeeded",
                "status_text": "已成功",
                "priority": 2,
                "priority_label": "P2",
                "record_state": "active",
                "created_at": "2026-04-08T20:00:00+08:00",
                "updated_at": "2026-04-08T20:02:00+08:00",
                "completed_at": "2026-04-08T20:02:00+08:00",
                "success_reason": "latest terminal",
            },
        ],
    )

    running_default = ws.get_assignment_status_detail(
        runtime_root,
        "asg-status-detail-default-running",
        include_test_data=False,
    )
    running_selected = dict(running_default.get("selected_node") or {})
    assert str(running_selected.get("node_id") or "").strip() == "node-current-running", running_selected

    explicit_old = ws.get_assignment_status_detail(
        runtime_root,
        "asg-status-detail-default-running",
        node_id_text="node-old-failed",
        include_test_data=False,
    )
    explicit_selected = dict(explicit_old.get("selected_node") or {})
    assert str(explicit_selected.get("node_id") or "").strip() == "node-old-failed", explicit_selected

    terminal_default = ws.get_assignment_status_detail(
        runtime_root,
        "asg-status-detail-default-terminal",
        include_test_data=False,
    )
    terminal_selected = dict(terminal_default.get("selected_node") or {})
    assert str(terminal_selected.get("node_id") or "").strip() == "node-terminal-succeeded", terminal_selected

    print(
        json.dumps(
            {
                "ok": True,
                "running_default_node_id": running_selected.get("node_id"),
                "explicit_node_id": explicit_selected.get("node_id"),
                "terminal_default_node_id": terminal_selected.get("node_id"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
