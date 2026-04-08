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
    from workflow_app.server.services import schedule_service

    root = workspace_root / ".test" / "runtime-schedule-runtime-persist-repair"
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
            "summary": "verify schedule runtime status persist repair",
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
            ("workflow", "workflow", str(workspace_root), "2026-04-08T00:00:00+08:00"),
        )
        conn.commit()
    finally:
        conn.close()

    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "schedule runtime stale repair",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "verify schedule runtime status can persist stale running repair once",
            "expected_artifact": "continuous-improvement-report.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id

    run_id = "arun-schedule-runtime-persist-repair"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=str(workspace_root),
        status="cancelled",
        command_summary="schedule runtime stale repair",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="检测到运行句柄缺失，已自动结束当前批次。",
        latest_event_at="2026-04-08T12:40:10+08:00",
        exit_code=0,
        started_at="2026-04-08T12:37:21+08:00",
        finished_at="2026-04-08T12:40:10+08:00",
        created_at="2026-04-08T12:37:21+08:00",
        updated_at="2026-04-08T12:40:10+08:00",
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["completed_at"] = ""
    node_payload["failure_reason"] = ""
    node_payload["updated_at"] = "2026-04-08T12:37:21+08:00"
    ws._assignment_write_json(node_path, node_payload)

    first = schedule_service._assignment_runtime_status(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        persist_repair=True,
    )
    repaired_node = ws._assignment_read_json(node_path)
    first_audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=16)
    first_recover_count = sum(
        1
        for item in list(first_audits or [])
        if str(item.get("action") or "").strip().lower() == "recover_stale_running"
    )

    second = schedule_service._assignment_runtime_status(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        persist_repair=True,
    )
    second_audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=16)
    second_recover_count = sum(
        1
        for item in list(second_audits or [])
        if str(item.get("action") or "").strip().lower() == "recover_stale_running"
    )

    assert first.get("assignment_status") == "failed", first
    assert first.get("result_status") == "failed", first
    assert second.get("assignment_status") == "failed", second
    assert str(repaired_node.get("status") or "").strip().lower() == "failed", repaired_node
    assert "运行句柄缺失" in str(repaired_node.get("failure_reason") or ""), repaired_node
    assert first_recover_count == 1, first_audits
    assert second_recover_count == 1, second_audits

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "first": first,
                "second": second,
                "repaired_node_status": str(repaired_node.get("status") or "").strip(),
                "recover_stale_running_audit_count": second_recover_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
