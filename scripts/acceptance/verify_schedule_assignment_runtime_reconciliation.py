#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime  # noqa: F401
    from workflow_app.server.services import assignment_service, schedule_service

    root = Path.cwd() / ".test" / "runtime-schedule-assignment-reconcile"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
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
    cfg = type("Cfg", (), {"root": root, "runtime_environment": "prod"})()

    original_list_agents = assignment_service.list_available_agents
    assignment_service.list_available_agents = lambda _cfg: [{"agent_id": "workflow", "agent_name": "workflow"}]
    try:
        created = assignment_service.create_assignment_graph(
            cfg,
            {
                "operator": "test",
                "graph_name": "任务中心全局主图",
                "source_workflow": "schedule-reconcile-probe",
                "summary": "verify schedule helper reconciles live runs",
                "review_mode": "none",
                "external_request_id": "schedule-reconcile-probe",
            },
        )
        ticket_id = str(created.get("ticket_id") or "").strip()
        if not ticket_id:
            raise RuntimeError("ticket_id missing")
        for node_id, node_name in (
            ("node-live-stale", "stale node with live run"),
            ("node-ready-check", "ready node waiting slot"),
        ):
            assignment_service.create_assignment_node(
                cfg,
                ticket_id,
                {
                    "operator": "test",
                    "node_id": node_id,
                    "node_name": node_name,
                    "assigned_agent_id": "workflow",
                    "priority": "P1",
                    "node_goal": "verify schedule runtime reconciliation",
                    "expected_artifact": "probe-report",
                    "delivery_mode": "none",
                },
                include_test_data=True,
            )
    finally:
        assignment_service.list_available_agents = original_list_agents

    now_text = _now_text()
    assignment_service._assignment_write_run_record(
        root,
        ticket_id=ticket_id,
        run_record={
            "record_type": "assignment_run",
            "schema_version": 1,
            "run_id": "arun-live-reconcile-0001",
            "ticket_id": ticket_id,
            "node_id": "node-live-stale",
            "provider": "codex",
            "workspace_path": root.as_posix(),
            "status": "running",
            "command_summary": "probe",
            "prompt_ref": "",
            "stdout_ref": "",
            "stderr_ref": "",
            "result_ref": "",
            "latest_event": "provider_start",
            "latest_event_at": now_text,
            "exit_code": 0,
            "started_at": now_text,
            "finished_at": "",
            "created_at": now_text,
            "updated_at": now_text,
            "provider_pid": 0,
            "codex_failure": {},
        },
        sync_index=True,
    )

    live_status = schedule_service._assignment_runtime_status(
        root,
        ticket_id=ticket_id,
        node_id="node-live-stale",
    )
    ready_status = schedule_service._assignment_runtime_status(
        root,
        ticket_id=ticket_id,
        node_id="node-ready-check",
    )
    other_running = schedule_service._assignment_ticket_has_other_running_nodes(
        root,
        ticket_id=ticket_id,
        exclude_node_id="node-ready-check",
    )

    assert str(live_status.get("result_status") or "") == "running", live_status
    assert str(live_status.get("assignment_status") or "") == "running", live_status
    assert str(ready_status.get("result_status") or "") == "queued", ready_status
    assert bool(other_running), {
        "ticket_id": ticket_id,
        "live_status": live_status,
        "ready_status": ready_status,
    }

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "live_status": live_status,
                "ready_status": ready_status,
                "other_running": other_running,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
