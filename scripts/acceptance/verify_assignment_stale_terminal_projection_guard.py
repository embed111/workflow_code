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
            "show_test_data": True,
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


def _create_root(workspace_root: Path) -> tuple[Path, Path]:
    root = workspace_root / ".test" / "runtime-stale-terminal-projection-guard"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
    agent_root = (root / "agents").resolve()
    agent_root.mkdir(parents=True, exist_ok=True)
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
    return root, agent_root


def _seed_case(
    ws,
    root: Path,
    cfg,
    *,
    suffix: str,
    run_status: str,
    exit_code: int,
    latest_event: str,
    result_summary: str,
) -> dict[str, object]:
    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": f"stale-terminal-projection-{suffix}",
            "source_workflow": "workflow-ui",
            "summary": f"verify stale terminal projection guard {suffix}",
            "review_mode": "none",
            "external_request_id": f"stale-terminal-projection-{suffix}",
            "operator": "test",
        },
    )
    agent_workspace = (root / "agents" / "workflow").resolve()
    agent_workspace.mkdir(parents=True, exist_ok=True)
    _register_agent(ws, root, agent_id="workflow", agent_workspace=agent_workspace)
    ticket_id = str(graph.get("ticket_id") or "").strip()
    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": f"stale terminal projection {suffix}",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": f"verify stale terminal projection {suffix}",
            "expected_artifact": f"{suffix}.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=True,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id

    run_id = f"arun-{suffix}"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=str(workspace_root),
        status=run_status,
        command_summary=f"stale terminal projection {suffix}",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event=latest_event,
        latest_event_at="2026-04-08T19:00:05+08:00",
        exit_code=exit_code,
        started_at="2026-04-08T19:00:00+08:00",
        finished_at="2026-04-08T19:00:05+08:00",
        created_at="2026-04-08T19:00:00+08:00",
        updated_at="2026-04-08T19:00:05+08:00",
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    ws._write_assignment_run_text(files["prompt"], f"{suffix} prompt")
    ws._write_assignment_run_text(files["stdout"], "")
    ws._write_assignment_run_text(files["stderr"], "")
    ws._write_assignment_run_json(
        files["result"],
        {
            "result_summary": result_summary,
            "artifact_label": f"{suffix}.md",
            "artifact_markdown": result_summary,
            "artifact_files": [],
            "warnings": [],
        },
    )
    ws._append_assignment_run_event(
        files["events"],
        event_type="final_result",
        message=latest_event,
        created_at="2026-04-08T19:00:05+08:00",
        detail={"exit_code": exit_code},
    )

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = "2026-04-08T19:00:00+08:00"
    ws._assignment_write_json(node_path, node_payload)

    ws.get_assignment_graph(
        root,
        ticket_id,
        include_test_data=True,
        active_batch_size=20,
        history_batch_size=20,
    )

    recovered_node = ws._assignment_read_json(node_path)
    audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=16)
    audit_actions = [str(item.get("action") or "").strip().lower() for item in list(audits or [])]
    return {
        "ticket_id": ticket_id,
        "node_id": node_id,
        "run_id": run_id,
        "result_ref": files["result"].as_posix(),
        "node": recovered_node,
        "audit_actions": audit_actions,
    }


def main() -> int:
    global workspace_root
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root, agent_root = _create_root(workspace_root)
    cfg = _build_cfg(root, agent_root)

    failed_case = _seed_case(
        ws,
        root,
        cfg,
        suffix="terminal-failed",
        run_status="failed",
        exit_code=1,
        latest_event="assignment execution failed with exit=1；已保留结构化结果：terminal failed summary",
        result_summary="terminal failed summary",
    )
    succeeded_case = _seed_case(
        ws,
        root,
        cfg,
        suffix="terminal-succeeded",
        run_status="succeeded",
        exit_code=0,
        latest_event="执行完成并已自动回写结果。",
        result_summary="terminal succeeded summary",
    )

    failed_node = dict(failed_case["node"] or {})
    failed_actions = list(failed_case["audit_actions"] or [])
    assert str(failed_node.get("status") or "").strip().lower() == "failed", failed_node
    assert "运行句柄缺失" not in str(failed_node.get("failure_reason") or ""), failed_node
    assert "exit=1" in str(failed_node.get("failure_reason") or ""), failed_node
    assert str(failed_node.get("result_ref") or "").strip() == str(failed_case["result_ref"]), failed_node
    assert "recover_stale_running" not in failed_actions, failed_actions

    succeeded_node = dict(succeeded_case["node"] or {})
    succeeded_actions = list(succeeded_case["audit_actions"] or [])
    assert str(succeeded_node.get("status") or "").strip().lower() == "succeeded", succeeded_node
    assert "terminal succeeded summary" in str(succeeded_node.get("success_reason") or ""), succeeded_node
    assert str(succeeded_node.get("result_ref") or "").strip() == str(succeeded_case["result_ref"]), succeeded_node
    assert str(succeeded_node.get("failure_reason") or "").strip() == "", succeeded_node
    assert "recover_stale_running" not in succeeded_actions, succeeded_actions

    print(
        json.dumps(
            {
                "ok": True,
                "failed_node_status": failed_node.get("status"),
                "failed_node_result_ref": failed_node.get("result_ref"),
                "succeeded_node_status": succeeded_node.get("status"),
                "succeeded_node_result_ref": succeeded_node.get("result_ref"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
