#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root = workspace_root / ".test" / "runtime-pm-parallel-assign-thread-mode"
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
            "graph_name": "pm-parallel-assign-thread-mode",
            "source_workflow": "test",
            "summary": "verify pm-parallel-assign non daemon",
            "review_mode": "none",
            "external_request_id": "pm-parallel-assign-thread-mode-v1",
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
            ("workflow_devmate", "workflow_devmate", str(workspace_root), "2026-04-07T00:00:00+08:00"),
        )
        conn.commit()
    finally:
        conn.close()
    ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "pm parallel assign node",
            "assigned_agent_id": "workflow_devmate",
            "priority": "P1",
            "node_goal": "verify pm-parallel-assign thread mode",
            "expected_artifact": "pm-parallel-assign-thread-mode.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    task_record = ws._assignment_load_task_record(root, ticket_id)
    node_records = ws._assignment_load_node_records(root, ticket_id, include_deleted=True)
    task_record["scheduler_state"] = "running"
    task_record["updated_at"] = ws.iso_ts(ws.now_local())
    ws._assignment_store_snapshot(root, task_record=task_record, node_records=node_records)

    marker_path = root / "pm-parallel-assign-marker.txt"
    child_code = f"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, {str(src_root)!r})
from workflow_app.server.bootstrap import web_server_runtime as ws

marker = Path({str(marker_path)!r})
dispatch_globals = ws.dispatch_assignment_next.__globals__

def fake_worker(**kwargs):
    time.sleep(0.5)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('worker-ran', encoding='utf-8')

original = dispatch_globals['_assignment_execution_worker_guarded']
dispatch_globals['_assignment_execution_worker_guarded'] = fake_worker
try:
    result = ws.dispatch_assignment_next(
        Path({str(root)!r}),
        ticket_id_text={ticket_id!r},
        operator='pm-parallel-assign',
        include_test_data=False,
    )
    print(json.dumps(result, ensure_ascii=False))
finally:
    dispatch_globals['_assignment_execution_worker_guarded'] = original
"""

    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", child_code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    elapsed_s = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"child failed: {completed.returncode} stdout={completed.stdout} stderr={completed.stderr}"
        )

    assert marker_path.exists(), {"stdout": completed.stdout, "stderr": completed.stderr}
    assert elapsed_s >= 0.45, elapsed_s
    assert ws._assignment_execution_thread_should_daemon("pm-parallel-assign") is False
    assert ws._assignment_execution_thread_should_daemon("pm-manual-recovery") is False
    assert ws._assignment_execution_thread_should_daemon("schedule-worker") is True

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "marker_path": marker_path.as_posix(),
                "elapsed_seconds": round(elapsed_s, 3),
                "child_stdout": completed.stdout.strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
