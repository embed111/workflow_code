#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import threading
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root = Path.cwd() / ".test" / "runtime-assignment-dispatch-lock"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(Path("D:/code/AI/J-Agents").resolve()),
                "artifact_root": str(artifact_root),
                "task_artifact_root": str(artifact_root),
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
            "summary": "dispatch lock test",
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
            "node_id": "node-dispatch-lock-test",
            "node_name": "dispatch lock test",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "verify duplicate dispatch is blocked",
            "expected_artifact": "dispatch-lock.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()

    task_path = ws._assignment_graph_record_path(root, ticket_id)
    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    task_record = ws._assignment_read_json(task_path)
    node_record = ws._assignment_read_json(node_path)
    task_record["scheduler_state"] = "running"
    task_record["pause_note"] = ""
    node_record["status"] = "ready"
    node_record["status_text"] = ws._node_status_text("ready")
    ws._assignment_write_json(task_path, task_record)
    ws._assignment_write_json(node_path, node_record)

    original_worker = ws._assignment_execution_worker

    def fake_worker(**_kwargs):
        return

    ws._assignment_execution_worker = fake_worker
    results: list[dict[str, object]] = []
    errors: list[str] = []
    start_gate = threading.Barrier(2)

    def runner() -> None:
        try:
            start_gate.wait(timeout=5)
            result = ws.dispatch_assignment_next(
                root,
                ticket_id_text=ticket_id,
                operator="schedule-worker",
                include_test_data=False,
            )
            results.append(result)
        except Exception as exc:  # pragma: no cover - surfaced by assert below
            errors.append(str(exc))

    threads = [threading.Thread(target=runner, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    ws._assignment_execution_worker = original_worker

    assert not errors, errors
    assert len(results) == 2, results

    dispatch_count = sum(len(list(item.get("dispatched") or [])) for item in results)
    runs = ws._assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id)
    run_ids = [str(item.get("run_id") or "").strip() for item in runs if str(item.get("run_id") or "").strip()]
    audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=20)
    dispatch_audits = [item for item in audits if str(item.get("action") or "").strip() == "dispatch"]
    latest_node = ws._assignment_read_json(node_path)

    assert dispatch_count == 1, results
    assert len(run_ids) == 1, runs
    assert len(dispatch_audits) == 1, dispatch_audits
    assert str(latest_node.get("status") or "").strip().lower() == "running", latest_node

    print(
        json.dumps(
            {
                "ok": True,
                "dispatch_count": dispatch_count,
                "run_ids": run_ids,
                "dispatch_audit_ids": [str(item.get("audit_id") or "").strip() for item in dispatch_audits],
                "latest_node_status": str(latest_node.get("status") or "").strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
