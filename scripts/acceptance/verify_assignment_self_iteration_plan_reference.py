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

    from workflow_app.server.services import assignment_service, schedule_service

    payload = assignment_service._assignment_self_iteration_schedule_payload(
        root=workspace_root,
        agent_id="workflow",
        ticket_id="asg-test-version-plan",
        node_id="node-test-version-plan",
        result_summary="上一轮已经完成基础收口。",
        next_trigger_at="2026-04-06T12:30:00+08:00",
        priority="P1",
    )
    pm_wake_payload = assignment_service._assignment_pm_wake_schedule_payload(
        root=workspace_root,
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
    assert "当前版本快照：" in launch_summary, payload
    assert "docs/workflow/reports/7x24发布边界收口方案-20260409.md" in launch_summary, payload
    assert "root_sync_state=" in launch_summary, payload
    assert "next_push_batch:" in launch_summary, payload
    assert "当前 active 版本" in execution_checklist, payload
    assert "4.6.1 当前现场更新" in execution_checklist, payload
    assert "PM版本推进现场更新总览.md" in execution_checklist, payload
    assert "pm-version-live/YYYY-MM/现场更新总览.md" in execution_checklist, payload
    assert "不要在主计划正文继续追加 `10./11./12.`" in execution_checklist, payload
    assert "UCD/设计优化" in launch_summary, payload
    assert "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯" in execution_checklist, payload
    assert "baseline、变更控制" in execution_checklist, payload
    assert "发布边界收口模式" in execution_checklist, payload
    assert "root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch" in execution_checklist, payload
    assert "workflow_devmate / workflow_testmate / workflow_qualitymate / workflow_bugmate" in execution_checklist, payload
    assert "/api/runtime-upgrade/status" in execution_checklist, payload
    assert "/api/runtime-upgrade/apply" in execution_checklist, payload
    assert "idle watcher" in execution_checklist, payload
    assert "不要自己调用" in execution_checklist, payload
    assert "不要使用 bash heredoc" in execution_checklist, payload
    assert "不要把 `scripts/*.ps1` 这类通配路径直接交给 `rg`" in execution_checklist, payload
    assert "不要手工猜测 run_id" in execution_checklist, payload
    assert "在 `next` 明确写出下一次主线/保底触发时间" in execution_checklist, payload
    assert "下一次唤醒已经排上" in done_definition, payload
    assert "周期性泳道、生命周期阶段" in done_definition, payload
    assert "4.6.1 当前现场更新" in done_definition, payload
    assert "PM版本推进现场更新总览.md" in done_definition, payload
    assert "本轮显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`" in done_definition, payload

    assert "docs/workflow/governance/PM版本推进计划.md" in pm_wake_launch_summary, pm_wake_payload
    assert "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md" in pm_wake_launch_summary, pm_wake_payload
    assert "当前版本快照：" in pm_wake_launch_summary, pm_wake_payload
    assert "docs/workflow/reports/7x24发布边界收口方案-20260409.md" in pm_wake_launch_summary, pm_wake_payload
    assert "root_sync_state=" in pm_wake_launch_summary, pm_wake_payload
    assert "UCD/设计优化" in pm_wake_launch_summary, pm_wake_payload
    assert "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯" in pm_wake_execution_checklist, pm_wake_payload
    assert "4.6.1 当前现场更新" in pm_wake_execution_checklist, pm_wake_payload
    assert "PM版本推进现场更新总览.md" in pm_wake_execution_checklist, pm_wake_payload
    assert "pm-version-live/YYYY-MM/现场更新总览.md" in pm_wake_execution_checklist, pm_wake_payload
    assert "不要在主计划正文继续追加 `10./11./12.`" in pm_wake_execution_checklist, pm_wake_payload
    assert "发布边界收口模式" in pm_wake_execution_checklist, pm_wake_payload
    assert "workflow_devmate / workflow_testmate / workflow_qualitymate / workflow_bugmate" in pm_wake_execution_checklist, pm_wake_payload
    assert "/api/runtime-upgrade/status" in pm_wake_execution_checklist, pm_wake_payload
    assert "/api/runtime-upgrade/apply" in pm_wake_execution_checklist, pm_wake_payload
    assert "idle watcher" in pm_wake_execution_checklist, pm_wake_payload
    assert "不要自己调用" in pm_wake_execution_checklist, pm_wake_payload
    assert "不要使用 bash heredoc" in pm_wake_execution_checklist, pm_wake_payload
    assert "不要把 `scripts/*.ps1` 这类通配路径直接交给 `rg`" in pm_wake_execution_checklist, pm_wake_payload
    assert "不要手工猜测 run_id" in pm_wake_execution_checklist, pm_wake_payload
    assert "active 版本、泳道、生命周期阶段" in pm_wake_done_definition, pm_wake_payload
    assert "4.6.1 当前现场更新" in pm_wake_done_definition, pm_wake_payload
    assert "PM版本推进现场更新总览.md" in pm_wake_done_definition, pm_wake_payload
    assert "root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch" in pm_wake_done_definition, pm_wake_payload
    assert "异常治理现场" in execution_checklist, payload
    assert "本地根仓收口" in execution_checklist, payload
    assert "不要主动 `fetch/pull origin` 或拉 GitHub" in execution_checklist, payload
    assert "异常治理现场" in pm_wake_execution_checklist, pm_wake_payload

    schedule_goal = schedule_service._schedule_assignment_goal(
        payload,
        planned_trigger_at="2026-04-06T12:30:00+08:00",
        trigger_rule_summary="定时 2026-04-06 12:30",
    )
    pm_wake_goal = schedule_service._schedule_assignment_goal(
        pm_wake_payload,
        planned_trigger_at="2026-04-06T13:00:00+08:00",
        trigger_rule_summary="定时 2026-04-06 13:00",
    )
    assert len(schedule_goal) <= 4000, len(schedule_goal)
    assert len(pm_wake_goal) <= 4000, len(pm_wake_goal)

    workflow_prompt = assignment_service._build_assignment_execution_prompt(
        graph_row={"graph_name": "任务中心全局主图"},
        node={
            "ticket_id": "asg-test",
            "node_id": "node-test-mainline",
            "assigned_agent_id": "workflow",
            "assigned_agent_name": "workflow",
            "node_name": "[持续迭代] workflow / 2026-04-10 22:22:00",
            "node_goal": "verify workflow pm governance exception",
            "expected_artifact": "continuous-improvement-report.md",
            "delivery_mode": "none",
        },
        upstream_nodes=[],
        workspace_path=workspace_root,
    )
    testmate_prompt = assignment_service._build_assignment_execution_prompt(
        graph_row={"graph_name": "任务中心全局主图"},
        node={
            "ticket_id": "asg-test",
            "node_id": "node-test-helper",
            "assigned_agent_id": "workflow_testmate",
            "assigned_agent_name": "workflow_testmate",
            "node_name": "生产 smoke 基线",
            "node_goal": "verify helper stays in workspace scope",
            "expected_artifact": "smoke-report",
            "delivery_mode": "none",
        },
        upstream_nodes=[],
        workspace_path=workspace_root,
    )
    assert "异常治理现场" in workflow_prompt, workflow_prompt
    assert "../workflow_code" in workflow_prompt, workflow_prompt
    assert "workspace_path 限制" in workflow_prompt, workflow_prompt
    assert "不要使用 bash heredoc" in workflow_prompt, workflow_prompt
    assert "不要把 `scripts/*.ps1` 这类通配路径直接交给 `rg`" in workflow_prompt, workflow_prompt
    assert "不要手工猜测 run_id" in workflow_prompt, workflow_prompt
    assert "异常治理现场" not in testmate_prompt, testmate_prompt

    print(
        json.dumps(
            {
                "ok": True,
                "schedule_name": payload.get("schedule_name"),
                "pm_wake_schedule_name": pm_wake_payload.get("schedule_name"),
                "priority": payload.get("priority"),
                "launch_summary": launch_summary,
                "schedule_goal_length": len(schedule_goal),
                "pm_wake_goal_length": len(pm_wake_goal),
                "workflow_prompt_preview": workflow_prompt.splitlines()[:8],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
