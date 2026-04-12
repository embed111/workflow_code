from __future__ import annotations

from workflow_app.server.services.release_boundary_service import (
    RELEASE_BOUNDARY_REPORT_PATH,
    collect_release_boundary_snapshot,
)
from workflow_app.server.services.pm_version_status_service import (
    format_pm_version_prompt_lines,
    load_pm_version_status,
)

ASSIGNMENT_SELF_ITERATION_AGENT_IDS = {"workflow"}
ASSIGNMENT_SELF_ITERATION_SCHEDULE_PREFIX = "[持续迭代]"
ASSIGNMENT_SELF_ITERATION_SUCCESS_DELAY_MINUTES = 15
ASSIGNMENT_SELF_ITERATION_FAILURE_DELAY_MINUTES = 10
ASSIGNMENT_PM_WAKE_SCHEDULE_NAME = "pm持续唤醒 - workflow 主线巡检"
ASSIGNMENT_PM_WATCHDOG_INTERVAL_MINUTES = 20
ASSIGNMENT_PM_WAKE_EXPECTED_ARTIFACT = "workflow-pm-wake-summary"
ASSIGNMENT_SELF_ITERATION_EXPECTED_ARTIFACT = "continuous-improvement-report.md"
ASSIGNMENT_PM_GOVERNANCE_README_PATH = "pm/README.md"
ASSIGNMENT_SELF_ITERATION_MASTER_PLAN_PATH = "pm/PM版本推进计划.md"
ASSIGNMENT_SELF_ITERATION_VERSION_PLAN_PATH = "pm/PM当前版本计划.md"
ASSIGNMENT_SELF_ITERATION_DAILY_TASK_PATH = "pm/PM每日任务清单.md"
ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT = "pm/daily-execution-history/YYYY-MM-DD.md"
ASSIGNMENT_SELF_ITERATION_VERSION_HISTORY_HINT = "pm/versions/<active_version>/history/YYYY-MM/YYYY-MM-DD.md"
ASSIGNMENT_SELF_ITERATION_WAKE_REQUIREMENT_PATH = "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md"
ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT = (
    "UCD/设计优化、测试探测、工程质量探测、需求分析、架构优化、功能开发、高价值功能探索"
)
ASSIGNMENT_SELF_ITERATION_LIFECYCLE_TEXT = (
    "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯"
)
ASSIGNMENT_SELF_ITERATION_TEAMMATES_TEXT = (
    "workflow_devmate / workflow_testmate / workflow_qualitymate / workflow_bugmate"
)
ASSIGNMENT_SELF_UPGRADE_HINT = (
    "正式升级改由 `prod` supervisor 托管的 idle watcher 周期检查并发起；"
    "当前主线/巡检节点不要再通过自排除方式自己触发 `/api/runtime-upgrade/apply`。"
)


def _assignment_self_iteration_enabled(task_record: dict[str, Any], node_record: dict[str, Any]) -> bool:
    if bool(task_record.get("is_test_data")):
        return False
    if str(node_record.get("record_state") or "active").strip().lower() == "deleted":
        return False
    agent_id = str(node_record.get("assigned_agent_id") or "").strip().lower()
    if not agent_id:
        return False
    return agent_id in ASSIGNMENT_SELF_ITERATION_AGENT_IDS


def _assignment_self_iteration_schedule_name(agent_id: str) -> str:
    agent_text = str(agent_id or "").strip() or "workflow"
    return f"{ASSIGNMENT_SELF_ITERATION_SCHEDULE_PREFIX} {agent_text}"


def _assignment_pm_wake_schedule_name(agent_id: str) -> str:
    agent_text = str(agent_id or "").strip().lower()
    if agent_text == "workflow" or not agent_text:
        return ASSIGNMENT_PM_WAKE_SCHEDULE_NAME
    return f"pm持续唤醒 - {str(agent_id or '').strip()} 主线巡检"


def _assignment_pm_watchdog_times() -> list[str]:
    interval_minutes = max(1, int(ASSIGNMENT_PM_WATCHDOG_INTERVAL_MINUTES))
    return [
        f"{int(total_minutes // 60):02d}:{int(total_minutes % 60):02d}"
        for total_minutes in range(0, 24 * 60, interval_minutes)
    ]


