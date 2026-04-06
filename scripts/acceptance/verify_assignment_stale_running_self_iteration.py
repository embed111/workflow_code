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

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import schedule_service

    root = Path.cwd() / ".test" / "runtime-stale-running-self-iteration"
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

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "任务中心全局主图",
            "source_workflow": "workflow-ui",
            "summary": "verify stale running self iteration",
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
            "node_name": "stale running self iteration",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "verify stale running queues next self iteration",
            "expected_artifact": "continuous-improvement-report.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id

    run_id = "arun-stale-self-iteration"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=str(workspace_root),
        status="running",
        command_summary="stale running self iteration",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="turn.started",
        latest_event_at="2026-04-07T00:00:00+08:00",
        exit_code=0,
        started_at="2026-04-07T00:00:00+08:00",
        finished_at="",
        created_at="2026-04-07T00:00:00+08:00",
        updated_at="2026-04-07T00:00:00+08:00",
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = "2026-04-07T00:00:00+08:00"
    ws._assignment_write_json(node_path, node_payload)

    original_load_agents = schedule_service._load_available_agents
    schedule_service._load_available_agents = lambda _cfg: [{"agent_id": "workflow", "agent_name": "workflow"}]
    try:
        ws.get_assignment_graph(
            root,
            ticket_id,
            include_test_data=False,
            active_batch_size=20,
            history_batch_size=20,
        )
    finally:
        schedule_service._load_available_agents = original_load_agents

    recovered_node = ws._assignment_read_json(node_path)
    schedules = ws.list_schedules(root)
    self_iter_items = [
        item
        for item in list(schedules.get("items") or [])
        if str(item.get("schedule_name") or "").strip() == "[持续迭代] workflow"
    ]

    assert str(recovered_node.get("status") or "").strip().lower() == "failed", recovered_node
    assert "运行句柄缺失" in str(recovered_node.get("failure_reason") or ""), recovered_node
    assert len(self_iter_items) == 1, schedules
    assert str(self_iter_items[0].get("expected_artifact") or "").strip() == "continuous-improvement-report.md", self_iter_items[0]

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "schedule_id": str(self_iter_items[0].get("schedule_id") or "").strip(),
                "schedule_name": str(self_iter_items[0].get("schedule_name") or "").strip(),
                "node_status": str(recovered_node.get("status") or "").strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
