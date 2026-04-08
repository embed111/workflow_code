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
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.api import dashboard

    runtime_root = (repo_root / ".test" / "runtime-dashboard-active-agent-count").resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)

    artifact_root = (runtime_root / "artifacts").resolve()
    task_root = artifact_root / "tasks" / "asg-dashboard-active-count"
    nodes_root = task_root / "nodes"
    _write_json(
        task_root / "task.json",
        {
            "ticket_id": "asg-dashboard-active-count",
            "graph_name": "dashboard active agent count",
            "source_workflow": "workflow-ui",
            "external_request_id": "workflow-ui-global-graph-v1",
            "record_state": "active",
            "is_test_data": False,
        },
    )
    _write_json(
        nodes_root / "node-failed.json",
        {
            "ticket_id": "asg-dashboard-active-count",
            "node_id": "node-failed",
            "node_name": "failed only",
            "assigned_agent_id": "workflow_bugmate",
            "assigned_agent_name": "workflow_bugmate",
            "status": "failed",
            "status_text": "失败",
            "priority": 1,
            "priority_label": "P1",
            "record_state": "active",
        },
    )
    _write_json(
        nodes_root / "node-ready.json",
        {
            "ticket_id": "asg-dashboard-active-count",
            "node_id": "node-ready",
            "node_name": "ready node",
            "assigned_agent_id": "workflow_devmate",
            "assigned_agent_name": "workflow_devmate",
            "status": "ready",
            "status_text": "待开始",
            "priority": 1,
            "priority_label": "P1",
            "record_state": "active",
        },
    )

    cfg = type("Cfg", (), {"root": runtime_root})()
    runtime_config = runtime_root / "state" / "runtime-config.json"
    _write_json(
        runtime_config,
        {
            "artifact_root": artifact_root.as_posix(),
            "task_artifact_root": artifact_root.as_posix(),
            "agent_search_root": "C:/work/J-Agents",
            "show_test_data": False,
        },
    )

    payload = dashboard._workboard_payload(cfg, include_test_data=False)
    summary = dict(payload.get("assignment_workboard_summary") or {})

    assert int(summary.get("active_agent_count") or 0) == 1, summary
    assert int(summary.get("running_task_count") or 0) == 0, summary
    assert int(summary.get("queued_task_count") or 0) == 1, summary
    assert int(summary.get("failed_task_count") or 0) == 1, summary

    print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
