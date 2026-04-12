#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

PM_GOVERNANCE_README = "pm/README.md"
PM_MASTER_PLAN = "pm/PM版本推进计划.md"
PM_CURRENT_PLAN = "pm/PM当前版本计划.md"
PM_DAILY_TASK = "pm/PM每日任务清单.md"
PM_DAILY_HISTORY_HINT = "pm/daily-execution-history/YYYY-MM-DD.md"
PM_VERSION_HISTORY_HINT = "pm/versions/<active_version>/history/YYYY-MM/YYYY-MM-DD.md"
WAKE_REQUIREMENT = "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md"
RELEASE_BOUNDARY_REPORT = "docs/workflow/reports/7x24发布边界收口方案-20260409.md"


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

    assert PM_GOVERNANCE_README in launch_summary, payload
    assert PM_MASTER_PLAN in launch_summary, payload
    assert PM_CURRENT_PLAN in launch_summary, payload
    assert PM_DAILY_TASK in launch_summary, payload
    assert WAKE_REQUIREMENT in launch_summary, payload
    assert "当前版本快照：" in launch_summary, payload
    assert "当前版本文件：" in launch_summary, payload
    assert RELEASE_BOUNDARY_REPORT in launch_summary, payload
    assert "root_sync_state=" in launch_summary, payload
    assert "next_push_batch:" in launch_summary, payload
    assert PM_GOVERNANCE_README in execution_checklist, payload
    assert PM_MASTER_PLAN in execution_checklist, payload
    assert PM_CURRENT_PLAN in execution_checklist, payload
    assert PM_DAILY_TASK in execution_checklist, payload
    assert PM_DAILY_HISTORY_HINT in execution_checklist, payload
    assert PM_VERSION_HISTORY_HINT in execution_checklist, payload
    assert "UCD/设计优化" in execution_checklist, payload
    assert "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯" in execution_checklist, payload
    assert "质量 / 效率 / 工作区小伙伴维护 = 4 / 4 / 2" in execution_checklist, payload
    assert "发布边界收口模式" in execution_checklist, payload
    assert "root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch" in execution_checklist, payload
    assert "workflow_devmate / workflow_testmate / workflow_qualitymate / workflow_bugmate" in execution_checklist, payload
    assert "不属于每日任务" in execution_checklist, payload
    assert "如果你准备做的内容与上一轮主产出实质一致" in execution_checklist, payload
    assert "版本进度有没有真的推进" in execution_checklist, payload
    assert "工程质量探测、bug 探测、需求开发" in execution_checklist, payload
    assert "/api/runtime-upgrade/status" in execution_checklist, payload
    assert "/api/runtime-upgrade/apply" in execution_checklist, payload
    assert "idle watcher" in execution_checklist, payload
    assert "不要自己调用" in execution_checklist, payload
    assert "不要使用 bash heredoc" in execution_checklist, payload
    assert "不要把 `scripts/*.ps1` 这类通配路径直接交给 `rg`" in execution_checklist, payload
    assert "不要手工猜 run_id" in execution_checklist, payload
    assert "在 `next` 明确写出下一次主线/保底触发时间" in execution_checklist, payload
    assert PM_DAILY_HISTORY_HINT in done_definition, payload
    assert PM_VERSION_HISTORY_HINT in done_definition, payload
    assert "当前泳道、生命周期阶段" in done_definition, payload
    assert "后续出口" in done_definition, payload
    assert "本轮执行内容不能与上一轮主内容实质一致" in done_definition, payload
    assert "版本是否真的发生推进" in done_definition, payload
    assert "本轮显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`" in done_definition, payload

    assert PM_GOVERNANCE_README in pm_wake_launch_summary, pm_wake_payload
    assert PM_MASTER_PLAN in pm_wake_launch_summary, pm_wake_payload
    assert PM_CURRENT_PLAN in pm_wake_launch_summary, pm_wake_payload
    assert PM_DAILY_TASK in pm_wake_launch_summary, pm_wake_payload
    assert WAKE_REQUIREMENT in pm_wake_launch_summary, pm_wake_payload
    assert "当前版本快照：" in pm_wake_launch_summary, pm_wake_payload
    assert RELEASE_BOUNDARY_REPORT in pm_wake_launch_summary, pm_wake_payload
    assert "root_sync_state=" in pm_wake_launch_summary, pm_wake_payload
    assert "UCD/设计优化" in pm_wake_execution_checklist, pm_wake_payload
    assert "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯" in pm_wake_execution_checklist, pm_wake_payload
    assert PM_DAILY_HISTORY_HINT in pm_wake_execution_checklist, pm_wake_payload
    assert PM_VERSION_HISTORY_HINT in pm_wake_execution_checklist, pm_wake_payload
    assert "发布边界收口模式" in pm_wake_execution_checklist, pm_wake_payload
    assert "如果继续做同样的事，会不会只是重复消耗 token" in pm_wake_execution_checklist, pm_wake_payload
    assert "版本进度有没有真的推进" in pm_wake_execution_checklist, pm_wake_payload
    assert "/api/runtime-upgrade/status" in pm_wake_execution_checklist, pm_wake_payload
    assert "/api/runtime-upgrade/apply" in pm_wake_execution_checklist, pm_wake_payload
    assert "idle watcher" in pm_wake_execution_checklist, pm_wake_payload
    assert "不要自己调用" in pm_wake_execution_checklist, pm_wake_payload
    assert "当前是继续推进、保持暂停、还是需要兜底补链" in pm_wake_done_definition, pm_wake_payload
    assert PM_DAILY_HISTORY_HINT in pm_wake_done_definition, pm_wake_payload
    assert "本轮巡检内容不能与上一轮主结论实质一致" in pm_wake_done_definition, pm_wake_payload
    assert "root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch" in pm_wake_done_definition, pm_wake_payload
    assert "异常治理现场" in execution_checklist, payload
    assert "non-destructive 收口" in execution_checklist, payload
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
