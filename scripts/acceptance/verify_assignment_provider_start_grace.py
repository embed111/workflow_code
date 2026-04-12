#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root = Path.cwd() / ".test" / "runtime-provider-start-grace"
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
            "graph_name": "provider-start-grace",
            "source_workflow": "workflow-ui",
            "summary": "verify provider start grace",
            "review_mode": "none",
            "external_request_id": "provider-start-grace",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "keep starting run alive",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "keep provider start grace alive",
            "expected_artifact": "provider-start-grace.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=True,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id

    now_dt = ws.now_local()
    dispatch_at = ws.iso_ts(now_dt - timedelta(seconds=90))

    run_id = "arun-test-provider-start-grace"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=str(workspace_root),
        status="starting",
        command_summary="test provider start grace",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="已创建运行批次，等待 provider 启动。",
        latest_event_at=dispatch_at,
        exit_code=0,
        started_at=dispatch_at,
        finished_at="",
        created_at=dispatch_at,
        updated_at=dispatch_at,
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    ws._write_assignment_run_text(files["prompt"], "test prompt")
    ws._write_assignment_run_text(files["stdout"], "")
    ws._write_assignment_run_text(files["stderr"], "")
    ws._write_assignment_run_text(files["events"], "")
    ws._append_assignment_run_event(
        files["events"],
        event_type="dispatch",
        message="调度器已创建真实执行批次。",
        created_at=dispatch_at,
        detail={},
    )

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = dispatch_at
    ws._assignment_write_json(node_path, node_payload)

    ws.get_assignment_graph(
        root,
        ticket_id,
        include_test_data=True,
        active_batch_size=20,
        history_batch_size=20,
    )

    refreshed_run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    refreshed_node = ws._assignment_read_json(node_path)

    assert str(refreshed_run.get("status") or "").strip().lower() == "starting", refreshed_run
    assert str(refreshed_node.get("status") or "").strip().lower() == "running", refreshed_node

    finalizing_run_id = "arun-test-provider-finalizing-grace"
    finalizing_node_id = "node-provider-finalizing-grace"
    finalizing_files = ws._assignment_run_file_paths(root, ticket_id, finalizing_run_id)
    finalizing_files["trace_dir"].mkdir(parents=True, exist_ok=True)
    finalizing_at = ws.iso_ts(now_dt - timedelta(seconds=90))
    finalizing_run_record = ws._assignment_build_run_record(
        run_id=finalizing_run_id,
        ticket_id=ticket_id,
        node_id=finalizing_node_id,
        provider="codex",
        workspace_path=str(workspace_root),
        status="running",
        command_summary="test provider finalizing grace",
        prompt_ref=finalizing_files["prompt"].as_posix(),
        stdout_ref=finalizing_files["stdout"].as_posix(),
        stderr_ref=finalizing_files["stderr"].as_posix(),
        result_ref=finalizing_files["result"].as_posix(),
        latest_event="Provider 已退出，正在整理结果。",
        latest_event_at=finalizing_at,
        exit_code=0,
        started_at=dispatch_at,
        finished_at="",
        created_at=dispatch_at,
        updated_at=finalizing_at,
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=finalizing_run_record)
    finalizing_node_payload = dict(node_payload)
    finalizing_node_payload["node_id"] = finalizing_node_id
    finalizing_node_payload["node_name"] = "keep finalizing run alive"
    finalizing_node_payload["status"] = "running"
    finalizing_node_payload["status_text"] = "进行中"
    finalizing_node_payload["updated_at"] = finalizing_at
    ws._assignment_write_json(ws._assignment_node_record_path(root, ticket_id, finalizing_node_id), finalizing_node_payload)

    finalizing_graph = ws.get_assignment_graph(
        root,
        ticket_id,
        include_test_data=True,
        active_batch_size=20,
        history_batch_size=20,
    )
    refreshed_finalizing_run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=finalizing_run_id)
    finalizing_nodes = list(finalizing_graph.get("nodes") or [])
    refreshed_finalizing_node = next(
        (item for item in finalizing_nodes if str((item or {}).get("node_id") or "").strip() == finalizing_node_id),
        {},
    )

    assert str(refreshed_finalizing_run.get("status") or "").strip().lower() == "running", refreshed_finalizing_run
    assert str(refreshed_finalizing_run.get("provider_pid") or "").strip() in {"", "0"}, refreshed_finalizing_run
    assert str(refreshed_finalizing_node.get("status") or "").strip().lower() == "running", refreshed_finalizing_node

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "run_id": run_id,
                "run_status": refreshed_run.get("status"),
                "node_status": refreshed_node.get("status"),
                "latest_event": refreshed_run.get("latest_event"),
                "latest_event_at": refreshed_run.get("latest_event_at"),
                "finalizing_run_id": finalizing_run_id,
                "finalizing_run_status": refreshed_finalizing_run.get("status"),
                "finalizing_node_id": finalizing_node_id,
                "finalizing_node_status": refreshed_finalizing_node.get("status"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
