#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _create_cfg(root: Path, agent_root: Path):
    return type(
        "Cfg",
        (),
        {
            "root": root,
            "agent_search_root": agent_root,
            "show_test_data": False,
            "runtime_environment": "prod",
        },
    )()


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
    (agent_workspace / ".codex").mkdir(parents=True, exist_ok=True)
    (agent_workspace / ".codex" / "SOUL.md").write_text("# SOUL\n", encoding="utf-8")
    (agent_workspace / ".codex" / "USER.md").write_text("# USER\n", encoding="utf-8")
    (agent_workspace / ".codex" / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")


def _create_node(ws, cfg, ticket_id: str, *, node_name: str) -> str:
    payload = {
        "node_name": node_name,
        "assigned_agent_id": "workflow_testmate",
        "priority": "P1",
        "node_goal": f"verify assignment workspace memory writeback: {node_name}",
        "expected_artifact": "memory-writeback.md",
        "delivery_mode": "none",
        "operator": "test",
    }
    node = ws.create_assignment_node(cfg, ticket_id, payload, include_test_data=False)
    node_id = str((node.get("node") or {}).get("node_id") or "").strip()
    assert node_id, node
    return node_id


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root = workspace_root / ".test" / "runtime-assignment-memory-writeback"
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

    cfg = _create_cfg(root, agent_root)
    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": "assignment-memory-writeback",
            "source_workflow": "test",
            "summary": "verify assignment workspace memory writeback",
            "review_mode": "none",
            "external_request_id": "assignment-memory-writeback-v1",
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

    success_node_id = _create_node(ws, cfg, ticket_id, node_name="memory writeback success")
    success_prep = ws._prepare_assignment_execution_run(
        root,
        ticket_id=ticket_id,
        node_id=success_node_id,
        now_text=ws.iso_ts(ws.now_local()),
    )
    success_prompt = Path(str(success_prep.get("files", {}).get("prompt") or "")).read_text(encoding="utf-8")
    assert "以 `workflow_testmate` 本人的身份执行这轮任务" in success_prompt, success_prompt
    assert "默认使用第一人称" in success_prompt, success_prompt
    ws._finalize_assignment_execution_run(
        root,
        run_id=str(success_prep.get("run_id") or "").strip(),
        ticket_id=ticket_id,
        node_id=success_node_id,
        exit_code=0,
        stdout_text="",
        stderr_text="",
        result_payload={
            "result_summary": "memory writeback success summary",
            "artifact_label": "memory-writeback.md",
            "artifact_markdown": "# success\n",
            "artifact_files": [],
            "warnings": ["warning-a"],
        },
        failure_message="",
    )

    failure_node_id = _create_node(ws, cfg, ticket_id, node_name="memory writeback failure")
    failure_prep = ws._prepare_assignment_execution_run(
        root,
        ticket_id=ticket_id,
        node_id=failure_node_id,
        now_text=ws.iso_ts(ws.now_local()),
    )
    ws._finalize_assignment_execution_run(
        root,
        run_id=str(failure_prep.get("run_id") or "").strip(),
        ticket_id=ticket_id,
        node_id=failure_node_id,
        exit_code=1,
        stdout_text="",
        stderr_text="simulated stderr",
        result_payload={},
        failure_message="memory writeback failure summary",
    )

    now_dt = ws.now_local()
    month_key = now_dt.strftime("%Y-%m")
    day_key = now_dt.strftime("%Y-%m-%d")
    daily_path = agent_workspace / ".codex" / "memory" / month_key / f"{day_key}.md"
    assert daily_path.exists(), daily_path
    daily_text = daily_path.read_text(encoding="utf-8")
    assert "memory writeback success summary" in daily_text, daily_text
    assert "memory writeback failure summary" in daily_text, daily_text
    assert str(success_prep.get("run_id") or "").strip() in daily_text, daily_text
    assert str(failure_prep.get("run_id") or "").strip() in daily_text, daily_text
    assert "系统替我补记了这轮日记" in daily_text, daily_text

    audit_path = artifact_root / "tasks" / ticket_id / "audit" / "audit.jsonl"
    audit_text = audit_path.read_text(encoding="utf-8")
    assert '"action": "append_workspace_memory"' in audit_text, audit_text

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "success_node_id": success_node_id,
                "failure_node_id": failure_node_id,
                "success_run_id": str(success_prep.get("run_id") or "").strip(),
                "failure_run_id": str(failure_prep.get("run_id") or "").strip(),
                "daily_path": daily_path.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
