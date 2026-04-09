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
    pm_wake_payload = assignment_service._assignment_pm_wake_schedule_payload(
        agent_id="workflow",
        result_summary="上一轮发现主链需要继续补链。",
        next_trigger_at="2026-04-06T13:00:00+08:00",
    )

    launch_summary = str(payload.get("launch_summary") or "")
    execution_checklist = str(payload.get("execution_checklist") or "")
    done_definition = str(payload.get("done_definition") or "")
    pm_wake_launch_summary = str(pm_wake_payload.get("launch_summary") or "")
    pm_wake_execution_checklist = str(pm_wake_payload.get("execution_checklist") or "")
    pm_wake_done_definition = str(pm_wake_payload.get("done_definition") or "")

    assert "docs/workflow/governance/PM版本推进计划.md" in launch_summary, payload
    assert "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md" in launch_summary, payload
    assert "docs/workflow/reports/7x24发布边界收口方案-20260409.md" in launch_summary, payload
    assert "root_sync_state=" in launch_summary, payload
    assert "next_push_batch:" in launch_summary, payload
    assert "当前 active 版本" in execution_checklist, payload
    assert "UCD/设计优化" in launch_summary, payload
    assert "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯" in execution_checklist, payload
    assert "baseline、变更控制" in execution_checklist, payload
    assert "发布边界收口模式" in execution_checklist, payload
    assert "root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch" in execution_checklist, payload
    assert "workflow_devmate / workflow_testmate / workflow_qualitymate / workflow_bugmate" in execution_checklist, payload
    assert "/api/runtime-upgrade/status" in execution_checklist, payload
    assert "/api/runtime-upgrade/apply" in execution_checklist, payload
    assert "在 `next` 明确写出下一次主线/保底触发时间" in execution_checklist, payload
    assert "下一次唤醒已经排上" in done_definition, payload
    assert "周期性泳道、生命周期阶段" in done_definition, payload
    assert "本轮显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`" in done_definition, payload

    assert "docs/workflow/governance/PM版本推进计划.md" in pm_wake_launch_summary, pm_wake_payload
    assert "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md" in pm_wake_launch_summary, pm_wake_payload
    assert "docs/workflow/reports/7x24发布边界收口方案-20260409.md" in pm_wake_launch_summary, pm_wake_payload
    assert "root_sync_state=" in pm_wake_launch_summary, pm_wake_payload
    assert "UCD/设计优化" in pm_wake_launch_summary, pm_wake_payload
    assert "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯" in pm_wake_execution_checklist, pm_wake_payload
    assert "发布边界收口模式" in pm_wake_execution_checklist, pm_wake_payload
    assert "workflow_devmate / workflow_testmate / workflow_qualitymate / workflow_bugmate" in pm_wake_execution_checklist, pm_wake_payload
    assert "/api/runtime-upgrade/status" in pm_wake_execution_checklist, pm_wake_payload
    assert "/api/runtime-upgrade/apply" in pm_wake_execution_checklist, pm_wake_payload
    assert "active 版本、泳道、生命周期阶段" in pm_wake_done_definition, pm_wake_payload
    assert "root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch" in pm_wake_done_definition, pm_wake_payload

    print(
        json.dumps(
            {
                "ok": True,
                "schedule_name": payload.get("schedule_name"),
                "pm_wake_schedule_name": pm_wake_payload.get("schedule_name"),
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