def _assignment_release_boundary_compact_lines(*, root: Path | None = None) -> list[str]:
    snapshot = collect_release_boundary_snapshot(runtime_root=root) if root is not None else {}
    developer_id = str(snapshot.get("developer_id") or "").strip() or "pm-main"
    workspace_head = str(snapshot.get("workspace_head") or "").strip() or "-"
    code_root_head = str(snapshot.get("code_root_head") or "").strip() or "-"
    return [
        f"发布边界专项方案：{RELEASE_BOUNDARY_REPORT_PATH}",
        (
            "根仓同步快照："
            f" root_sync_state={str(snapshot.get('root_sync_state') or '').strip() or 'diverged_or_unknown'}"
            f" ; ahead_count={int(snapshot.get('ahead_count') or 0)}"
            f" ; dirty_tracked_count={int(snapshot.get('dirty_tracked_count') or 0)}"
            f" ; untracked_count={int(snapshot.get('untracked_count') or 0)}"
        ),
        f"当前开发工作区：{developer_id} ; workspace_head={workspace_head} ; code_root_head={code_root_head}",
        (
            f"next_push_batch: {str(snapshot.get('next_push_batch') or '').strip() or '待切批'}"
            f" ; push_block_reason: {str(snapshot.get('push_block_reason') or '').strip() or '-'}"
        ),
        "注意：这些计数只是异常触发信号；一旦命中 dirty/ahead/阻塞，不允许只汇报数字，必须先执行清理、切批、提交、推根仓或明确阻塞收口。",
    ]


def _assignment_pm_version_compact_lines(*, root: Path | None = None) -> list[str]:
    if root is None:
        return []
    return format_pm_version_prompt_lines(load_pm_version_status(root))


