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

    root = workspace_root / ".test" / "runtime-worker-guarded-fail-closed"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(workspace_root.resolve()),
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
            "agent_search_root": workspace_root.resolve(),
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "worker-guard-test",
            "source_workflow": "test",
            "summary": "verify worker guarded fail closed",
            "review_mode": "none",
            "external_request_id": "worker-guard-test-v1",
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
            ("workflow", "workflow", str(workspace_root), "2026-04-07T00:00:00+08:00"),
        )
        conn.commit()
    finally:
        conn.close()
    node = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "worker guard node",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "verify worker guarded fail closed",
            "expected_artifact": "guarded-fail-closed.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((node.get("node") or {}).get("node_id") or "").strip()
    prep = ws._prepare_assignment_execution_run(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        now_text=ws.iso_ts(ws.now_local()),
    )

    guard_globals = ws._assignment_execution_worker_guarded.__globals__
    original_worker = guard_globals["_assignment_execution_worker"]
    try:
        def _boom(*args, **kwargs):
            raise RuntimeError("boom before provider_start")

        guard_globals["_assignment_execution_worker"] = _boom
        ws._assignment_execution_worker_guarded(
            root,
            run_id=str(prep.get("run_id") or "").strip(),
            ticket_id=ticket_id,
            node_id=node_id,
            workspace_path=prep.get("workspace_path"),
            command=list(prep.get("command") or []),
            command_summary=str(prep.get("command_summary") or "").strip(),
            prompt_text=str(prep.get("prompt_text") or ""),
            operator="test",
        )
    finally:
        guard_globals["_assignment_execution_worker"] = original_worker

    run_id = str(prep.get("run_id") or "").strip()
    run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    node_payload = ws._assignment_read_json(ws._assignment_node_record_path(root, ticket_id, node_id))
    events = ws._tail_assignment_run_events(prep.get("files", {}).get("events"), limit=20)

    assert str(run.get("status") or "").strip().lower() == "failed", run
    assert "bootstrap failed" in str(run.get("latest_event") or "").strip().lower(), run
    assert str(node_payload.get("status") or "").strip().lower() == "failed", node_payload
    assert any(str(item.get("event_type") or "").strip() == "provider_start_failed" for item in events), events

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "run_id": run_id,
                "event_types": [str(item.get("event_type") or "") for item in events],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
