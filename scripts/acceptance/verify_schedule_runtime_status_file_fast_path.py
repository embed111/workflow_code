#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import schedule_service

    root = workspace_root / ".test" / "runtime-schedule-runtime-fast-path"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    artifact_root = (root / "artifact-root").resolve()
    ticket_id = "asg-schedule-runtime-fast-path"
    node_id = "node-schedule-runtime-fast-path"
    task_dir = artifact_root / "tasks" / ticket_id
    nodes_dir = task_dir / "nodes"
    nodes_dir.mkdir(parents=True, exist_ok=True)
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

    task_record = ws._assignment_build_task_record(
        ticket_id=ticket_id,
        graph_name="schedule runtime fast path graph",
        source_workflow="workflow-acceptance",
        summary="schedule runtime status should prefer task/node files",
        review_mode="none",
        global_concurrency_limit=1,
        is_test_data=False,
        external_request_id="schedule-runtime-fast-path",
        scheduler_state="running",
        pause_note="",
        created_at="2026-04-08T10:40:00+08:00",
        updated_at="2026-04-08T10:40:00+08:00",
        edges=[],
        record_state="active",
    )
    node_record = ws._assignment_build_node_record(
        ticket_id=ticket_id,
        node_id=node_id,
        node_name="schedule runtime fast path node",
        source_schedule_id="sch-fast-path",
        planned_trigger_at="2026-04-08T10:40:00+08:00",
        trigger_instance_id="sti-fast-path",
        trigger_rule_summary="定时 2026-04-08 10:40",
        assigned_agent_id="workflow",
        assigned_agent_name="workflow",
        node_goal="verify schedule runtime status file fast path",
        expected_artifact="workflow-pm-wake-summary",
        delivery_mode="none",
        delivery_receiver_agent_id="",
        delivery_receiver_agent_name="",
        artifact_delivery_status="pending",
        artifact_delivered_at="",
        artifact_paths=[],
        status="succeeded",
        priority=1,
        completed_at="2026-04-08T10:41:00+08:00",
        success_reason="fast path success",
        result_ref="result.json",
        failure_reason="",
        created_at="2026-04-08T10:40:00+08:00",
        updated_at="2026-04-08T10:41:00+08:00",
        upstream_node_ids=[],
        downstream_node_ids=[],
        record_state="active",
        delete_meta={},
    )
    (task_dir / "task.json").write_text(
        json.dumps(task_record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (nodes_dir / f"{node_id}.json").write_text(
        json.dumps(node_record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with patch.object(
        schedule_service,
        "_assignment_snapshot_for_schedule_status",
        side_effect=AssertionError("schedule runtime status should not load full assignment snapshot"),
    ):
        payload = schedule_service._assignment_runtime_status(root, ticket_id=ticket_id, node_id=node_id)

    assert payload["assignment_status"] == "succeeded", payload
    assert payload["result_status"] == "succeeded", payload
    assert payload["assignment_graph_name"] == task_record["graph_name"], payload
    assert payload["assignment_node_name"] == node_record["node_name"], payload

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "assignment_status": payload["assignment_status"],
                "result_status": payload["result_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