def _assignment_self_iteration_schedule_payload(
    *,
    root: Path | None = None,
    agent_id: str,
    ticket_id: str,
    node_id: str,
    result_summary: str,
    next_trigger_at: str,
    priority: str,
) -> dict[str, Any]:
    summary_text = _short_assignment_text(result_summary, 240) or "上一轮已完成，继续推进 workflow 工程质量提升。"
    version_plan_path = ASSIGNMENT_SELF_ITERATION_VERSION_PLAN_PATH
    wake_requirement_path = ASSIGNMENT_SELF_ITERATION_WAKE_REQUIREMENT_PATH
    release_boundary_lines = _assignment_release_boundary_compact_lines(root=root)
    pm_version_lines = _assignment_pm_version_compact_lines(root=root)
    return {
        "schedule_name": _assignment_self_iteration_schedule_name(agent_id),
        "enabled": True,
        "assigned_agent_id": agent_id,
        "launch_summary": "\n".join(
            [
                "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 连续迭代。",
                "本轮先服务当前 active 版本与当前窗口任务，不空转，也不把保底巡检职责混进主线。",
                "禁止改写上一轮；先识别已完成事项，再选当前最高价值动作。",
                f"先读 PM 治理入口：{ASSIGNMENT_PM_GOVERNANCE_README_PATH}",
                f"必读：{ASSIGNMENT_SELF_ITERATION_MASTER_PLAN_PATH} / {version_plan_path} / `{version_plan_path}` 中 `active_version_file` 指向的版本文件 / {ASSIGNMENT_SELF_ITERATION_DAILY_TASK_PATH} / {wake_requirement_path}",
                (
                    f"今日例行任务是否已完成，看 `{ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT}`；"
                    "每日任务现在只包含“每日 1 次系统 7x24 运维质量检查”和“团队内每个小伙伴每日学习提示”。"
                ),
                *pm_version_lines,
                *release_boundary_lines,
                f"上一轮结果: {summary_text}",
            ]
        ).strip(),
        "execution_checklist": "\n".join(
            [
                f"1. 按 `{ASSIGNMENT_PM_GOVERNANCE_README_PATH} -> {ASSIGNMENT_SELF_ITERATION_MASTER_PLAN_PATH} -> {version_plan_path} -> {version_plan_path} 中 active_version_file 指向的版本文件 -> {ASSIGNMENT_SELF_ITERATION_DAILY_TASK_PATH} -> {wake_requirement_path}` 的顺序补齐上下文。",
                f"2. 先确认本轮属于 `{ASSIGNMENT_SELF_ITERATION_LIFECYCLE_TEXT}` 中的哪一段，并从 `{ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT}` 里判断当前最高价值泳道。",
                (
                    f"3. 先检查 `{ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT}` 对应的今日日文件是否存在；"
                    "若不存在，需要在本轮合适窗口补做今天唯一一轮每日任务；若已存在，则不要把每日任务误当成每轮待办。"
                ),
                "4. 先对照上一轮结果和最近版本记录；若本轮计划与上一轮主产出实质一致，必须改选更高价值切片。",
                "5. 本轮必须明确版本究竟推进了哪一项：`工程质量探测 / bug 探测 / 当前需求开发 / 发布推进`；若只是复述上一轮，就视为无效轮次。",
                "6. 按 `质量 / 效率 / 工作区小伙伴维护 = 4 / 4 / 2` 判断重点；若 live 真相显示另一条线更高价值，主动重排优先级。",
                "7. 只有 helper workspace 真异常、drift、creating 或无法派发时，才把工作区可用性抬成最高优先级。",
                f"8. 先记录 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`；若命中 dirty/ahead/异常治理现场，立即进入发布边界收口模式。",
                f"9. 只做受支持动作：基于本机 `../workflow_code` 的 non-destructive 收口、developer workspace bootstrap/refresh、helper stale `creating` / schedule / supervisor / runtime-upgrade 恢复；不要主动 `fetch/pull origin` 或拉 GitHub。",
                "10. 命中工作区问题时，不能停在“等待问题被解决”。只要属于受支持动作范围，你必须主动治理收口；只有确实超出支持范围或继续动作风险更大时，才允许记为 blocked。",
                "11. 再检查 `/healthz`、`/api/status`、`/api/schedules`、`/api/runtime-upgrade/status`；必要时再看 `status-detail / run.json / events.log`。当前 shell 是 PowerShell：不要使用 bash heredoc，不要把 `scripts/*.ps1` 这类通配路径直接交给 `rg`，也不要手工猜 run_id。",
                f"12. 正式升级申请改由 `prod` supervisor 托管的 idle watcher 周期检查并发起，当前主线节点不要自己调用 `/api/runtime-upgrade/apply`。{ASSIGNMENT_SELF_UPGRADE_HINT}",
                f"13. 每轮都要检查是否需要给 {ASSIGNMENT_SELF_ITERATION_TEAMMATES_TEXT} 创建、续挂、恢复或调整任务；这属于 PM 主线每轮必查项，不属于每日任务。",
                f"14. 当天的版本推进、后移和后续版本排期判断先写 `{ASSIGNMENT_SELF_ITERATION_VERSION_HISTORY_HINT}`；只有本轮主判断发生变化时，才更新 `{version_plan_path}` 的当前状态快照，或对应版本文件的具体排期正文。",
                "15. 若识别到新的高杠杆功能或低维护价值重构项，先记入版本记录，并明确它进入 `V2 / V3 / V4 / backlog` 的哪一处，不要继续把当前版本加胖。",
                "16. 更新 `.codex/memory/...` 时，在 `next` 明确写出下一次主线/保底触发时间；记忆库每一轮都要更新，不能因为当天每日任务已完成就跳过。",
            ]
        ).strip(),
        "done_definition": "\n".join(
            [
                "1. 当前活跃版本文件中的最高优先事项有可交付结果，或已经被明确标记为 blocked。",
                f"2. 若今日 `{ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT}` 原本不存在，本轮已经补齐当天每日执行结果，或明确写清为什么仍未完成。",
                "3. 本轮执行内容不能与上一轮主内容实质一致；若沿同一事项继续推进，必须新增证据、缺陷、实现、决策或发布动作。",
                "4. 本轮要写清当前泳道、生命周期阶段，以及版本是否真的发生推进；若没有推进，必须写清卡点和下一轮改变动作。",
                f"5. 当天的版本推进、后移和后续版本排期判断已写入 `{ASSIGNMENT_SELF_ITERATION_VERSION_HISTORY_HINT}`；只有主判断变化时才更新 `{version_plan_path}` 的当前状态快照。",
                "6. 本轮显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`，并且没有把它们误当成最终交付本身。",
                "7. 若识别到新功能想法或低维护价值重构项，本轮已明确后移去向，而不是继续扩胖当前版本。",
                "8. 若命中工作区异常、发布边界异常或 helper 异常，本轮已经主动执行受支持的治理动作，或明确写清为什么这轮只能 blocked；不接受只写“等待问题被解决”。",
                "9. 若本轮存在已验证代码改动，本轮结束前已经完成当前工作区 `commit / push / 根仓同步`，或明确写清收口阻塞原因。",
                "10. 若当前窗口不是暂停/治理调整，本轮结束时至少还保留一个后续出口（ready / future / 明确的下一次唤醒）；若当前窗口是暂停/治理调整，则不得误续挂新的主线推进任务。",
            ]
        ),
        "priority": priority,
        "expected_artifact": ASSIGNMENT_SELF_ITERATION_EXPECTED_ARTIFACT,
        "delivery_mode": "none",
        "rule_sets": {
            "monthly": {"enabled": False},
            "weekly": {"enabled": False},
            "daily": {"enabled": False},
            "once": {"enabled": True, "date_times_text": next_trigger_at},
        },
        "operator": "assignment-self-iteration",
    }


