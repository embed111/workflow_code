#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

PM_GOVERNANCE_README = "pm/README.md"
PM_MASTER_PLAN = "pm/PM版本推进计划.md"
PM_CURRENT_PLAN = "pm/PM当前版本计划.md"
PM_DAILY_TASK = "pm/PM每日任务清单.md"
PM_DAILY_HISTORY_HINT = "pm/daily-execution-history/YYYY-MM-DD.md"
PM_VERSION_HISTORY_HINT = "pm/versions/<active_version>/history/YYYY-MM/YYYY-MM-DD.md"
WATCHDOG_TIMES_TEXT = ",".join(f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in range(0, 60, 20))


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import schedule_service

    root = workspace_root / ".test" / "runtime-self-iter-backup-on-smoke-block"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    cfg = type(
        "Cfg",
        (),
        {
            "root": root,
            "runtime_environment": "prod",
        },
    )()

    original_load_agents = schedule_service._load_available_agents
    schedule_service._load_available_agents = lambda _cfg: [{"agent_id": "workflow", "agent_name": "workflow"}]
    try:
        now_local = datetime.now().astimezone().replace(second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")
        created = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "[持续迭代] workflow",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 连续迭代。",
                "execution_checklist": "输出本轮结论，并确保系统已经挂上下一轮可执行任务或唤醒计划。",
                "done_definition": "若当前没有新的 ready 任务，也必须保证下一次唤醒已经排上。",
                "priority": "P1",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {"enabled": True, "date_times_text": now_local},
                },
            },
        )
        schedule_id = str(created.get("schedule_id") or "").strip()
        assert schedule_id, created

        scan = schedule_service.run_schedule_scan(
            cfg,
            operator="test",
            now_at=now_local,
            schedule_id=schedule_id,
        )

        detail = {}
        for _ in range(20):
            detail = schedule_service.get_schedule_detail(root, schedule_id)
            schedule_info = dict(detail.get("schedule") or {})
            if str(schedule_info.get("last_result_status") or "").strip().lower() == "failed":
                break
            time.sleep(0.2)

        assert str(schedule_info.get("last_result_status") or "").strip().lower() == "failed", detail
        assert "smoke baseline report missing" in str(schedule_info.get("last_result_summary") or "").strip(), detail
        schedules = {}
        backup_items = []
        backup_detail = {}
        backup_schedule = {}
        for _ in range(20):
            schedules = schedule_service.list_schedules(root)
            backup_items = [
                item
                for item in list(schedules.get("items") or [])
                if str(item.get("expected_artifact") or "").strip() == "workflow-pm-wake-summary"
            ]
            backup_schedule_id = str(backup_items[0].get("schedule_id") or "").strip() if backup_items else ""
            backup_detail = schedule_service.get_schedule_detail(root, backup_schedule_id) if backup_schedule_id else {}
            backup_schedule = dict(backup_detail.get("schedule") or {})
            if len(backup_items) == 1 and bool(str(backup_items[0].get("next_trigger_at") or "").strip()):
                break
            time.sleep(0.2)

        assert len(backup_items) == 1, schedules
        assert bool(str(backup_items[0].get("next_trigger_at") or "").strip()), backup_items[0]
        assert str(backup_items[0].get("assigned_agent_id") or "").strip() == "workflow", backup_items[0]
        assert PM_GOVERNANCE_README in str(backup_schedule.get("launch_summary") or ""), backup_schedule
        assert "20 分钟真定时看门狗" in str(backup_schedule.get("launch_summary") or ""), backup_schedule
        assert PM_MASTER_PLAN in str(backup_schedule.get("launch_summary") or ""), backup_schedule
        assert PM_CURRENT_PLAN in str(backup_schedule.get("launch_summary") or ""), backup_schedule
        assert PM_DAILY_TASK in str(backup_schedule.get("launch_summary") or ""), backup_schedule
        assert "当前版本快照：" in str(backup_schedule.get("launch_summary") or ""), backup_schedule
        assert "docs/workflow/reports/7x24发布边界收口方案-20260409.md" in str(backup_schedule.get("launch_summary") or ""), backup_schedule
        assert "root_sync_state=" in str(backup_schedule.get("launch_summary") or ""), backup_schedule
        assert "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯" in str(
            backup_schedule.get("execution_checklist") or ""
        ), backup_schedule
        assert "UCD/设计优化" in str(backup_schedule.get("execution_checklist") or ""), backup_schedule
        assert "主线健康" in str(backup_schedule.get("execution_checklist") or ""), backup_schedule
        assert PM_DAILY_HISTORY_HINT in str(backup_schedule.get("execution_checklist") or ""), backup_schedule
        assert PM_VERSION_HISTORY_HINT in str(backup_schedule.get("execution_checklist") or ""), backup_schedule
        assert "发布边界收口模式" in str(backup_schedule.get("execution_checklist") or ""), backup_schedule
        assert "idle watcher" in str(backup_schedule.get("execution_checklist") or ""), backup_schedule
        assert "不要自己调用" in str(backup_schedule.get("execution_checklist") or ""), backup_schedule
        assert "当前是继续推进、保持暂停、还是需要兜底补链" in str(backup_schedule.get("done_definition") or ""), backup_schedule
        assert PM_DAILY_HISTORY_HINT in str(backup_schedule.get("done_definition") or ""), backup_schedule
        assert "root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch" in str(
            backup_schedule.get("done_definition") or ""
        ), backup_schedule
        editor_inputs = backup_schedule.get("editor_rule_inputs") if isinstance(backup_schedule.get("editor_rule_inputs"), dict) else {}
        daily_rule = editor_inputs.get("daily") if isinstance(editor_inputs.get("daily"), dict) else {}
        once_rule = editor_inputs.get("once") if isinstance(editor_inputs.get("once"), dict) else {}
        assert bool(daily_rule.get("enabled")), backup_schedule
        assert str(daily_rule.get("times_text") or "").strip() == WATCHDOG_TIMES_TEXT, backup_schedule
        assert not bool(once_rule.get("enabled")), backup_schedule

        print(
            json.dumps(
                {
                    "ok": True,
                    "self_iteration_schedule_id": schedule_id,
                    "scan": scan,
                    "backup_schedule_id": backup_schedule_id,
                    "backup_next_trigger_at": str(backup_items[0].get("next_trigger_at") or "").strip(),
                    "self_iteration_last_result_summary": str(schedule_info.get("last_result_summary") or "").strip(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        schedule_service._load_available_agents = original_load_agents


if __name__ == "__main__":
    raise SystemExit(main())
