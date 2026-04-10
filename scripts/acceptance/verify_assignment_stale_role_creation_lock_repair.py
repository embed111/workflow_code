#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _seed_agent_workspace(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "AGENTS.md").write_text(
        "# workflow_testmate\n\n"
        "## Startup Read Order\n"
        "1. `AGENTS.md`\n"
        "2. `.codex/SOUL.md`\n"
        "3. `.codex/USER.md`\n"
        "4. `.codex/MEMORY.md`\n",
        encoding="utf-8",
    )
    codex_dir = workspace / ".codex"
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
    from workflow_app.server.services import role_creation_service as rc

    rc.bind_runtime_symbols(ws.__dict__)

    root = workspace_root / ".test" / "runtime-stale-role-creation-lock-repair"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    artifact_root = (root / "artifacts-root").resolve()
    agent_root = (root / "agents").resolve()
    agent_workspace = agent_root / "workflow_testmate"
    _seed_agent_workspace(agent_workspace)
    fresh_workspace = agent_root / "workflow_qualitymate"
    _seed_agent_workspace(fresh_workspace)
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
            "graph_name": "stale-role-creation-lock-repair",
            "source_workflow": "test",
            "summary": "verify stale role creation runtime lock repair",
            "review_mode": "none",
            "external_request_id": "stale-role-creation-lock-repair-v1",
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    rc._ensure_role_creation_tables(root)
    stale_ts = "2026-04-04T11:45:03+08:00"
    fresh_ts = ws.iso_ts(ws.now_local())
    session_id = "rcs-stale-role-creation-lock"
    fresh_session_id = "rcs-fresh-role-creation-lock"

    conn = ws.connect_db(root)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_registry(agent_id,agent_name,workspace_path,runtime_status,updated_at)
            VALUES (?,?,?,?,?)
            """,
            (
                "workflow_testmate",
                "workflow_testmate",
                agent_workspace.as_posix(),
                "creating",
                stale_ts,
            ),
        )
        conn.execute(
            """
            INSERT INTO role_creation_sessions (
                session_id,session_title,status,current_stage_key,current_stage_index,
                assignment_ticket_id,created_agent_id,created_agent_name,created_agent_workspace_path,
                workspace_init_status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                "workflow_testmate stale creating",
                "creating",
                "persona_collection",
                2,
                ticket_id,
                "workflow_testmate",
                "workflow_testmate",
                agent_workspace.as_posix(),
                "completed",
                stale_ts,
                stale_ts,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_registry(agent_id,agent_name,workspace_path,runtime_status,updated_at)
            VALUES (?,?,?,?,?)
            """,
            (
                "workflow_qualitymate",
                "workflow_qualitymate",
                fresh_workspace.as_posix(),
                "creating",
                fresh_ts,
            ),
        )
        conn.execute(
            """
            INSERT INTO role_creation_sessions (
                session_id,session_title,status,current_stage_key,current_stage_index,
                assignment_ticket_id,created_agent_id,created_agent_name,created_agent_workspace_path,
                workspace_init_status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                fresh_session_id,
                "workflow_qualitymate fresh creating",
                "creating",
                "persona_collection",
                2,
                ticket_id,
                "workflow_qualitymate",
                "workflow_qualitymate",
                fresh_workspace.as_posix(),
                "completed",
                fresh_ts,
                fresh_ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": "stale role creation lock repair node",
            "assigned_agent_id": "workflow_testmate",
            "priority": "P1",
            "node_goal": "verify stale role creation runtime lock repair",
            "expected_artifact": "stale-role-creation-lock-repair.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=False,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert node_id, created

    conn = ws.connect_db(root)
    try:
        row = conn.execute(
            "SELECT runtime_status,updated_at FROM agent_registry WHERE agent_id=? LIMIT 1",
            ("workflow_testmate",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "agent_registry row missing after repair"
    assert str(row["runtime_status"] or "").strip().lower() == "idle", dict(row)

    blocked_code = ""
    try:
        ws.create_assignment_node(
            cfg,
            ticket_id,
            {
                "node_name": "fresh creating lock still guarded",
                "assigned_agent_id": "workflow_qualitymate",
                "priority": "P1",
                "node_goal": "verify fresh role creation runtime lock still blocks general assignment",
                "expected_artifact": "fresh-creating-lock.md",
                "delivery_mode": "none",
                "operator": "test",
            },
            include_test_data=False,
        )
    except Exception as exc:
        blocked_code = str(getattr(exc, "code", "") or "").strip()
    assert blocked_code == "assigned_agent_creating_locked", blocked_code

    print(
        json.dumps(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "session_id": session_id,
                "fresh_session_id": fresh_session_id,
                "node_id": node_id,
                "runtime_status": str(row["runtime_status"] or "").strip(),
                "runtime_status_updated_at": str(row["updated_at"] or "").strip(),
                "fresh_lock_blocked_code": blocked_code,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
