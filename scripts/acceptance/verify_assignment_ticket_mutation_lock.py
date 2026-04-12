#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
import shutil
import sys
import threading
import time
from pathlib import Path


def _write_runtime_config(root: Path) -> None:
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


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import assignment_service

    runtime_root = workspace_root / ".test" / "runtime-assignment-ticket-mutation-lock"
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    _write_runtime_config(runtime_root)

    cfg = type(
        "Cfg",
        (),
        {
            "root": runtime_root,
            "agent_search_root": Path("D:/code/AI/J-Agents").resolve(),
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "assignment mutation lock",
            "source_workflow": "workflow-ui",
            "summary": "verify ticket mutation lock preserves delete during concurrent create",
            "review_mode": "none",
            "external_request_id": "assignment-mutation-lock-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    assert ticket_id, graph

    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_id": "node-mutation-old",
            "node_name": "[持续迭代] workflow / old",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "old mainline node",
            "expected_artifact": "continuous-improvement-report.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    old_node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert old_node_id == "node-mutation-old", created

    original_load_node_records = assignment_service._assignment_load_node_records
    original_store_snapshot = assignment_service._assignment_store_snapshot
    thread_roles: dict[int, str] = {}
    delete_snapshot_loaded = threading.Event()
    delete_store_finished = threading.Event()
    errors: list[str] = []
    results: dict[str, dict[str, object]] = {}

    def patched_load_node_records(root: Path, ticket_id_text: str, include_deleted: bool = False):
        node_records = original_load_node_records(root, ticket_id_text, include_deleted=include_deleted)
        role = thread_roles.get(threading.get_ident(), "")
        if str(ticket_id_text or "").strip() == ticket_id and role == "delete" and not delete_snapshot_loaded.is_set():
            delete_snapshot_loaded.set()
            time.sleep(0.35)
        return node_records

    def patched_store_snapshot(root: Path, *, task_record: dict, node_records: list[dict]) -> None:
        role = thread_roles.get(threading.get_ident(), "")
        current_ticket_id = str(task_record.get("ticket_id") or "").strip()
        if current_ticket_id == ticket_id and role == "create":
            if not delete_store_finished.wait(timeout=5):
                raise AssertionError("delete snapshot write did not finish before create snapshot write")
        original_store_snapshot(root, task_record=task_record, node_records=node_records)
        if current_ticket_id == ticket_id and role == "delete":
            delete_store_finished.set()

    assignment_service._assignment_load_node_records = patched_load_node_records
    assignment_service._assignment_store_snapshot = patched_store_snapshot
    try:
        def run_delete() -> None:
            thread_roles[threading.get_ident()] = "delete"
            try:
                results["delete"] = ws.delete_assignment_node(
                    runtime_root,
                    ticket_id_text=ticket_id,
                    node_id_text=old_node_id,
                    operator="test",
                    reason="superseded by mutation lock probe",
                    include_test_data=False,
                )
            except Exception as exc:  # pragma: no cover - surfaced by assert below
                errors.append(f"delete: {exc}")

        def run_create() -> None:
            thread_roles[threading.get_ident()] = "create"
            try:
                results["create"] = ws.create_assignment_node(
                    cfg,
                    ticket_id,
                    {
                        "node_id": "node-mutation-new",
                        "node_name": "[持续迭代] workflow / new",
                        "assigned_agent_id": "workflow",
                        "priority": "P1",
                        "node_goal": "new mainline node",
                        "expected_artifact": "continuous-improvement-report.md",
                        "delivery_mode": "none",
                        "operator": "test",
                    },
                    include_test_data=False,
                )
            except Exception as exc:  # pragma: no cover - surfaced by assert below
                errors.append(f"create: {exc}")

        delete_thread = threading.Thread(target=run_delete, daemon=True)
        create_thread = threading.Thread(target=run_create, daemon=True)
        delete_thread.start()
        assert delete_snapshot_loaded.wait(timeout=5), "delete thread did not reach snapshot load gate"
        create_thread.start()
        delete_thread.join(timeout=10)
        create_thread.join(timeout=10)
    finally:
        assignment_service._assignment_load_node_records = original_load_node_records
        assignment_service._assignment_store_snapshot = original_store_snapshot

    assert not errors, errors
    assert "delete" in results and "create" in results, results

    old_node = ws._assignment_read_json(ws._assignment_node_record_path(runtime_root, ticket_id, old_node_id))
    new_node = ws._assignment_read_json(ws._assignment_node_record_path(runtime_root, ticket_id, "node-mutation-new"))
    audit_rows = ws._assignment_load_audit_records(runtime_root, ticket_id=ticket_id, limit=20)

    assert str(old_node.get("record_state") or "").strip().lower() == "deleted", old_node
    assert str(new_node.get("record_state") or "active").strip().lower() == "active", new_node
    assert any(str(row.get("action") or "").strip() == "delete_node" for row in audit_rows), audit_rows
    assert any(
        str(row.get("action") or "").strip() == "create_node"
        and str(row.get("node_id") or "").strip() == "node-mutation-new"
        for row in audit_rows
    ), audit_rows

    create_source = inspect.getsource(assignment_service.create_assignment_node)
    delete_source = inspect.getsource(assignment_service.delete_assignment_node)
    override_source = inspect.getsource(assignment_service.override_assignment_node_status)
    assert "_assignment_ticket_mutation_lock" in create_source
    assert "_assignment_ticket_mutation_lock" in delete_source
    assert "_assignment_ticket_mutation_lock" in override_source

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "deleted_node_state": str(old_node.get("record_state") or "").strip().lower(),
                "created_node_id": str(new_node.get("node_id") or "").strip(),
                "audit_actions": [str(row.get("action") or "").strip() for row in audit_rows[:6]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
