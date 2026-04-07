#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch


def _write_runtime_config(root: Path, artifact_root: Path) -> None:
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


def _seed_running_node(ws, root: Path, *, ticket_id: str, node_id: str, workspace_path: Path, now_text: str) -> None:
    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = now_text
    ws._assignment_write_json(node_path, node_payload)
    ws._assignment_write_run_record(
        root,
        ticket_id=ticket_id,
        run_record={
            "record_type": "assignment_run",
            "schema_version": 1,
            "run_id": f"arun-{node_id}",
            "ticket_id": ticket_id,
            "node_id": node_id,
            "provider": "codex",
            "workspace_path": workspace_path.as_posix(),
            "status": "running",
            "command_summary": "runtime upgrade self exclusion probe",
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


class _Handler:
    def __init__(self) -> None:
        self.status: int | None = None
        self.payload: dict | None = None

    def send_json(self, status: int, payload: dict) -> None:
        self.status = int(status)
        self.payload = dict(payload or {})


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import assignment_service
    from workflow_app.server.api import runtime_upgrade

    root = workspace_root / ".test" / "runtime-upgrade-self-exclusion"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    candidate_app_root = (root / "candidate-app").resolve()
    candidate_app_root.mkdir(parents=True, exist_ok=True)
    candidate_evidence_path = (root / "candidate-evidence.json").resolve()
    candidate_evidence_path.write_text("{}\n", encoding="utf-8")
    _write_runtime_config(root, artifact_root)

    cfg = type(
        "Cfg",
        (),
        {
            "root": root,
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()
    state = ws.RuntimeState()

    snapshot = {
        "environment": "prod",
        "current_version": "20260407-200414",
        "current_version_rank": "20260407-200414",
        "candidate": {
            "version": "20260408-040001",
            "version_rank": "20260408-040001",
            "source_environment": "test",
            "passed_at": "2026-04-08T00:00:00Z",
            "evidence_path": candidate_evidence_path.as_posix(),
            "candidate_record_path": (root / "prod-candidate.json").as_posix(),
            "candidate_app_root": candidate_app_root.as_posix(),
        },
        "last_action": {},
        "upgrade_request": {},
    }
    requested: list[dict[str, str]] = []
    shutdowns: list[dict[str, object]] = []

    with patch.object(assignment_service, "list_available_agents", return_value=[{"agent_id": "workflow", "agent_name": "workflow"}]), patch.object(
        runtime_upgrade.rus,
        "runtime_snapshot",
        return_value=snapshot,
    ), patch.object(
        runtime_upgrade.rus,
        "write_prod_upgrade_request",
        side_effect=lambda _snapshot, operator: requested.append({"operator": str(operator), "candidate_version": str((snapshot.get("candidate") or {}).get("version") or "")}) or {"requested_at": "2026-04-08T04:00:00Z", "candidate_version": str((snapshot.get("candidate") or {}).get("version") or "")},
    ), patch.object(
        runtime_upgrade.rus,
        "schedule_runtime_shutdown",
        side_effect=lambda _state, **kwargs: shutdowns.append(dict(kwargs)),
    ), patch.object(
        runtime_upgrade.ws,
        "active_runtime_task_count",
        return_value=0,
    ):
        graph = assignment_service.create_assignment_graph(
            cfg,
            {
                "operator": "test",
                "graph_name": "runtime upgrade self exclusion probe",
                "source_workflow": "runtime-upgrade-self-exclusion",
                "summary": "verify runtime upgrade can exclude current workflow node",
                "review_mode": "none",
                "external_request_id": "runtime-upgrade-self-exclusion",
            },
        )
        ticket_id = str(graph.get("ticket_id") or "").strip()
        if not ticket_id:
            raise RuntimeError("ticket_id missing")

        def create_node(node_id: str, node_name: str) -> None:
            assignment_service.create_assignment_node(
                cfg,
                ticket_id,
                {
                    "operator": "test",
                    "node_id": node_id,
                    "node_name": node_name,
                    "assigned_agent_id": "workflow",
                    "priority": "P1",
                    "node_goal": "verify runtime upgrade self exclusion",
                    "expected_artifact": "continuous-improvement-report.md",
                    "delivery_mode": "none",
                },
                include_test_data=True,
            )

        create_node("node-self-upgrade", "[持续迭代] workflow / self-upgrade probe")
        now_text = ws.iso_ts(ws.now_local())
        _seed_running_node(
            ws,
            root,
            ticket_id=ticket_id,
            node_id="node-self-upgrade",
            workspace_path=workspace_root,
            now_text=now_text,
        )

        baseline_handler = _Handler()
        runtime_upgrade.try_handle_get(
            baseline_handler,
            cfg,
            state,
            {"path": "/api/runtime-upgrade/status", "query": {}},
        )
        assert baseline_handler.status == 200, baseline_handler.payload
        baseline_payload = dict(baseline_handler.payload or {})
        assert not bool(baseline_payload.get("can_upgrade")), baseline_payload
        assert int(baseline_payload.get("running_task_count") or 0) == 1, baseline_payload

        exclusion_query = {
            "exclude_assignment_ticket_id": [ticket_id],
            "exclude_assignment_node_id": ["node-self-upgrade"],
        }
        excluded_handler = _Handler()
        runtime_upgrade.try_handle_get(
            excluded_handler,
            cfg,
            state,
            {"path": "/api/runtime-upgrade/status", "query": exclusion_query},
        )
        assert excluded_handler.status == 200, excluded_handler.payload
        excluded_payload = dict(excluded_handler.payload or {})
        assert bool(excluded_payload.get("can_upgrade")), excluded_payload
        assert int(excluded_payload.get("running_task_count") or 0) == 0, excluded_payload
        assert bool(excluded_payload.get("running_gate_exclusion_applied")), excluded_payload

        apply_handler = _Handler()
        runtime_upgrade.try_handle_post(
            apply_handler,
            cfg,
            state,
            {
                "path": "/api/runtime-upgrade/apply",
                "body": {
                    "operator": "self-upgrade-probe",
                    "exclude_assignment_ticket_id": ticket_id,
                    "exclude_assignment_node_id": "node-self-upgrade",
                },
            },
        )
        assert apply_handler.status == 202, apply_handler.payload
        assert requested and requested[-1]["candidate_version"] == "20260408-040001", requested
        assert shutdowns and int(shutdowns[-1].get("exit_code") or 0) == int(runtime_upgrade.rus.PROD_UPGRADE_EXIT_CODE), shutdowns

        create_node("node-other-running", "other running node")
        _seed_running_node(
            ws,
            root,
            ticket_id=ticket_id,
            node_id="node-other-running",
            workspace_path=workspace_root,
            now_text=ws.iso_ts(ws.now_local()),
        )

        blocked_handler = _Handler()
        runtime_upgrade.try_handle_get(
            blocked_handler,
            cfg,
            state,
            {"path": "/api/runtime-upgrade/status", "query": exclusion_query},
        )
        assert blocked_handler.status == 200, blocked_handler.payload
        blocked_payload = dict(blocked_handler.payload or {})
        assert not bool(blocked_payload.get("can_upgrade")), blocked_payload
        assert int(blocked_payload.get("running_task_count") or 0) == 1, blocked_payload

    print(
        json.dumps(
            {
                "ok": True,
                "baseline_running_task_count": int(baseline_payload.get("running_task_count") or 0),
                "excluded_running_task_count": int(excluded_payload.get("running_task_count") or 0),
                "apply_status": int(apply_handler.status or 0),
                "blocked_running_task_count": int(blocked_payload.get("running_task_count") or 0),
                "candidate_version": str((snapshot.get("candidate") or {}).get("version") or ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