def _assignment_find_schedule_by_name(root: Path, *, schedule_name: str, agent_id: str) -> dict[str, Any]:
    conn = connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT schedule_id,schedule_name,assigned_agent_id,next_trigger_at,enabled,deleted_at,updated_at
            FROM schedule_plans
            WHERE deleted_at='' AND schedule_name=? AND assigned_agent_id=?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (
                str(schedule_name or "").strip(),
                str(agent_id or "").strip(),
            ),
        ).fetchone()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def _assignment_find_self_iteration_schedule(root: Path, *, agent_id: str) -> dict[str, Any]:
    return _assignment_find_schedule_by_name(
        root,
        schedule_name=_assignment_self_iteration_schedule_name(agent_id),
        agent_id=agent_id,
    )


def _assignment_find_pm_wake_schedule(root: Path, *, agent_id: str) -> dict[str, Any]:
    return _assignment_find_schedule_by_name(
        root,
        schedule_name=_assignment_pm_wake_schedule_name(agent_id),
        agent_id=agent_id,
    )


def _assignment_self_iteration_next_trigger_at(*, success: bool) -> str:
    from datetime import timedelta

    delay_minutes = (
        ASSIGNMENT_SELF_ITERATION_SUCCESS_DELAY_MINUTES
        if success
        else ASSIGNMENT_SELF_ITERATION_FAILURE_DELAY_MINUTES
    )
    trigger_dt = now_local() + timedelta(minutes=max(1, int(delay_minutes)))
    return trigger_dt.isoformat(timespec="seconds")


def _assignment_pm_wake_next_trigger_at(*, primary_next_trigger_at: str = "") -> str:
    from datetime import datetime, timedelta

    base_dt = None
    raw_primary = str(primary_next_trigger_at or "").strip()
    if raw_primary:
        try:
            base_dt = datetime.fromisoformat(raw_primary)
        except Exception:
            base_dt = None
    if base_dt is None:
        base_dt = now_local()
    trigger_dt = base_dt + timedelta(minutes=max(1, int(ASSIGNMENT_PM_WATCHDOG_INTERVAL_MINUTES)))
    return trigger_dt.isoformat(timespec="seconds")


def _assignment_keep_earliest_future_trigger(*, existing_next: str, candidate_next: str) -> str:
    current_time = now_local().isoformat(timespec="seconds")
    existing_text = str(existing_next or "").strip()
    candidate_text = str(candidate_next or "").strip()
    if existing_text and existing_text > current_time and (
        not candidate_text or existing_text < candidate_text
    ):
        return existing_text
    return candidate_text


def _assignment_persisted_schedule_next_trigger_at(result: dict[str, Any], fallback: str) -> str:
    payload = result if isinstance(result, dict) else {}
    schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {}
    next_trigger_at = str(schedule.get("next_trigger_at") or payload.get("next_trigger_at") or "").strip()
    return next_trigger_at or str(fallback or "").strip()


