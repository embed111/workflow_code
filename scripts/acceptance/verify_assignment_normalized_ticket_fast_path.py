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

    root = workspace_root / ".test" / "runtime-assignment-normalized-fast-path"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    artifact_root = (root / "artifact-root").resolve()
    ticket_id = "asg-normalized-fast-path"
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
    ws.ensure_tables(root)

    task_record = ws._assignment_build_task_record(
        ticket_id=ticket_id,
        graph_name="归一化快路径验收图",
        source_workflow="workflow-acceptance",
        summary="已归一化 ticket 不应在热读路径里再触发全量 repair。",
        review_mode="none",
        global_concurrency_limit=1,
        is_test_data=False,
        external_request_id="assignment-normalized-fast-path",
        scheduler_state="running",
        pause_note="",
        created_at="2026-04-08T09:55:00+08:00",
        updated_at="2026-04-08T09:55:00+08:00",
        edges=[],
        record_state="active",
    )
    node_record = ws._assignment_build_node_record(
        ticket_id=ticket_id,
        node_id="node-fast-path",
        node_name="归一化快路径节点",
        source_schedule_id="",
        planned_trigger_at="",
        trigger_instance_id="",
        trigger_rule_summary="",
        assigned_agent_id="workflow",
        assigned_agent_name="workflow",
        node_goal="验证 load_task_record/load_node_records 不触发全量 repair。",
        expected_artifact="fast-path-report.md",
        delivery_mode="none",
        delivery_receiver_agent_id="",
        delivery_receiver_agent_name="",
        artifact_delivery_status="pending",
        artifact_delivered_at="",
        artifact_paths=[],
        status="ready",
        priority=1,
        completed_at="",
        success_reason="",
        result_ref="",
        failure_reason="",
        created_at="2026-04-08T09:55:00+08:00",
        updated_at="2026-04-08T09:55:00+08:00",
        upstream_node_ids=[],
        downstream_node_ids=[],
        record_state="active",
        delete_meta={},
    )
    (task_dir / "task.json").write_text(
        json.dumps(task_record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (nodes_dir / "node-fast-path.json").write_text(
        json.dumps(node_record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with patch.object(ws, "_assignment_repair_ticket_files", side_effect=AssertionError("normalized fast path should skip repair")):
        loaded_task = ws._assignment_load_task_record(root, ticket_id)
        loaded_nodes = ws._assignment_load_node_records(root, ticket_id, include_deleted=True)

    structure_path = task_dir / "TASK_STRUCTURE.md"
    assert structure_path.exists(), "TASK_STRUCTURE.md should be refreshed on fast path"
    assert str(loaded_task.get("ticket_id") or "").strip() == ticket_id, loaded_task
    assert len(loaded_nodes) == 1, loaded_nodes
    assert str(loaded_nodes[0].get("node_id") or "").strip() == "node-fast-path", loaded_nodes

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "task_structure_path": structure_path.as_posix(),
                "node_count": len(loaded_nodes),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
