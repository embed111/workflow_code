#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str((workspace_root / "src").resolve()))
    from workflow_app.server.api.dashboard import _assignment_runtime_with_workboard_fallback

    runtime = {
        "running_task_count": 0,
        "running_agent_count": 0,
        "active_execution_count": 0,
        "agent_call_count": 0,
    }
    workboard = {
        "assignment_workboard_summary": {
            "active_agent_count": 2,
            "running_task_count": 1,
            "queued_task_count": 3,
            "failed_task_count": 4,
            "blocked_task_count": 0,
        }
    }
    patched = _assignment_runtime_with_workboard_fallback(runtime, workboard)
    assert int(patched.get("running_task_count") or 0) == 1, patched
    assert int(patched.get("running_agent_count") or 0) == 2, patched
    assert int(patched.get("active_execution_count") or 0) == 1, patched
    assert int(patched.get("agent_call_count") or 0) == 1, patched
    print(json.dumps({"ok": True, "patched": patched}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