def _assignment_pm_wake_schedule_payload(
    *,
    root: Path | None = None,
    agent_id: str,
    result_summary: str,
    next_trigger_at: str,
) -> dict[str, Any]:
    summary_text = _short_assignment_text(result_summary, 240) or "检查 prod 当前是否仍保留未来可执行入口，并在断链时立即补链。"
    version_plan_path = ASSIGNMENT_SELF_ITERATION_VERSION_PLAN_PATH
    wake_requirement_path = ASSIGNMENT_SELF_ITERATION_WAKE_REQUIREMENT_PATH
    release_boundary_lines = _assignment_release_boundary_compact_lines(root=root)
    pm_version_lines = _assignment_pm_version_compact_lines(root=root)
    return {
        "schedule_name": _assignment_pm_wake_schedule_name(agent_id),
        "enabled": True,
        "assigned_agent_id": agent_id,
        "launch_summary": "\n".join(
            [
                f"作为 20 分钟真定时看门狗，检查 prod 当前是否仍存在未来可执行的 [持续迭代] workflow 或 active 版本任务。",
                "若主线健康，只留下简短检查报告，不补链、不扰动现网；只有主链断了或当前窗口明确要求兜底时，才补链或接管异常治理。",
                "保底巡检也不能重复上一轮；若现场没新变化，就切到更高价值的探测、补链或开发。",
                f"先读 PM 治理入口：{ASSIGNMENT_PM_GOVERNANCE_README_PATH}",
                f"必读：{ASSIGNMENT_SELF_ITERATION_MASTER_PLAN_PATH} / {version_plan_path} / `{version_plan_path}` 中 `active_version_file` 指向的版本文件 / {ASSIGNMENT_SELF_ITERATION_DAILY_TASK_PATH} / {wake_requirement_path}",
                (
                    f"今日例行任务是否已完成，看 `{ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT}`；"
                    "每日任务现在只包含“每日 1 次系统 7x24 运维质量检查”和“团队内每个小伙伴每日学习提示”。"
                ),
                *pm_version_lines,
                *release_boundary_lines,
                f"最近上下文: {summary_text}",
            ]
        ).strip(),
        "execution_checklist": "\n".join(
            [
                f"1. 按 `{ASSIGNMENT_PM_GOVERNANCE_README_PATH} -> {ASSIGNMENT_SELF_ITERATION_MASTER_PLAN_PATH} -> {version_plan_path} -> {version_plan_path} 中 active_version_file 指向的版本文件 -> {ASSIGNMENT_SELF_ITERATION_DAILY_TASK_PATH} -> {wake_requirement_path}` 的顺序补齐上下文。",
                f"2. 先确认本轮属于 `{ASSIGNMENT_SELF_ITERATION_LIFECYCLE_TEXT}` 中的哪一段，并从 `{ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT}` 里判断当前泳道。",
                f"3. 先检查 `{ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT}` 对应的今日日文件是否存在；若不存在，需要在当天合适窗口补做今天唯一一轮每日任务并落盘。",
                "4. 先对照上一轮结果和最近版本记录；若继续做同样的事只会重复消耗 token，就必须切到更高价值的巡检、探测或开发事项。",
                "5. 本轮必须明确版本究竟推进了哪一项：`工程质量探测 / bug 探测 / 当前需求开发 / 发布推进`。",
                "6. 先判断当前版本引用和当前活跃版本文件是否要求暂停、治理调整或仅观察；若是，默认不补新主线，只报告现场并保持暂停。",
                "7. 再检查 `/healthz`、`/api/status`、`/api/schedules`、`/api/runtime-upgrade/status`；必要时再看 `assignment graph / status-detail / run.json / events.log`。",
                "8. 若主线健康、future/ready 出口存在且没有 `0 running + ready pileup` 假健康，本轮只输出最小检查报告，不做额外治理动作。",
                "9. 先记录 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`；若命中 dirty/ahead/异常治理现场，立即进入发布边界收口模式。",
                f"10. 只做受支持动作：基于本机 `../workflow_code` 的 non-destructive 收口、developer workspace bootstrap/refresh、helper stale `creating` / schedule / supervisor / runtime-upgrade 恢复。不要主动 `fetch/pull origin` 或拉 GitHub。",
                "11. 命中工作区问题时，不能停在“等待问题被解决”。只要属于受支持动作范围，你必须主动治理收口；只有确实超出支持范围或继续动作风险更大时，才允许记为 blocked。",
                f"12. 正式升级申请改由 `prod` supervisor 托管的 idle watcher 周期检查并发起，当前巡检节点不要自己调用 `/api/runtime-upgrade/apply`。{ASSIGNMENT_SELF_UPGRADE_HINT}",
                f"13. 只有主链断了，或当前版本引用/当前活跃版本文件明确要求补链/兜底时，才补新的 [持续迭代] workflow 入口；是否派发或恢复小伙伴，也要按版本文件里的每轮必查项判断。",
                f"14. 当天的版本推进、后移和后续版本排期判断先写 `{ASSIGNMENT_SELF_ITERATION_VERSION_HISTORY_HINT}`；只有本轮主判断发生变化时，才更新 `{version_plan_path}` 的当前状态快照。",
                "15. 若发现高杠杆新功能或低维护价值重构项，先记录并明确它进入哪个后续版本，不要借巡检窗口把当前版本加胖。",
                "16. 更新 `.codex/memory/...` 时，在 `next` 明确写出下一次主线/保底触发时间，并输出本次巡检结论与下一步建议；记忆库每一轮都要更新。",
            ]
        ).strip(),
        "done_definition": "\n".join(
            [
                "1. 本次巡检已经明确回答：当前是继续推进、保持暂停、还是需要兜底补链。",
                f"2. 若今日 `{ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT}` 原本不存在，本轮已经补齐当天每日执行结果，或明确写清为什么仍未完成。",
                "3. 本轮巡检内容不能与上一轮主结论实质一致；若判断继续推进，必须指出新增进展、风险变化或新切换的最高价值动作。",
                "4. 若当前窗口是暂停/治理调整，本轮没有误补新的主线 schedule 或主线任务。",
                "5. 若当前窗口允许推进，prod 仍至少保留一条未来可执行的 workflow 主线入口，且不存在 ready 堆积但没有 live run 的假健康现场。",
                "6. 本次巡检显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`，并且没有把它们误当成终态交付。",
                f"7. 当天的版本推进、后移和后续版本排期判断已写入 `{ASSIGNMENT_SELF_ITERATION_VERSION_HISTORY_HINT}`；只有主判断变化时才更新 `{version_plan_path}` 的当前状态快照。",
                "8. 若命中 7x24 异常治理现场或工作区异常，本轮已经执行受支持的治理收口动作，或明确写清为什么仍然 blocked；不接受只写“等待问题被解决”。",
            ]
        ).strip(),
        "priority": "P1",
        "expected_artifact": ASSIGNMENT_PM_WAKE_EXPECTED_ARTIFACT,
        "delivery_mode": "none",
        "rule_sets": {
            "monthly": {"enabled": False},
            "weekly": {"enabled": False},
            "daily": {"enabled": True, "times_text": ",".join(_assignment_pm_watchdog_times())},
            "once": {"enabled": False},
        },
        "operator": "assignment-self-iteration",
    }


