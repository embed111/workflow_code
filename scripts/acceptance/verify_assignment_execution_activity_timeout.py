#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _build_cfg(root: Path, agent_root: Path):
    return type(
        "Cfg",
        (),
        {
            "root": root,
            "agent_search_root": agent_root,
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()


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


def _create_root(ws, workspace_root: Path, root_name: str) -> tuple[Path, Path]:
    root = workspace_root / ".test" / root_name
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
    agent_root = (root / "agents").resolve()
    agent_root.mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": agent_root.as_posix(),
                "artifact_root": artifact_root.as_posix(),
                "task_artifact_root": artifact_root.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root, agent_root


def _seed_running_node(ws, root: Path, *, ticket_id: str, node_id: str, now_text: str) -> None:
    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = now_text
    ws._assignment_write_json(node_path, node_payload)


def _run_probe(
    ws,
    root: Path,
    *,
    graph_name: str,
    external_request_id: str,
    node_name: str,
    command: list[str],
) -> tuple[dict, dict, dict]:
    agent_id = "workflow"
    agent_workspace = (root / "agents" / agent_id).resolve()
    agent_workspace.mkdir(parents=True, exist_ok=True)
    cfg = _build_cfg(root, root / "agents")
    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": graph_name,
            "source_workflow": "test",
            "summary": "verify assignment execution timeout policy",
            "review_mode": "none",
            "external_request_id": external_request_id,
            "operator": "test",
        },
    )
    _register_agent(ws, root, agent_id=agent_id, agent_workspace=agent_workspace)
    ticket_id = str(graph.get("ticket_id") or "").strip()
    node = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": node_name,
            "assigned_agent_id": agent_id,
            "priority": "P1",
            "node_goal": "verify assignment execution timeout policy",
            "expected_artifact": "timeout-policy.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((node.get("node") or {}).get("node_id") or "").strip()
    now_text = ws.iso_ts(ws.now_local())
    prep = ws._prepare_assignment_execution_run(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        now_text=now_text,
    )
    _seed_running_node(ws, root, ticket_id=ticket_id, node_id=node_id, now_text=now_text)
    ws._assignment_execution_worker(
        root,
        run_id=str(prep.get("run_id") or "").strip(),
        ticket_id=ticket_id,
        node_id=node_id,
        workspace_path=Path(prep.get("workspace_path") or agent_workspace),
        command=command,
        command_summary="acceptance timeout probe",
        prompt_text="timeout probe",
    )
    run_record = ws._assignment_load_run_record(
        root,
        ticket_id=ticket_id,
        run_id=str(prep.get("run_id") or "").strip(),
    )
    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    result_payload = ws._assignment_read_json(ws._assignment_run_file_paths(root, ticket_id, str(prep.get("run_id") or "").strip())["result"])
    return run_record, node_payload, result_payload


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root, _agent_root = _create_root(ws, workspace_root, "runtime-assignment-execution-activity-timeout")
    assert int(ws.DEFAULT_ASSIGNMENT_EXECUTION_TIMEOUT_S) >= 7200, ws.DEFAULT_ASSIGNMENT_EXECUTION_TIMEOUT_S

    worker_globals = ws._assignment_execution_worker.__globals__
    original_timeout = worker_globals["_assignment_execution_timeout_s"]
    original_activity_timeout = worker_globals["_assignment_execution_activity_timeout_s"]
    worker_globals["_assignment_execution_timeout_s"] = lambda: 1
    worker_globals["_assignment_execution_activity_timeout_s"] = lambda: 1
    try:
        heartbeat_script = "\n".join(
            [
                "import json",
                "import time",
                "print('heartbeat-1', flush=True)",
                "time.sleep(0.6)",
                "print('heartbeat-2', flush=True)",
                "time.sleep(0.6)",
                "print(json.dumps({'result_summary':'heartbeat probe succeeded','artifact_label':'timeout-policy.md','artifact_markdown':'heartbeat ok','artifact_files':[],'warnings':[]}), flush=True)",
            ]
        )
        silent_script = "\n".join(
            [
                "import json",
                "import time",
                "time.sleep(3.0)",
                "print(json.dumps({'result_summary':'silent probe succeeded','artifact_label':'timeout-policy.md','artifact_markdown':'silent ok','artifact_files':[],'warnings':[]}), flush=True)",
            ]
        )

        heartbeat_run, heartbeat_node, heartbeat_result = _run_probe(
            ws,
            root,
            graph_name="assignment-activity-timeout-heartbeat",
            external_request_id="assignment-activity-timeout-heartbeat",
            node_name="heartbeat timeout probe",
            command=[sys.executable, "-c", heartbeat_script],
        )
        silent_run, silent_node, silent_result = _run_probe(
            ws,
            root,
            graph_name="assignment-activity-timeout-silent",
            external_request_id="assignment-activity-timeout-silent",
            node_name="silent timeout probe",
            command=[sys.executable, "-c", silent_script],
        )
    finally:
        worker_globals["_assignment_execution_timeout_s"] = original_timeout
        worker_globals["_assignment_execution_activity_timeout_s"] = original_activity_timeout

    assert str(heartbeat_run.get("status") or "").strip().lower() == "succeeded", heartbeat_run
    assert str(heartbeat_node.get("status") or "").strip().lower() == "succeeded", heartbeat_node
    assert "heartbeat probe succeeded" in str(heartbeat_result.get("result_summary") or ""), heartbeat_result

    assert str(silent_run.get("status") or "").strip().lower() == "failed", silent_run
    assert str(silent_node.get("status") or "").strip().lower() == "failed", silent_node
    assert "without progress" in str(silent_run.get("latest_event") or ""), silent_run
    assert "without progress" in str(silent_result.get("result_summary") or ""), silent_result

    print(
        json.dumps(
            {
                "ok": True,
                "heartbeat_run_status": heartbeat_run.get("status"),
                "heartbeat_result_summary": heartbeat_result.get("result_summary"),
                "silent_run_status": silent_run.get("status"),
                "silent_latest_event": silent_run.get("latest_event"),
                "silent_codex_failure_code": ((silent_run.get("codex_failure") or {}).get("failure_detail_code") or ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
