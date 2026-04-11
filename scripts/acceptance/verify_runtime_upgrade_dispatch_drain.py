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
    from workflow_app.server.services import runtime_upgrade_service

    root = workspace_root / ".test" / "runtime-upgrade-dispatch-drain"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(Path("D:/code/AI/J-Agents").resolve()),
                "artifact_root": artifact_root.as_posix(),
                "task_artifact_root": artifact_root.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate_root = (root / "candidate-app").resolve()
    candidate_root.mkdir(parents=True, exist_ok=True)
    evidence_path = (root / "candidate-evidence.md").resolve()
    evidence_path.write_text("# candidate evidence\n", encoding="utf-8")
    snapshot = {
        "environment": "prod",
        "current_version": "20260411-214605",
        "current_version_rank": "20260411-214605",
        "candidate": {
            "version": "20260411-220013",
            "version_rank": "20260411-220013",
            "candidate_app_root": candidate_root.as_posix(),
            "evidence_path": evidence_path.as_posix(),
        },
        "upgrade_request": {},
        "last_action": {},
    }
    drain_status = runtime_upgrade_service.runtime_upgrade_drain_state(snapshot)
    status_payload = runtime_upgrade_service.build_runtime_upgrade_status(
        snapshot,
        running_task_count=1,
        agent_call_count=1,
    )
    assert bool(drain_status.get("active")), drain_status
    assert str(drain_status.get("code") or "").strip() == "candidate_newer_pending_idle_window", drain_status
    assert bool(status_payload.get("drain_active")), status_payload
    assert str(status_payload.get("drain_reason_code") or "").strip() == "candidate_newer_pending_idle_window", status_payload

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
            "summary": "verify upgrade drain blocks new dispatch",
            "review_mode": "none",
            "external_request_id": "upgrade-drain-dispatch-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_id": "node-upgrade-drain",
            "node_name": "upgrade drain node",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "verify prod upgrade drain blocks dispatch",
            "expected_artifact": "upgrade-drain.md",
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

    original_drain_state = runtime_upgrade_service.runtime_upgrade_drain_state
    runtime_upgrade_service.runtime_upgrade_drain_state = lambda snapshot=None: {
        "active": True,
        "code": "candidate_newer_pending_idle_window",
        "reason": "已存在更高 prod candidate，冻结新派发为 idle watcher 创造升级空窗。",
        "environment": "prod",
        "current_version": "20260411-214605",
        "candidate_version": "20260411-220013",
    }
    try:
        dispatch_result = ws.dispatch_assignment_next(
            root,
            ticket_id_text=ticket_id,
            operator="schedule-worker",
            include_test_data=False,
        )
        task_record["scheduler_state"] = "idle"
        ws._assignment_write_json(task_path, task_record)
        resume_result = ws.resume_assignment_scheduler(
            root,
            ticket_id_text=ticket_id,
            operator="schedule-worker",
            include_test_data=False,
        )
    finally:
        runtime_upgrade_service.runtime_upgrade_drain_state = original_drain_state

    latest_node = ws._assignment_read_json(node_path)
    run_records = ws._assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id)
    skipped = [dict(item) for item in list(dispatch_result.get("skipped") or []) if isinstance(item, dict)]
    assert not list(dispatch_result.get("dispatched") or []), dispatch_result
    assert skipped and str(skipped[0].get("code") or "").strip() == "upgrade_drain_active", dispatch_result
    assert str(skipped[0].get("message") or "").strip().startswith("[upgrade_drain_active:"), dispatch_result
    assert str(latest_node.get("status") or "").strip().lower() == "ready", latest_node
    assert not run_records, run_records
    assert str((resume_result.get("dispatch_result") or {}).get("mode") or "").strip() == "drain", resume_result
    assert str((resume_result.get("dispatch_result") or {}).get("code") or "").strip() == "upgrade_drain_active", resume_result

    print(
        json.dumps(
            {
                "ok": True,
                "drain_status": drain_status,
                "status_payload": {
                    "drain_active": bool(status_payload.get("drain_active")),
                    "drain_reason_code": str(status_payload.get("drain_reason_code") or "").strip(),
                    "blocking_reason_code": str(status_payload.get("blocking_reason_code") or "").strip(),
                },
                "dispatch_result": {
                    "message": str(dispatch_result.get("message") or "").strip(),
                    "code": str(dispatch_result.get("code") or "").strip(),
                    "skipped": skipped,
                },
                "resume_result": {
                    "state": str(resume_result.get("state") or "").strip(),
                    "dispatch_result": dict(resume_result.get("dispatch_result") or {}),
                },
                "latest_node_status": str(latest_node.get("status") or "").strip(),
                "run_record_count": len(run_records),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
