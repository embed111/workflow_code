#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import schedule_assignment_bridge as bridge

    called = {"create": False}

    def fake_canonical(_root):
        return "asg-fast-path"

    def fail_create(*_args, **_kwargs):
        called["create"] = True
        raise AssertionError("create_assignment_graph should not be called when canonical ticket exists")

    original_create = bridge.assignment_service.create_assignment_graph
    bridge.assignment_service.create_assignment_graph = fail_create
    bridge.bind_runtime_symbols(
        {
            "_assignment_ensure_workflow_ui_global_graph_ticket": fake_canonical,
            "SCHEDULE_ASSIGNMENT_GRAPH_NAME": "任务中心全局主图",
            "SCHEDULE_ASSIGNMENT_SOURCE_WORKFLOW": "workflow-ui",
            "SCHEDULE_ASSIGNMENT_GRAPH_REQUEST_ID": "workflow-ui-global-graph-v1",
        }
    )
    try:
        cfg = type("Cfg", (), {"root": Path(".").resolve()})()
        ticket_id = bridge.ensure_global_assignment_graph(cfg)
    finally:
        bridge.assignment_service.create_assignment_graph = original_create

    assert ticket_id == "asg-fast-path", ticket_id
    assert not called["create"], called
    print(json.dumps({"ok": True, "ticket_id": ticket_id}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
