#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path


def _register_agent(ws, root: Path, *, agent_id: str, agent_workspace: Path) -> None:
    conn = ws.connect_db(root)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_registry(agent_id,agent_name,workspace_path,updated_at)
            VALUES (?,?,?,?)
            """,
            (
                agent_id,
                agent_id,
                agent_workspace.as_posix(),
                "2026-04-08T00:00:00+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root = Path.cwd() / ".test" / "runtime-dispatch-stale-recovery"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": True,
                "agent_search_root": str((root / "agents").resolve()),
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
            "agent_search_root": (root / "agents").resolve(),
            "show_test_data": True,
            "runtime_environment": "prod",
        },
    )()

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "任务中心全局主图",
            "source_workflow": "workflow-ui",
            "summary": "verify dispatch survives stale recovery",
            "review_mode": "none",
            "external_request_id": "workflow-ui-global-graph-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    assert ticket_id

    workflow_workspace = (root / "agents" / "workflow").resolve()
    quality_workspace = (root / "agents" / "workflow_qualitymate").resolve()
    workflow_workspace.mkdir(parents=True, exist_ok=True)
    quality_workspace.mkdir(parents=True, exist_ok=True)
    _register_agent(ws, root, agent_id="workflow", agent_workspace=workflow_workspace)
    _register_agent(ws, root, agent_id="workflow_qualitymate", agent_workspace=quality_workspace)

    ready_created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "ready workflow node",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "dispatch after stale recovery",
            "expected_artifact": "continuous-improvement-report.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=True,
    )
    ready_node_id = str((ready_created.get("node") or {}).get("node_id") or "").strip()
    assert ready_node_id

    stale_created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "stale quality node",
            "assigned_agent_id": "workflow_qualitymate",
            "priority": "P1",
            "node_goal": "stale running node with final artifacts",
            "expected_artifact": "quality-report.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=True,
    )
    stale_node_id = str((stale_created.get("node") or {}).get("node_id") or "").strip()
    assert stale_node_id

    stale_run_id = "arun-stale-dispatch-recovery"
    stale_files = ws._assignment_run_file_paths(root, ticket_id, stale_run_id)
    stale_files["trace_dir"].mkdir(parents=True, exist_ok=True)
    stale_run = ws._assignment_build_run_record(
        run_id=stale_run_id,
        ticket_id=ticket_id,
        node_id=stale_node_id,
        provider="codex",
        workspace_path=str(quality_workspace),
        status="running",
        command_summary="stale quality node",
        prompt_ref=stale_files["prompt"].as_posix(),
        stdout_ref=stale_files["stdout"].as_posix(),
        stderr_ref=stale_files["stderr"].as_posix(),
        result_ref=stale_files["result"].as_posix(),
        latest_event="turn.started",
        latest_event_at="2026-04-08T00:00:00+08:00",
        exit_code=0,
        started_at="2026-04-08T00:00:00+08:00",
        finished_at="",
        created_at="2026-04-08T00:00:00+08:00",
        updated_at="2026-04-08T00:00:00+08:00",
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=stale_run)
    ws._write_assignment_run_text(stale_files["prompt"], "stale prompt")
    ws._write_assignment_run_text(stale_files["stdout"], '{"type":"turn.started"}\n')
    ws._write_assignment_run_text(stale_files["stderr"], "")
    ws._write_assignment_run_json(
        stale_files["result"],
        {
            "result_summary": "stale quality result",
            "artifact_label": "quality-report.md",
            "artifact_markdown": "stale quality result",
            "artifact_files": [],
            "warnings": [],
        },
    )
    ws._append_assignment_run_event(
        stale_files["events"],
        event_type="final_result",
        message="stale quality result",
        created_at="2026-04-08T00:00:05+08:00",
        detail={"exit_code": 0},
    )

    stale_node_path = ws._assignment_node_record_path(root, ticket_id, stale_node_id)
    stale_node = ws._assignment_read_json(stale_node_path)
    stale_node["status"] = "running"
    stale_node["status_text"] = "进行中"
    stale_node["updated_at"] = "2026-04-08T00:00:00+08:00"
    ws._assignment_write_json(stale_node_path, stale_node)

    task_path = ws._assignment_graph_record_path(root, ticket_id)
    task_payload = ws._assignment_read_json(task_path)
    task_payload["scheduler_state"] = "running"
    task_payload["updated_at"] = "2026-04-08T00:00:00+08:00"
    ws._assignment_write_json(task_path, task_payload)

    original_worker = ws._assignment_execution_worker_guarded
    started_runs: list[dict[str, str]] = []

    def fake_worker(**kwargs):
        started_runs.append(
            {
                "run_id": str(kwargs.get("run_id") or "").strip(),
                "node_id": str(kwargs.get("node_id") or "").strip(),
            }
        )

    ws._assignment_execution_worker_guarded = fake_worker
    try:
        started_at = time.monotonic()
        dispatch_result = ws.dispatch_assignment_next(
            root,
            ticket_id_text=ticket_id,
            operator="schedule-worker",
            include_test_data=True,
        )
        elapsed_seconds = time.monotonic() - started_at
    finally:
        ws._assignment_execution_worker_guarded = original_worker

    recovered_stale_node = ws._assignment_read_json(stale_node_path)
    ready_node_path = ws._assignment_node_record_path(root, ticket_id, ready_node_id)
    ready_node = ws._assignment_read_json(ready_node_path)
    followup_audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=stale_node_id, limit=16)

    assert elapsed_seconds < 5.0, elapsed_seconds
    assert any(str(item.get("node_id") or "").strip() == ready_node_id for item in list(dispatch_result.get("dispatched") or [])), dispatch_result
    assert any(str(item.get("node_id") or "").strip() == ready_node_id for item in list(dispatch_result.get("dispatched_runs") or [])), dispatch_result
    assert str(ready_node.get("status") or "").strip().lower() == "running", ready_node
    assert str(recovered_stale_node.get("status") or "").strip().lower() == "succeeded", recovered_stale_node
    assert not any(str(item.get("action") or "").strip() == "followup_dispatch_failed" for item in followup_audits), followup_audits

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "ready_node_id": ready_node_id,
                "stale_node_id": stale_node_id,
                "elapsed_seconds": round(elapsed_seconds, 3),
                "started_runs": started_runs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
