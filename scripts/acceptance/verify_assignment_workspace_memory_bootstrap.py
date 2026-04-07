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

    root = workspace_root / ".test" / "runtime-assignment-memory-bootstrap"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    artifact_root = (root / "artifacts-root").resolve()
    agent_root = (root / "agents").resolve()
    agent_workspace = agent_root / "workflow_testmate"
    agent_workspace.mkdir(parents=True, exist_ok=True)
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
            "graph_name": "assignment-memory-bootstrap",
            "source_workflow": "test",
            "summary": "verify assignment workspace memory bootstrap",
            "review_mode": "none",
            "external_request_id": "assignment-memory-bootstrap-v1",
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
                "2026-04-07T00:00:00+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    node = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "memory bootstrap node",
            "assigned_agent_id": "workflow_testmate",
            "priority": "P1",
            "node_goal": "verify assignment workspace memory bootstrap",
            "expected_artifact": "memory-bootstrap.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((node.get("node") or {}).get("node_id") or "").strip()
    assert node_id, node

    now_dt = ws.now_local()
    month_key = now_dt.strftime("%Y-%m")
    day_key = now_dt.strftime("%Y-%m-%d")
    global_path = agent_workspace / ".codex" / "memory" / "全局记忆总览.md"
    month_path = agent_workspace / ".codex" / "memory" / month_key / "记忆总览.md"
    day_path = agent_workspace / ".codex" / "memory" / month_key / f"{day_key}.md"
    assert not global_path.exists(), global_path
    assert not month_path.exists(), month_path
    assert not day_path.exists(), day_path

    prep = ws._prepare_assignment_execution_run(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        now_text=ws.iso_ts(ws.now_local()),
    )

    assert global_path.exists(), global_path
    assert month_path.exists(), month_path
    assert day_path.exists(), day_path
    assert day_key in day_path.read_text(encoding="utf-8"), day_path.read_text(encoding="utf-8")
    assert month_key in month_path.read_text(encoding="utf-8"), month_path.read_text(encoding="utf-8")
    assert month_key in global_path.read_text(encoding="utf-8"), global_path.read_text(encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "run_id": str(prep.get("run_id") or "").strip(),
                "workspace_path": agent_workspace.as_posix(),
                "created_paths": [
                    global_path.as_posix(),
                    month_path.as_posix(),
                    day_path.as_posix(),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
