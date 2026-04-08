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

    root = workspace_root / ".test" / "runtime-assignment-run-record-db-sync"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    artifact_root = (root / "artifact-root").resolve()
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(Path("C:/work/J-Agents").resolve()),
                "artifact_root": artifact_root.as_posix(),
                "task_artifact_root": artifact_root.as_posix(),
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
            "agent_search_root": Path("C:/work/J-Agents").resolve(),
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "任务中心全局主图",
            "source_workflow": "workflow-ui",
            "summary": "verify assignment run record db sync",
            "review_mode": "none",
            "external_request_id": "workflow-ui-global-graph-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    conn = ws.connect_db(root)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_registry(agent_id,agent_name,workspace_path,updated_at)
            VALUES (?,?,?,?)
            """,
            ("workflow", "workflow", str(workspace_root), ws.iso_ts(ws.now_local())),
        )
        conn.commit()
    finally:
        conn.close()

    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "run record db sync",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "verify run.json writes are mirrored into assignment_execution_runs",
            "expected_artifact": "continuous-improvement-report.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id

    now_text = ws.iso_ts(ws.now_local())
    run_id = "arun-assignment-run-record-db-sync"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=str(workspace_root),
        status="starting",
        command_summary="verify assignment run record db sync",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="已创建运行批次，等待 provider 启动。",
        latest_event_at=now_text,
        exit_code=0,
        started_at=now_text,
        finished_at="",
        created_at=now_text,
        updated_at=now_text,
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)

    conn = ws.connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT run_id,status,provider_pid,latest_event,latest_event_at,updated_at
            FROM assignment_execution_runs
            WHERE run_id=?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "assignment_execution_runs missing inserted row"
    inserted = dict(row)
    assert str(inserted.get("status") or "").strip().lower() == "starting", inserted
    assert int(inserted.get("provider_pid") or 0) == 0, inserted

    running_at = ws.iso_ts(ws.now_local())
    run_record["status"] = "running"
    run_record["latest_event"] = "Provider 已启动，执行中。"
    run_record["latest_event_at"] = running_at
    run_record["updated_at"] = running_at
    run_record["provider_pid"] = 43210
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)

    conn = ws.connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT status,provider_pid,latest_event,latest_event_at,updated_at
            FROM assignment_execution_runs
            WHERE run_id=?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "assignment_execution_runs missing updated row"
    running = dict(row)
    assert str(running.get("status") or "").strip().lower() == "running", running
    assert int(running.get("provider_pid") or 0) == 43210, running
    assert str(running.get("latest_event") or "").strip() == "Provider 已启动，执行中。", running
    assert str(running.get("latest_event_at") or "").strip() == running_at, running

    finished_at = ws.iso_ts(ws.now_local())
    run_record["status"] = "failed"
    run_record["latest_event"] = "运行句柄缺失或 workflow 已重启，请手动重跑。"
    run_record["latest_event_at"] = finished_at
    run_record["updated_at"] = finished_at
    run_record["finished_at"] = finished_at
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)

    conn = ws.connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT status,provider_pid,latest_event,latest_event_at,finished_at
            FROM assignment_execution_runs
            WHERE run_id=?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "assignment_execution_runs missing finalized row"
    finalized = dict(row)
    assert str(finalized.get("status") or "").strip().lower() == "failed", finalized
    assert int(finalized.get("provider_pid") or 0) == 43210, finalized
    assert str(finalized.get("latest_event") or "").strip() == "运行句柄缺失或 workflow 已重启，请手动重跑。", finalized
    assert str(finalized.get("latest_event_at") or "").strip() == finished_at, finalized
    assert str(finalized.get("finished_at") or "").strip() == finished_at, finalized

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "run_id": run_id,
                "inserted": inserted,
                "running": running,
                "finalized": finalized,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
