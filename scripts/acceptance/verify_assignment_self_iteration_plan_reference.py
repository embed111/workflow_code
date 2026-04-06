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

    from workflow_app.server.services import assignment_service

    payload = assignment_service._assignment_self_iteration_schedule_payload(
        agent_id="workflow",
        ticket_id="asg-test-version-plan",
        node_id="node-test-version-plan",
        result_summary="上一轮已经完成基础收口。",
        next_trigger_at="2026-04-06T12:30:00+08:00",
        priority="P1",
    )

    launch_summary = str(payload.get("launch_summary") or "")
    execution_checklist = str(payload.get("execution_checklist") or "")
    done_definition = str(payload.get("done_definition") or "")

    assert "docs/workflow/governance/PM版本推进计划.md" in launch_summary, payload
    assert "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md" in launch_summary, payload
    assert "当前 active 版本" in execution_checklist, payload
    assert "工程质量/稳定性任务" in execution_checklist, payload
    assert "下一次唤醒已经排上" in done_definition, payload

    print(
        json.dumps(
            {
                "ok": True,
                "schedule_name": payload.get("schedule_name"),
                "priority": payload.get("priority"),
                "launch_summary": launch_summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