def _assignment_queue_pm_wake_schedule(
    root: Path,
    *,
    agent_id: str,
    result_summary: str,
    primary_next_trigger_at: str = "",
) -> dict[str, Any]:
    agent_text = str(agent_id or "").strip()
    if not agent_text:
        return {"queued": False, "reason": "agent_missing"}
    next_trigger_at = _assignment_pm_wake_next_trigger_at(primary_next_trigger_at=primary_next_trigger_at)
    existing = _assignment_find_pm_wake_schedule(root, agent_id=agent_text)
    if existing:
        next_trigger_at = _assignment_keep_earliest_future_trigger(
            existing_next=str(existing.get("next_trigger_at") or "").strip(),
            candidate_next=next_trigger_at,
        )
    payload = _assignment_pm_wake_schedule_payload(
        root=root,
        agent_id=agent_text,
        result_summary=result_summary,
        next_trigger_at=next_trigger_at,
    )
    cfg = type("AssignmentPmWakeCfg", (), {})()
    cfg.root = root
    from workflow_app.server.services import schedule_service

    if existing:
        data = schedule_service.update_schedule(cfg, str(existing.get("schedule_id") or "").strip(), payload)
    else:
        data = schedule_service.create_schedule(cfg, payload)
    persisted_next_trigger_at = _assignment_persisted_schedule_next_trigger_at(data, next_trigger_at)
    return {
        "queued": True,
        "schedule_id": str(data.get("schedule_id") or "").strip(),
        "next_trigger_at": persisted_next_trigger_at,
        "agent_id": agent_text,
    }


