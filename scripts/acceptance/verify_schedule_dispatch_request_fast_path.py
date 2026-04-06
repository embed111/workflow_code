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

    calls: list[str] = []

    def fake_dispatch(*_args, **_kwargs):
        calls.append("dispatch")
        return {
            "message": "scheduler_not_running",
            "graph_overview": {"scheduler_state": "idle"},
            "dispatched_runs": [],
        }

    def fake_resume(*_args, **_kwargs):
        calls.append("resume")
        return {"state": "running"}

    def fail_overview(*_args, **_kwargs):
        raise AssertionError("get_assignment_overview should not be called")

    original_dispatch = bridge.assignment_service.dispatch_assignment_next
    original_resume = bridge.assignment_service.resume_assignment_scheduler
    original_overview = getattr(bridge.assignment_service, "get_assignment_overview", None)
    bridge.assignment_service.dispatch_assignment_next = fake_dispatch
    bridge.assignment_service.resume_assignment_scheduler = fake_resume
    if original_overview is not None:
        bridge.assignment_service.get_assignment_overview = fail_overview
    try:
        result = bridge.request_assignment_dispatch(Path("."), "asg-fast-dispatch")
    finally:
        bridge.assignment_service.dispatch_assignment_next = original_dispatch
        bridge.assignment_service.resume_assignment_scheduler = original_resume
        if original_overview is not None:
            bridge.assignment_service.get_assignment_overview = original_overview

    assert result["dispatch_status"] == "requested", result
    assert result["dispatch_message"] == "resume_scheduler_requested", result
    assert calls == ["dispatch", "resume"], calls
    print(json.dumps({"ok": True, "calls": calls, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
