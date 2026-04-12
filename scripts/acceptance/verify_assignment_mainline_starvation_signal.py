#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def _seed_ticket(root: Path, *, ticket_id: str, nodes: list[dict], audits: list[dict]) -> None:
    artifact_root = (root / "artifacts-root").resolve()
    task_root = artifact_root / "tasks" / ticket_id
    _write_json(
        task_root / "task.json",
        {
            "ticket_id": ticket_id,
            "graph_name": "assignment-mainline-starvation-signal",
            "source_workflow": "workflow-ui",
            "summary": "verify workflow mainline starvation signal",
            "review_mode": "none",
            "global_concurrency_limit": 5,
            "record_state": "active",
            "is_test_data": False,
            "external_request_id": "workflow-ui-global-graph-v1",
            "scheduler_state": "running",
            "pause_note": "",
            "created_at": "2026-04-09T12:00:00+08:00",
            "updated_at": "2026-04-09T12:40:00+08:00",
        },
    )
    for node in nodes:
        _write_json(task_root / "nodes" / f"{node['node_id']}.json", node)
    _write_jsonl(task_root / "audit" / "audit.jsonl", audits)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.api import dashboard as dashboard_api

    runtime_root = (repo_root / ".test" / "runtime-assignment-mainline-starvation-signal").resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    (runtime_root / "state").mkdir(parents=True, exist_ok=True)
    artifact_root = (runtime_root / "artifacts-root").resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        runtime_root / "state" / "runtime-config.json",
        {
            "show_test_data": False,
            "agent_search_root": "C:/work/J-Agents",
            "artifact_root": artifact_root.as_posix(),
            "task_artifact_root": artifact_root.as_posix(),
        },
    )

    ticket_id = "asg-assignment-mainline-starvation-signal"
    deleted_node_id = "node-mainline-superseded"
    later_node_id = "node-mainline-running"
    _seed_ticket(
        runtime_root,
        ticket_id=ticket_id,
        nodes=[
            {
                "ticket_id": ticket_id,
                "node_id": deleted_node_id,
                "node_name": "[持续迭代] workflow / 2026-04-09 12:20:00",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "expected_artifact": "continuous-improvement-report.md",
                "status": "ready",
                "status_text": "待开始",
                "priority": 2,
                "priority_label": "P2",
                "record_state": "deleted",
                "created_at": "2026-04-09T12:20:00+08:00",
                "updated_at": "2026-04-09T12:31:00+08:00",
                "delete_meta": {
                    "delete_action": "delete_node",
                    "deleted_at": "2026-04-09T12:31:00+08:00",
                    "delete_reason": "superseded by newer schedule trigger",
                },
            },
            {
                "ticket_id": ticket_id,
                "node_id": later_node_id,
                "node_name": "[持续迭代] workflow / 2026-04-09 12:40:00",
                "assigned_agent_id": "workflow",
                "assigned_agent_name": "workflow",
                "expected_artifact": "continuous-improvement-report.md",
                "status": "running",
                "status_text": "进行中",
                "priority": 1,
                "priority_label": "P1",
                "record_state": "active",
                "created_at": "2026-04-09T12:40:00+08:00",
                "updated_at": "2026-04-09T12:40:00+08:00",
            },
        ],
        audits=[
            {
                "audit_id": "aaud-busy-skip",
                "ticket_id": ticket_id,
                "node_id": "node-patrol-running",
                "action": "followup_dispatch_blocked",
                "operator": "assignment-executor",
                "reason": "assigned agent already has running node",
                "target_status": "succeeded",
                "detail": {
                    "skipped": [
                        {
                            "node_id": deleted_node_id,
                            "code": "agent_busy",
                            "message": "assigned agent already has running node",
                        }
                    ]
                },
                "created_at": "2026-04-09T12:29:00+08:00",
            },
            {
                "audit_id": "aaud-delete-superseded",
                "ticket_id": ticket_id,
                "node_id": deleted_node_id,
                "action": "delete_node",
                "operator": "schedule-worker",
                "reason": "superseded by newer schedule trigger",
                "target_status": "deleted",
                "detail": {},
                "created_at": "2026-04-09T12:31:00+08:00",
            },
            {
                "audit_id": "aaud-dispatch-recovery",
                "ticket_id": ticket_id,
                "node_id": later_node_id,
                "action": "dispatch",
                "operator": "assignment-executor",
                "reason": "dispatch next ready node",
                "target_status": "running",
                "detail": {
                    "run_id": "arun-mainline-recovery",
                },
                "created_at": "2026-04-09T12:40:00+08:00",
            },
        ],
    )

    cfg = type("Cfg", (), {"root": runtime_root})()
    workboard = dashboard_api._workboard_payload(cfg, include_test_data=False)
    workflow_group = next(
        (
            item
            for item in list(workboard.get("assignment_workboard_agents") or [])
            if str(item.get("agent_id") or "").strip() == "workflow"
        ),
        {},
    )
    assert bool(workflow_group.get("workflow_mainline_starvation_signal")), workflow_group
    assert str(workflow_group.get("workflow_mainline_starvation_state") or "") == "mitigated", workflow_group
    note = str(workflow_group.get("workflow_mainline_starvation_note") or "")
    assert "已缓解" in note and "继续观察" in note, note
    assert deleted_node_id in note, note
    assert later_node_id in note, note
    assert bool(workboard.get("workflow_mainline_starvation_signal")), workboard
    assert str(workboard.get("workflow_mainline_starvation_state") or "") == "mitigated", workboard

    print(
        json.dumps(
            {
                "ok": True,
                "workflow_mainline_starvation_signal": workboard.get("workflow_mainline_starvation_signal"),
                "workflow_mainline_starvation_state": workboard.get("workflow_mainline_starvation_state"),
                "workflow_mainline_starvation_note": workboard.get("workflow_mainline_starvation_note"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
