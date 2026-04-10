#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch


def _write_workspace(agent_workspace: Path) -> None:
    agent_workspace.mkdir(parents=True, exist_ok=True)
    (agent_workspace / "AGENTS.md").write_text(
        "# workflow_testmate\n\n"
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


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import runtime_upgrade_service

    root = workspace_root / ".test" / "runtime-stale-runtime-upgrade-recovery"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    artifact_root = (root / "artifacts-root").resolve()
    agent_root = (root / "agents").resolve()
    agent_workspace = agent_root / "workflow_testmate"
    _write_workspace(agent_workspace)

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
            "graph_name": "assignment-stale-runtime-upgrade-recovery",
            "source_workflow": "test",
            "summary": "verify stale recovery recognizes runtime upgrade interruption",
            "review_mode": "none",
            "external_request_id": "assignment-stale-runtime-upgrade-recovery-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    assert ticket_id

    conn = ws.connect_db(root)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_registry(agent_id,agent_name,workspace_path,updated_at)
            VALUES (?,?,?,?)
            """,
            (
                "workflow_testmate",
                "workflow_testmate",
                agent_workspace.as_posix(),
                "2026-04-08T00:00:00+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "stale runtime upgrade recovery",
            "assigned_agent_id": "workflow_testmate",
            "priority": "P1",
            "node_goal": "verify stale recovery keeps runtime upgrade truth",
            "expected_artifact": "runtime-upgrade-recovery.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert node_id

    run_id = "arun-stale-runtime-upgrade-recovery"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=agent_workspace.as_posix(),
        status="running",
        command_summary="stale runtime upgrade recovery",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="turn.started",
        latest_event_at="2026-04-08T00:00:00+08:00",
        exit_code=0,
        started_at="2026-04-08T00:00:00+08:00",
        finished_at="",
        created_at="2026-04-08T00:00:00+08:00",
        updated_at="2026-04-08T00:00:00+08:00",
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)

    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = "2026-04-08T00:00:00+08:00"
    ws._assignment_write_json(node_path, node_payload)

    upgrade_payload = {
        "action": "upgrade",
        "status": "success",
        "finished_at": ws.iso_ts(ws.now_local()),
        "previous_version": "20260410-121209",
        "current_version": "20260410-135550",
        "candidate_version": "20260410-135550",
        "evidence_path": (root / "upgrade-evidence.json").resolve().as_posix(),
    }
    Path(upgrade_payload["evidence_path"]).write_text("{}\n", encoding="utf-8")

    with patch.object(runtime_upgrade_service, "read_prod_last_action", return_value=upgrade_payload):
        ws.get_assignment_graph(
            root,
            ticket_id,
            include_test_data=False,
            active_batch_size=20,
            history_batch_size=20,
        )

    recovered_run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    recovered_node = ws._assignment_read_json(node_path)
    audits = ws._assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=16)
    recover_audit = next(
        (
            item
            for item in list(audits or [])
            if str(item.get("action") or "").strip().lower() == "recover_stale_running"
        ),
        {},
    )
    now_dt = ws.now_local()
    day_key = now_dt.strftime("%Y-%m-%d")
    month_key = now_dt.strftime("%Y-%m")
    daily_path = agent_workspace / ".codex" / "memory" / month_key / f"{day_key}.md"
    assert daily_path.exists(), daily_path
    daily_text = daily_path.read_text(encoding="utf-8")

    failure_reason = str(recovered_node.get("failure_reason") or "").strip()
    latest_event = str(recovered_run.get("latest_event") or "").strip()
    runtime_upgrade_detail = dict((recover_audit.get("detail") or {}).get("runtime_upgrade") or {})

    assert str(recovered_run.get("status") or "").strip().lower() == "cancelled", recovered_run
    assert str(recovered_node.get("status") or "").strip().lower() == "failed", recovered_node
    assert "正式环境已从 20260410-121209 升级到 20260410-135550" in failure_reason, recovered_node
    assert "升级切换中中断" in failure_reason, recovered_node
    assert "运行句柄缺失" not in failure_reason, recovered_node
    assert "升级切换" in latest_event, recovered_run
    assert run_id in daily_text, daily_text
    assert "升级切换中中断" in daily_text, daily_text
    assert str(recover_audit.get("reason") or "").strip() == "recover stale running node after runtime upgrade switch", recover_audit
    assert runtime_upgrade_detail.get("status") == "success", recover_audit
    assert runtime_upgrade_detail.get("run_id") == run_id, recover_audit

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "run_id": run_id,
                "node_status": str(recovered_node.get("status") or "").strip(),
                "run_status": str(recovered_run.get("status") or "").strip(),
                "failure_reason": failure_reason,
                "latest_event": latest_event,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