def _assignment_queue_self_iteration_schedule(
    root: Path,
    *,
    task_record: dict[str, Any],
    node_record: dict[str, Any],
    result_summary: str,
    success: bool,
) -> dict[str, Any]:
    if not _assignment_self_iteration_enabled(task_record, node_record):
        return {"queued": False, "reason": "agent_not_enabled"}
    agent_id = str(node_record.get("assigned_agent_id") or "").strip()
    ticket_id = str(task_record.get("ticket_id") or "").strip()
    node_id = str(node_record.get("node_id") or "").strip()
    next_trigger_at = _assignment_self_iteration_next_trigger_at(success=success)
    priority = "P2" if success else "P1"
    existing = _assignment_find_self_iteration_schedule(root, agent_id=agent_id)
    if existing:
        next_trigger_at = _assignment_keep_earliest_future_trigger(
            existing_next=str(existing.get("next_trigger_at") or "").strip(),
            candidate_next=next_trigger_at,
        )
    payload = _assignment_self_iteration_schedule_payload(
        root=root,
        agent_id=agent_id,
        ticket_id=ticket_id,
        node_id=node_id,
        result_summary=result_summary,
        next_trigger_at=next_trigger_at,
        priority=priority,
    )
    cfg = type("AssignmentSelfIterationCfg", (), {})()
    cfg.root = root
    from workflow_app.server.services import schedule_service

    if existing:
        data = schedule_service.update_schedule(cfg, str(existing.get("schedule_id") or "").strip(), payload)
    else:
        data = schedule_service.create_schedule(cfg, payload)
    persisted_next_trigger_at = _assignment_persisted_schedule_next_trigger_at(data, next_trigger_at)
    backup = _assignment_queue_pm_wake_schedule(
        root,
        agent_id=agent_id,
        result_summary=result_summary,
        primary_next_trigger_at=persisted_next_trigger_at,
    )
    return {
        "queued": True,
        "schedule_id": str(data.get("schedule_id") or "").strip(),
        "next_trigger_at": persisted_next_trigger_at,
        "agent_id": agent_id,
        "backup_schedule_id": str(backup.get("schedule_id") or "").strip(),
        "backup_next_trigger_at": str(backup.get("next_trigger_at") or "").strip(),
    }


def _assignment_runtime_upgrade_loopback_base_url() -> str:
    from workflow_app.server.services import runtime_upgrade_service

    if str(runtime_upgrade_service.current_runtime_environment() or "").strip().lower() != "prod":
        return ""
    instance = runtime_upgrade_service.current_runtime_instance()
    manifest = runtime_upgrade_service.current_runtime_manifest()
    host = str((instance or {}).get("host") or (manifest or {}).get("host") or "").strip()
    port_text = str((instance or {}).get("port") or (manifest or {}).get("port") or "").strip()
    if not host or not port_text:
        return ""
    try:
        port = int(port_text)
    except Exception:
        return ""
    if port <= 0:
        return ""
    return f"http://{host}:{port}"


def _assignment_maybe_request_prod_upgrade_after_finalize(
    root: Path,
    *,
    task_record: dict[str, Any],
    node_record: dict[str, Any],
) -> dict[str, Any]:
    if not _assignment_self_iteration_enabled(task_record, node_record):
        return {
            "requested": False,
            "suppress_dispatch": False,
            "reason": "agent_not_enabled",
        }
    base_url = _assignment_runtime_upgrade_loopback_base_url()
    ticket_id = str(task_record.get("ticket_id") or "").strip()
    node_id = str(node_record.get("node_id") or "").strip()
    return {
        "requested": False,
        "suppress_dispatch": False,
        "reason": "runtime_upgrade_delegated_to_watchdog",
        "base_url": base_url,
        "ticket_id": ticket_id,
        "node_id": node_id,
    }
