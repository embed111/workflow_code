from __future__ import annotations

from workflow_app.server.services.release_boundary_service import (
    RELEASE_BOUNDARY_REPORT_PATH,
    collect_release_boundary_snapshot,
)

ASSIGNMENT_SELF_ITERATION_AGENT_IDS = {"workflow"}
ASSIGNMENT_SELF_ITERATION_SCHEDULE_PREFIX = "[持续迭代]"
ASSIGNMENT_SELF_ITERATION_SUCCESS_DELAY_MINUTES = 5
ASSIGNMENT_SELF_ITERATION_FAILURE_DELAY_MINUTES = 10
ASSIGNMENT_PM_WAKE_SCHEDULE_NAME = "pm持续唤醒 - workflow 主线巡检"
ASSIGNMENT_PM_WAKE_DELAY_MINUTES = 60
ASSIGNMENT_PM_WAKE_EXPECTED_ARTIFACT = "workflow-pm-wake-summary"
ASSIGNMENT_SELF_ITERATION_EXPECTED_ARTIFACT = "continuous-improvement-report.md"
ASSIGNMENT_SELF_ITERATION_VERSION_PLAN_PATH = "docs/workflow/governance/PM版本推进计划.md"
ASSIGNMENT_SELF_ITERATION_PLAN_LIVE_INDEX_PATH = "docs/workflow/governance/PM版本推进现场更新总览.md"
ASSIGNMENT_SELF_ITERATION_PLAN_LIVE_MONTHLY_HINT = "docs/workflow/governance/pm-version-live/YYYY-MM/现场更新总览.md"
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
    return {
        "schedule_name": _assignment_self_iteration_schedule_name(agent_id),
        "enabled": True,
        "assigned_agent_id": agent_id,
        "launch_summary": "\n".join(
            [
                "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 连续迭代。",
                "7x24 的业务目标是持续推进当前 active 版本，不是只维持存活或空转。",
                f"版本计划：{version_plan_path}",
                f"持续唤醒需求：{wake_requirement_path}",
                f"周期性工作泳道：{ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT}",
                *release_boundary_lines,
                f"上一轮 ticket: {ticket_id}",
                f"上一轮 node: {node_id}",
                f"上一轮结果: {summary_text}",
            ]
        ).strip(),
        "execution_checklist": "\n".join(
            [
                f"1. 先读取 `{version_plan_path}`，确认当前 active 版本、当前优先任务包与当前生命周期阶段：`{ASSIGNMENT_SELF_ITERATION_LIFECYCLE_TEXT}`。",
                f"2. 从 `{ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT}` 中选出本轮最高价值泳道；若当前 active 版本没有可执行任务，就先补 baseline、变更控制或下一个任务包，不允许空转。",
                f"2.1 若更新 `{version_plan_path}`，`4.6.1 当前现场更新` 只允许覆盖成一版最新有效快照；详细时序现场改写到 `{ASSIGNMENT_SELF_ITERATION_PLAN_LIVE_INDEX_PATH}` 指向的活动月份总览（路径模式：`{ASSIGNMENT_SELF_ITERATION_PLAN_LIVE_MONTHLY_HINT}`），不要在主计划正文继续追加 `10./11./12.` 这类流水编号。",
                "3. 先记录当前根仓同步快照里的 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`；这些字段只用于触发判断，不是本轮交付本身。",
                f"4. 若快照显示根仓未同步、本地工作区 dirty，或命中异常治理现场，就立即读取 `{RELEASE_BOUNDARY_REPORT_PATH}` 并进入发布边界收口模式；这轮必须先执行清理动作，不允许只复述计数。受支持动作包括：基于本机 `../workflow_code` 的 non-destructive 本地根仓收口、developer workspace bootstrap/refresh、helper stale `creating` / schedule / supervisor / runtime-upgrade 恢复。除非你明确要求，不要主动 `fetch/pull origin` 或拉 GitHub。",
                "5. 再检查 healthz、assignments、schedules、runs 与 `/api/runtime-upgrade/status`；当前 shell 是 PowerShell：不要使用 bash heredoc（如 `python - <<'PY'`），不要把 `scripts/*.ps1` 这类通配路径直接交给 `rg`，也不要手工猜测 run_id。",
                f"6. 继续检查 `/api/runtime-upgrade/status` 作为升级门禁真相；正式升级申请改由 `prod` supervisor 托管的 idle watcher 周期检查并发起，当前主线节点不要自己调用 `/api/runtime-upgrade/apply`。{ASSIGNMENT_SELF_UPGRADE_HINT}",
                "7. 在推进开发实现前，先明确本轮沿用的 baseline、需要变更控制的内容，以及基于哪条基线做后续测试与验收；优先推进当前版本里最高优先级且未完成的任务包，不要跳版抢做新功能。",
                f"8. 视情况给 {ASSIGNMENT_SELF_ITERATION_TEAMMATES_TEXT} 创建或续挂任务；更新 `.codex/memory/...` 时，在 `next` 明确写出下一次主线/保底触发时间，同时写清本轮泳道与生命周期阶段，并确保系统已经挂上下一轮可执行任务或唤醒计划。",
            ]
        ).strip(),
        "done_definition": "\n".join(
            [
                f"1. 当前活跃版本对应任务包有可交付结果，且版本计划 `{version_plan_path}` 已同步最新状态。",
                "2. 本轮明确记录了当前周期性泳道、生命周期阶段，以及是否发生 baseline/变更控制更新。",
                f"2.1 若本轮更新 `{version_plan_path}`，主计划正文中的 `4.6.1 当前现场更新` 仍保持单份最新快照；详细现场已写入 `{ASSIGNMENT_SELF_ITERATION_PLAN_LIVE_INDEX_PATH}` 指向的活动月份总览，而不是继续把正文写成长流水。",
                "3. 本轮显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`，且没有把它们误当成终态交付。",
                "4. 若本轮命中 dirty/ahead/阻塞，本轮已经先执行清理、切批、提交、推根仓或明确阻塞收口；不接受只汇报计数后继续等待状态自己恢复。",
                "5. 若本轮命中 7x24 异常治理现场，本轮已经执行受支持的治理收口动作，或明确写清为什么仍然 blocked，而不是只停在“workspace_path 不允许”；并附带验证证据。",
                "6. 如有需要，本轮已经给对应小伙伴挂好下一步任务或交接任务；若本轮没有新的 ready 任务，也必须保证下一次唤醒已经排上，7x24 连续推进不断链。",
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
    trigger_dt = base_dt + timedelta(minutes=max(1, int(ASSIGNMENT_PM_WAKE_DELAY_MINUTES)))
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
    return {
        "schedule_name": _assignment_pm_wake_schedule_name(agent_id),
        "enabled": True,
        "assigned_agent_id": agent_id,
        "launch_summary": "\n".join(
            [
                "作为保底接力入口，检查 prod 当前是否仍存在未来可执行的 [持续迭代] workflow 或 active 版本任务。",
                "7x24 的业务目标是持续推进当前 active 版本，不是只维持存活或空转。",
                f"先读版本计划：{version_plan_path}",
                f"再对照持续唤醒需求：{wake_requirement_path}",
                f"周期性工作泳道：{ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT}",
                *release_boundary_lines,
                f"最近上下文: {summary_text}",
            ]
        ).strip(),
        "execution_checklist": "\n".join(
            [
                f"1. 读取 `{version_plan_path}` 与 `{wake_requirement_path}`，确认当前 active 版本、任务包，以及所处生命周期阶段：`{ASSIGNMENT_SELF_ITERATION_LIFECYCLE_TEXT}`。",
                f"2. 从 `{ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT}` 中判断当前最该推进的泳道；若 active 版本没有可执行任务，立即补 baseline、变更控制或下一条当前版本任务。",
                f"2.1 若更新 `{version_plan_path}`，`4.6.1 当前现场更新` 只允许覆盖成一版最新有效快照；详细时序现场改写到 `{ASSIGNMENT_SELF_ITERATION_PLAN_LIVE_INDEX_PATH}` 指向的活动月份总览（路径模式：`{ASSIGNMENT_SELF_ITERATION_PLAN_LIVE_MONTHLY_HINT}`），不要在主计划正文继续追加 `10./11./12.` 这类流水编号。",
                "3. 先记录当前根仓同步快照里的 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`；这些字段只是触发信号，不是本轮交付本身。",
                f"3.1 若快照显示根仓未同步、本地工作区 dirty，或命中异常治理现场，就立即读取 `{RELEASE_BOUNDARY_REPORT_PATH}` 并切到发布边界收口模式；必须先执行清理动作，不允许只抄数字等状态自然恢复。只做受支持动作：基于本机 `../workflow_code` 的 non-destructive 本地根仓收口、developer workspace bootstrap/refresh、helper stale `creating` / schedule / supervisor / runtime-upgrade 恢复。除非你明确要求，不要主动 `fetch/pull origin` 或拉 GitHub。",
                "4. 检查 prod 当前 schedules、assignment graph、ready/running 节点、最近 runs 与 `/api/runtime-upgrade/status` 真相；当前 shell 是 PowerShell：不要使用 bash heredoc（如 `python - <<'PY'`），不要把 `scripts/*.ps1` 这类通配路径直接交给 `rg`，也不要手工猜测 run_id。",
                "5. 继续检查 `/api/runtime-upgrade/status` 作为升级门禁真相；正式升级申请改由 `prod` supervisor 托管的 idle watcher 周期检查并发起，当前巡检节点不要自己调用 `/api/runtime-upgrade/apply`。",
                f"5.1 {ASSIGNMENT_SELF_UPGRADE_HINT}",
                "6. 若 [持续迭代] workflow 没有未来入口，立即补一条未来可执行入口或当前版本任务。",
                f"7. 若测试/质量/开发/缺陷修复泳道缺少执行者，给 {ASSIGNMENT_SELF_ITERATION_TEAMMATES_TEXT} 创建或续挂任务。",
                "8. 更新 `.codex/memory/...` 时，在 `next` 明确写出下一次主线/保底触发时间，同时标注本轮泳道与生命周期阶段。",
                "9. 输出本次保底巡检结论、证据路径和下一次建议唤醒时间。",
            ]
        ).strip(),
        "done_definition": "\n".join(
            [
                "1. prod 至少保留一条未来可执行的 workflow 主线入口。",
                "2. 不能存在 `workflow` 已到时 ready 节点堆积但没有真实 live run 的假健康现场。",
                "3. 本次巡检结论明确写出 active 版本、泳道、生命周期阶段与证据。",
                f"3.1 若本轮更新 `{version_plan_path}`，主计划正文中的 `4.6.1 当前现场更新` 仍保持单份最新快照；详细现场已写入 `{ASSIGNMENT_SELF_ITERATION_PLAN_LIVE_INDEX_PATH}` 指向的活动月份总览，而不是继续把正文写成长流水。",
                "4. 本次巡检显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`，且没有把它们当成终态交付。",
                "5. 若发现这是上一轮遗留的 dirty/ahead 历史问题，本轮已经先处理这批历史 release boundary，执行清理或明确阻塞；不接受只汇报计数后空等。",
                "5.1 若本轮命中 7x24 异常治理现场，本轮已经执行受支持的治理收口动作，或明确写清为什么仍然 blocked，而不是只停在“workspace_path 不允许”。",
                "6. 若主链已断，本轮已经完成补链而不是只留口头说明。",
            ]
        ).strip(),
        "priority": "P1",
        "expected_artifact": ASSIGNMENT_PM_WAKE_EXPECTED_ARTIFACT,
        "delivery_mode": "none",
        "rule_sets": {
            "monthly": {"enabled": False},
            "weekly": {"enabled": False},
            "daily": {"enabled": False},
            "once": {"enabled": True, "date_times_text": next_trigger_at},
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
