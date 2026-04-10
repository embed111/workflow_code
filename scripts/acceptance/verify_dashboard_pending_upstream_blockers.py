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

    runtime_root = (repo_root / ".test" / "runtime-dashboard-pending-upstream-blockers").resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)

    artifact_root = (runtime_root / "artifacts").resolve()
    task_root = artifact_root / "tasks" / "asg-dashboard-pending-upstream-blockers"
    nodes_root = task_root / "nodes"
    _write_json(
        task_root / "task.json",
        {
            "ticket_id": "asg-dashboard-pending-upstream-blockers",
            "graph_name": "dashboard pending upstream blockers",
            "source_workflow": "workflow-ui",
            "external_request_id": "workflow-ui-global-graph-v1",
            "record_state": "active",
            "is_test_data": False,
        },
    )
    _write_json(
        nodes_root / "node-persona-blocked.json",
        {
            "ticket_id": "asg-dashboard-pending-upstream-blockers",
            "node_id": "node-persona-blocked",
            "node_name": "persona blocked",
            "assigned_agent_id": "workflow_qualitymate",
            "assigned_agent_name": "workflow_qualitymate",
            "status": "blocked",
            "status_text": "阻塞",
            "priority": 1,
            "priority_label": "P1",
            "record_state": "active",
            "upstream_node_ids": [],
        },
    )
    _write_json(
        nodes_root / "node-capability-pending.json",
        {
            "ticket_id": "asg-dashboard-pending-upstream-blockers",
            "node_id": "node-capability-pending",
            "node_name": "capability waiting upstream",
            "assigned_agent_id": "workflow_qualitymate",
            "assigned_agent_name": "workflow_qualitymate",
            "status": "pending",
            "status_text": "待开始",
            "priority": 1,
            "priority_label": "P1",
            "record_state": "active",
            "upstream_node_ids": ["node-persona-blocked"],
        },
    )
    _write_json(
        nodes_root / "node-review-pending.json",
        {
            "ticket_id": "asg-dashboard-pending-upstream-blockers",
            "node_id": "node-review-pending",
            "node_name": "review waiting upstream",
            "assigned_agent_id": "workflow_qualitymate",
            "assigned_agent_name": "workflow_qualitymate",
            "status": "pending",
            "status_text": "待开始",
            "priority": 1,
            "priority_label": "P1",
            "record_state": "active",
            "upstream_node_ids": ["node-capability-pending"],
        },
    )
    _write_json(
        nodes_root / "node-ready.json",
        {
            "ticket_id": "asg-dashboard-pending-upstream-blockers",
            "node_id": "node-ready",
            "node_name": "ready node",
            "assigned_agent_id": "workflow_devmate",
            "assigned_agent_name": "workflow_devmate",
            "status": "ready",
            "status_text": "待开始",
            "priority": 1,
            "priority_label": "P1",
            "record_state": "active",
            "upstream_node_ids": [],
        },
    )

    cfg = type("Cfg", (), {"root": runtime_root})()
    _write_json(
        runtime_root / "state" / "runtime-config.json",
        {
            "artifact_root": artifact_root.as_posix(),
            "task_artifact_root": artifact_root.as_posix(),
            "agent_search_root": "C:/work/J-Agents",
            "show_test_data": False,
        },
    )

    payload = dashboard._workboard_payload(cfg, include_test_data=False)
    summary = dict(payload.get("assignment_workboard_summary") or {})
    groups = list(payload.get("assignment_workboard_agents") or [])
    quality_group = next(
        (item for item in groups if str(item.get("agent_id") or "").strip() == "workflow_qualitymate"),
        {},
    )
    blocked = list(quality_group.get("blocked") or [])

    assert int(summary.get("active_agent_count") or 0) == 1, summary
    assert int(summary.get("queued_task_count") or 0) == 1, summary
    assert int(summary.get("blocked_task_count") or 0) == 3, summary
    assert len(blocked) == 3, quality_group
    waiting = {
        str(item.get("node_id") or "").strip(): item
        for item in blocked
        if bool(item.get("waiting_upstream"))
    }
    assert set(waiting) == {"node-capability-pending", "node-review-pending"}, waiting
    assert str(waiting["node-capability-pending"].get("status_text") or "").strip() == "等待上游", waiting
    assert str(waiting["node-review-pending"].get("status_text") or "").strip() == "等待上游", waiting

    print(
        json.dumps(
            {
                "ok": True,
                "summary": summary,
                "blocked_node_ids": [str(item.get("node_id") or "").strip() for item in blocked],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
