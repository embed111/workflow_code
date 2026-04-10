#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
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
                "2026-04-10T00:00:00+08:00",
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

    root = workspace_root / ".test" / "runtime-stale-failure-context"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
    agent_root = (root / "agents").resolve()
    agent_workspace = (agent_root / "workflow").resolve()
    agent_workspace.mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": True,
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
    cfg = type(
        "Cfg",
        (),
        {
            "root": root,
            "agent_search_root": agent_root,
            "show_test_data": True,
        },
    )()

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "assignment-stale-failure-context",
            "source_workflow": "workflow-ui",
            "summary": "verify stale recovery preserves failure context from traces",
            "review_mode": "none",
            "external_request_id": "assignment-stale-failure-context-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    _register_agent(ws, root, agent_id="workflow", agent_workspace=agent_workspace)
    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "stale failure context",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "preserve meaningful stale failure context",
            "expected_artifact": "stale-failure-context.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=True,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id

    run_id = "arun-stale-failure-context"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=agent_workspace.as_posix(),
        status="running",
        command_summary="stale failure context",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="Provider 已启动，执行中。",
        latest_event_at="2026-04-10T13:00:00+08:00",
        exit_code=0,
        started_at="2026-04-10T13:00:00+08:00",
        finished_at="",
        created_at="2026-04-10T13:00:00+08:00",
        updated_at="2026-04-10T13:00:00+08:00",
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    ws._write_assignment_run_text(files["prompt"], "test prompt")
    ws._write_assignment_run_text(files["stdout"], '{"type":"turn.started"}\n')
    ws._write_assignment_run_text(
        files["stderr"],
        "\n".join(
            [
                "[2026-04-10T14:34:31+08:00] 环境 test 当前正在运行（PID=10944），请先停止后再部署。",
                "[2026-04-10T14:35:08+08:00] Invoke-RestMethod : 无法连接到远程服务器",
                "[2026-04-10T14:35:08+08:00] At line:2 char:1",
                "",
            ]
        ),
    )

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = "2026-04-10T13:00:00+08:00"
    ws._assignment_write_json(node_path, node_payload)

    ws.get_assignment_graph(
        root,
        ticket_id,
        include_test_data=True,
        active_batch_size=20,
        history_batch_size=20,
    )

    recovered_run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    recovered_node = ws._assignment_read_json(node_path)
    audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=16)
    recover_audit = next(
        (
            item
            for item in list(audits or [])
            if str(item.get("action") or "").strip().lower() == "recover_stale_running"
        ),
        {},
    )

    failure_reason = str(recovered_node.get("failure_reason") or "").strip()
    latest_event = str(recovered_run.get("latest_event") or "").strip()
    preserved_detail = dict((recover_audit.get("detail") or {}).get("preserved_failure_context") or {})

    assert str(recovered_run.get("status") or "").strip().lower() == "cancelled", recovered_run
    assert str(recovered_node.get("status") or "").strip().lower() == "failed", recovered_node
    assert "无法连接到远程服务器" in failure_reason, recovered_node
    assert "运行句柄缺失" not in failure_reason, recovered_node
    assert "最近失败线索" in latest_event, recovered_run
    assert "无法连接到远程服务器" in latest_event, recovered_run
    assert preserved_detail.get("source") == "stderr", recover_audit
    assert preserved_detail.get("run_id") == run_id, recover_audit
    assert "stderr.txt" in str(preserved_detail.get("evidence_ref") or ""), recover_audit

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "run_id": run_id,
                "failure_reason": failure_reason,
                "latest_event": latest_event,
                "preserved_failure_context": preserved_detail,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
