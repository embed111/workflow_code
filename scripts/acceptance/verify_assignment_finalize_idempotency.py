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
                "2026-04-09T00:00:00+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _write_workspace(agent_workspace: Path) -> Path:
    agent_workspace.mkdir(parents=True, exist_ok=True)
    (agent_workspace / "AGENTS.md").write_text(
        "# workflow\n\n"
        "## Startup Read Order\n"
        "1. `AGENTS.md`\n"
        "2. `.codex/SOUL.md`\n"
        "3. `.codex/USER.md`\n"
        "4. `.codex/MEMORY.md`\n"
        "5. `.codex/memory/全局记忆总览.md`\n"
        "6. `.codex/memory/YYYY-MM/记忆总览.md`\n"
        "7. `.codex/memory/YYYY-MM/YYYY-MM-DD.md`\n",
        encoding="utf-8",
    )
    codex_dir = agent_workspace / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "SOUL.md").write_text("# SOUL\n", encoding="utf-8")
    (codex_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
    (codex_dir / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    report_path = agent_workspace / "continuous-improvement-report.md"
    report_path.write_text("# test finalize idempotency\n", encoding="utf-8")
    return report_path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root = workspace_root / ".test" / "runtime-assignment-finalize-idempotency"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    artifact_root = (root / "artifacts-root").resolve()
    agent_root = (root / "agents").resolve()
    agent_workspace = (agent_root / "workflow").resolve()
    source_report = _write_workspace(agent_workspace)

    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
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
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()

    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "assignment-finalize-idempotency",
            "source_workflow": "workflow-ui",
            "summary": "verify finalize is idempotent per run",
            "review_mode": "none",
            "external_request_id": "assignment-finalize-idempotency-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    _register_agent(ws, root, agent_id="workflow", agent_workspace=agent_workspace)
    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "finalize idempotency",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "verify repeated finalize does not duplicate artifact delivery",
            "expected_artifact": "continuous-improvement-report.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id
    source_report_text = source_report.read_text(encoding="utf-8")

    run_id = "arun-finalize-idempotency"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=agent_workspace.as_posix(),
        status="running",
        command_summary="verify finalize idempotency",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="turn.started",
        latest_event_at="2026-04-09T12:00:00+08:00",
        exit_code=0,
        started_at="2026-04-09T12:00:00+08:00",
        finished_at="",
        created_at="2026-04-09T12:00:00+08:00",
        updated_at="2026-04-09T12:00:00+08:00",
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    ws._write_assignment_run_text(files["prompt"], "verify finalize idempotency")
    ws._write_assignment_run_text(files["stdout"], "")
    ws._write_assignment_run_text(files["stderr"], "")
    result_payload = {
        "result_summary": "finalize idempotency summary",
        "artifact_label": "continuous-improvement-report.md",
        "artifact_markdown": "# finalize idempotency\n",
        "artifact_files": ["continuous-improvement-report.md"],
        "warnings": [],
    }
    ws._write_assignment_run_json(files["result"], result_payload)

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = "2026-04-09T12:00:00+08:00"
    ws._assignment_write_json(node_path, node_payload)

    ws._finalize_assignment_execution_run(
        root,
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        exit_code=0,
        stdout_text="",
        stderr_text="",
        result_payload=result_payload,
        failure_message="",
    )

    first_node = ws._assignment_read_json(node_path)
    first_run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    first_audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=32)
    first_actions = [str(item.get("action") or "").strip().lower() for item in list(first_audits or [])]
    first_deliver_audit = next(
        (
            item
            for item in list(first_audits or [])
            if str(item.get("action") or "").strip().lower() == "deliver_artifact"
        ),
        {},
    )
    now_dt = ws.now_local()
    day_key = now_dt.strftime("%Y-%m-%d")
    month_key = now_dt.strftime("%Y-%m")
    daily_path = agent_workspace / ".codex" / "memory" / month_key / f"{day_key}.md"
    first_daily_text = daily_path.read_text(encoding="utf-8")
    first_artifact_paths = list(first_node.get("artifact_paths") or [])
    first_artifact_text = Path(first_artifact_paths[0]).read_text(encoding="utf-8")
    delivery_info_path = ws._node_delivery_info_path(root, first_node)
    delivery_info = json.loads(delivery_info_path.read_text(encoding="utf-8"))
    delivery_inbox_paths = [str(item).strip() for item in list(delivery_info.get("delivery_inbox_paths") or []) if str(item).strip()]
    assert delivery_info_path.exists(), delivery_info_path
    assert first_deliver_audit, first_audits
    cleanup_detail = dict(first_deliver_audit.get("detail") or {}).get("source_workspace_cleanup") or {}
    cleaned_paths = [str(item).strip() for item in list(cleanup_detail.get("cleaned_paths") or []) if str(item).strip()]
    cleanup_errors = [str(item).strip() for item in list(cleanup_detail.get("cleanup_errors") or []) if str(item).strip()]

    assert str(first_run.get("status") or "").strip().lower() == "succeeded", first_run
    assert str(first_node.get("status") or "").strip().lower() == "succeeded", first_node
    assert first_artifact_paths, first_node
    assert first_actions.count("deliver_artifact") == 1, first_actions
    assert first_actions.count("execution_succeeded") == 1, first_actions
    assert first_actions.count("append_workspace_memory") == 1, first_actions
    assert first_daily_text.count("系统替我补记了这轮日记") == 1, first_daily_text
    assert first_artifact_text == source_report_text, {
        "artifact": first_artifact_text,
        "source": source_report_text,
    }
    assert first_artifact_paths[0] in first_daily_text, first_daily_text
    assert delivery_info.get("canonical_artifact_paths") == first_artifact_paths, delivery_info
    assert len(delivery_inbox_paths) == 1, delivery_info
    assert Path(delivery_inbox_paths[0]).read_text(encoding="utf-8") == source_report_text, delivery_inbox_paths
    assert source_report.as_posix() in cleaned_paths, cleaned_paths
    assert not cleanup_errors, cleanup_errors
    assert source_report.exists() is False, source_report

    ws._finalize_assignment_execution_run(
        root,
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        exit_code=0,
        stdout_text="",
        stderr_text="",
        result_payload=result_payload,
        failure_message="",
    )

    second_node = ws._assignment_read_json(node_path)
    second_run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    second_audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=32)
    second_actions = [str(item.get("action") or "").strip().lower() for item in list(second_audits or [])]
    second_daily_text = daily_path.read_text(encoding="utf-8")
    second_artifact_paths = list(second_node.get("artifact_paths") or [])
    second_delivery_info = json.loads(delivery_info_path.read_text(encoding="utf-8"))

    assert str(second_run.get("status") or "").strip().lower() == "succeeded", second_run
    assert str(second_node.get("status") or "").strip().lower() == "succeeded", second_node
    assert second_artifact_paths == first_artifact_paths, {
        "first": first_artifact_paths,
        "second": second_artifact_paths,
    }
    assert second_actions.count("deliver_artifact") == 1, second_actions
    assert second_actions.count("execution_succeeded") == 1, second_actions
    assert second_actions.count("append_workspace_memory") == 1, second_actions
    assert second_daily_text == first_daily_text, {
        "first": first_daily_text,
        "second": second_daily_text,
    }
    assert second_delivery_info == delivery_info, {
        "first": delivery_info,
        "second": second_delivery_info,
    }

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "run_id": run_id,
                "artifact_paths": second_artifact_paths,
                "audit_action_counts": {
                    "deliver_artifact": second_actions.count("deliver_artifact"),
                    "execution_succeeded": second_actions.count("execution_succeeded"),
                    "append_workspace_memory": second_actions.count("append_workspace_memory"),
                },
                "delivery_info_path": delivery_info_path.as_posix(),
                "delivery_inbox_paths": delivery_inbox_paths,
                "cleaned_paths": cleaned_paths,
                "daily_path": daily_path.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
