#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.infra.db.connection import connect_db
    from workflow_app.server.infra.db.migrations import ensure_tables
    from workflow_app.server.services import training_registry_service

    training_registry_service.bind_runtime_symbols(ws.__dict__)

    runtime_root = (workspace_root / ".test" / "runtime-training-registry-assignment-runtime-status").resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    (runtime_root / "state").mkdir(parents=True, exist_ok=True)

    agent_search_root = (runtime_root / "agents").resolve()
    workspace_path = (agent_search_root / "workflow").resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    (workspace_path / "AGENTS.md").write_text("# workflow\n", encoding="utf-8")

    ensure_tables(runtime_root)
    conn = connect_db(runtime_root)
    try:
        conn.execute(
            """
            INSERT INTO agent_registry (agent_id,agent_name,workspace_path,runtime_status,updated_at)
            VALUES (?,?,?,?,?)
            """,
            (
                "workflow",
                "workflow",
                workspace_path.as_posix(),
                "idle",
                "2026-04-11T03:15:00+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    cfg = SimpleNamespace(root=runtime_root, agent_search_root=agent_search_root)
    running_projection = training_registry_service._effective_agent_runtime_status(
        "idle",
        assignment_running=True,
    )
    creating_projection = training_registry_service._effective_agent_runtime_status(
        "creating",
        assignment_running=True,
    )
    assert running_projection == ("running", "assignment_live_execution"), running_projection
    assert creating_projection == ("creating", "agent_registry"), creating_projection

    training_registry_service._REGISTRY_SYNC_LAST_ROOT = str(agent_search_root.resolve(strict=False))
    training_registry_service._REGISTRY_SYNC_LAST_AT_S = time.monotonic()
    with patch.object(
        training_registry_service,
        "_assignment_running_agent_ids",
        return_value={"workflow"},
        create=True,
    ):
        overview = training_registry_service.list_training_agents_overview(cfg, include_test_data=True)
    overview_item = next(item for item in overview["items"] if item["agent_id"] == "workflow")
    assert overview_item["runtime_status"] == "running", overview_item
    assert overview_item["runtime_status_source"] == "assignment_live_execution", overview_item
    assert overview_item["registry_runtime_status"] == "idle", overview_item
    assert overview_item["assignment_runtime_status"] == "running", overview_item

    training_registry_service._REGISTRY_SYNC_LAST_ROOT = ""
    training_registry_service._REGISTRY_SYNC_LAST_AT_S = 0.0
    available_agents = [
        {
            "agent_name": "workflow",
            "agents_md_path": str((workspace_path / "AGENTS.md").resolve(strict=False)),
            "agents_version": "v-test",
        }
    ]
    portrait = {
        "capability_summary": "持续推进 workflow 主线",
        "knowledge_scope": "7x24 连续运行",
        "skills": ["调度治理", "发布边界收口"],
        "applicable_scenarios": "主线巡检；任务接力；发布收口",
        "version_notes": "训练注册表 runtime_status 覆盖验证",
    }
    with patch.object(training_registry_service, "list_available_agents", return_value=available_agents, create=True), patch.object(
        training_registry_service,
        "extract_agent_role_portrait",
        return_value=portrait,
        create=True,
    ), patch.object(
        training_registry_service,
        "extract_core_capability_summary",
        return_value="持续推进 workflow 主线",
        create=True,
    ), patch.object(
        training_registry_service,
        "_git_available_in_scope",
        return_value=False,
        create=True,
    ), patch.object(
        training_registry_service,
        "build_agent_vector_icon",
        return_value="icon-workflow",
        create=True,
    ), patch.object(
        training_registry_service,
        "_assignment_running_agent_ids",
        return_value={"workflow"},
        create=True,
    ):
        sync_result = training_registry_service.sync_training_agent_registry(cfg)

    conn = connect_db(runtime_root)
    try:
        row = conn.execute(
            "SELECT runtime_status FROM agent_registry WHERE agent_id=? LIMIT 1",
            ("workflow",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "workflow row should exist after registry sync"
    synced_runtime_status = str(row["runtime_status"] or "")
    assert synced_runtime_status == "running", synced_runtime_status

    print(
        json.dumps(
            {
                "ok": True,
                "effective_runtime_status_examples": {
                    "idle_with_assignment_running": list(running_projection),
                    "creating_with_assignment_running": list(creating_projection),
                },
                "overview_item": {
                    "agent_id": overview_item["agent_id"],
                    "runtime_status": overview_item["runtime_status"],
                    "runtime_status_source": overview_item["runtime_status_source"],
                    "registry_runtime_status": overview_item["registry_runtime_status"],
                    "assignment_runtime_status": overview_item["assignment_runtime_status"],
                },
                "sync_result_count": len(sync_result),
                "synced_runtime_status": synced_runtime_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
