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

    root = Path.cwd() / ".test" / "runtime-stale-run-recovery"
    if root.exists():
        import shutil

        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": True,
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
            "show_test_data": True,
        },
    )()

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "stale-run-recovery",
            "source_workflow": "workflow-ui",
            "summary": "verify stale run recovery",
            "review_mode": "none",
            "external_request_id": "stale-run-recovery",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "recover stale run",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "recover stale run from result artifacts",
            "expected_artifact": "recovery.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=True,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id

    # Manually seed a stale in-flight run that already has final artifacts on disk.
    run_id = "arun-test-stale-recovery"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=str(workspace_root),
        status="running",
        command_summary="test stale run",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="turn.started",
        latest_event_at="2026-04-06T01:00:00+08:00",
        exit_code=0,
        started_at="2026-04-06T01:00:00+08:00",
        finished_at="",
        created_at="2026-04-06T01:00:00+08:00",
        updated_at="2026-04-06T01:00:00+08:00",
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    ws._write_assignment_run_text(files["prompt"], "test prompt")
    ws._write_assignment_run_text(files["stdout"], '{"type":"turn.started"}\n')
    ws._write_assignment_run_text(files["stderr"], "")
    ws._write_assignment_run_json(
        files["result"],
        {
            "result_summary": "assignment execution failed with exit=1",
            "artifact_label": "recover stale run",
            "artifact_markdown": "assignment execution failed with exit=1",
            "artifact_files": [],
            "warnings": [],
        },
    )
    ws._append_assignment_run_event(
        files["events"],
        event_type="final_result",
        message="assignment execution failed with exit=1",
        created_at="2026-04-06T01:00:05+08:00",
        detail={"exit_code": 1},
    )

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = "2026-04-06T01:00:00+08:00"
    ws._assignment_write_json(node_path, node_payload)

    # Trigger reconciliation via a read path.
    ws.get_assignment_graph(
        root,
        ticket_id,
        include_test_data=True,
        active_batch_size=20,
        history_batch_size=20,
    )

    recovered_run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    recovered_node = ws._assignment_read_json(node_path)

    assert str(recovered_run.get("status") or "").strip().lower() == "failed", recovered_run
    assert str(recovered_node.get("status") or "").strip().lower() == "failed", recovered_node
    assert "exit=1" in str(recovered_run.get("latest_event") or ""), recovered_run

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "run_id": run_id,
                "run_status": recovered_run.get("status"),
                "node_status": recovered_node.get("status"),
                "latest_event": recovered_run.get("latest_event"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
