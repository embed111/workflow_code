#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import schedule_service

    runtime_root = workspace_root / ".test" / "runtime-schedule-smoke-guard-expired-fail-open"
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    (runtime_root / "state").mkdir(parents=True, exist_ok=True)
    (runtime_root / ".test").mkdir(parents=True, exist_ok=True)
    (runtime_root / ".test" / "schedule_smoke_baseline.latest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "pass": True,
                "executed_at": "2026-04-06T12:00:00+08:00",
                "environment": "prod",
                "schedule_id": "sch-smoke-baseline",
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
            "root": runtime_root,
            "runtime_environment": "prod",
        },
    )()

    self_iter_schedule = {
        "assigned_agent_id": "workflow",
        "schedule_name": "[持续迭代] workflow",
        "expected_artifact": "continuous-improvement-report.md",
        "launch_summary": "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 连续迭代。",
        "execution_checklist": "输出本轮结论，并确保系统已经挂上下一轮可执行任务或唤醒计划。",
    }
    pm_awake_schedule = {
        "assigned_agent_id": "workflow",
        "schedule_name": "pm持续唤醒 - workflow 主线巡检",
        "expected_artifact": "workflow-pm-wake-summary",
        "launch_summary": "这是 workflow pm 的低频保底唤醒计划。若滚动自迭代计划断链，就按这里继续承接版本主线。",
        "execution_checklist": "只做低风险巡检、排障、计划续挂或任务补单。",
    }

    self_iter_gate = schedule_service._check_self_iter_gate(cfg, self_iter_schedule)
    pm_awake_gate = schedule_service._check_self_iter_gate(cfg, pm_awake_schedule)

    assert bool(self_iter_gate.get("allow")) is True, self_iter_gate
    assert str(self_iter_gate.get("guard_state") or "").strip() == "degraded_expired_smoke", self_iter_gate
    assert str(self_iter_gate.get("message") or "").strip() == "smoke baseline expired", self_iter_gate
    assert bool(pm_awake_gate.get("allow")) is True, pm_awake_gate
    assert str(pm_awake_gate.get("guard_state") or "").strip() == "non_self_iteration", pm_awake_gate

    print(
        json.dumps(
            {
                "ok": True,
                "self_iteration_guard_state": self_iter_gate.get("guard_state"),
                "self_iteration_message": self_iter_gate.get("message"),
                "pm_awake_guard_state": pm_awake_gate.get("guard_state"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
