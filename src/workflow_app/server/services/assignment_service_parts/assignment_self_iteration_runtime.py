from __future__ import annotations


ASSIGNMENT_SELF_ITERATION_AGENT_IDS = {"workflow"}
ASSIGNMENT_SELF_ITERATION_SCHEDULE_PREFIX = "[持续迭代]"
ASSIGNMENT_SELF_ITERATION_SUCCESS_DELAY_MINUTES = 15
ASSIGNMENT_SELF_ITERATION_FAILURE_DELAY_MINUTES = 30
ASSIGNMENT_PM_WAKE_SCHEDULE_NAME = "pm持续唤醒 - workflow 主线巡检"
ASSIGNMENT_PM_WAKE_DELAY_MINUTES = 30
ASSIGNMENT_PM_WAKE_EXPECTED_ARTIFACT = "workflow-pm-wake-summary"
ASSIGNMENT_SELF_ITERATION_EXPECTED_ARTIFACT = "continuous-improvement-report.md"
ASSIGNMENT_SELF_ITERATION_VERSION_PLAN_PATH = "docs/workflow/governance/PM版本推进计划.md"
ASSIGNMENT_SELF_ITERATION_WAKE_REQUIREMENT_PATH = "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md"


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


def _assignment_self_iteration_schedule_payload(
    *,
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
    return {
        "schedule_name": _assignment_self_iteration_schedule_name(agent_id),
        "enabled": True,
        "assigned_agent_id": agent_id,
        "launch_summary": "\n".join(
            [
                "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 连续迭代。",
                f"先读版本计划：{version_plan_path}",
                f"再对照持续唤醒需求：{wake_requirement_path}",
                f"上一轮 ticket: {ticket_id}",
                f"上一轮 node: {node_id}",
                f"上一轮结果: {summary_text}",
            ]
        ).strip(),
        "execution_checklist": "\n".join(
            [
                f"1. 先读取 `{version_plan_path}`，确认当前 active 版本和当前优先任务包。",
                f"2. 同时对照 `{wake_requirement_path}`，确保本轮推进不会把持续唤醒和 7x24 连续性做断。",
                "3. 再检查 healthz、dashboard、assignments、schedules、runs 的真实状态，不要只看前端表象。",
                "4. 优先推进当前 active 版本里最高优先级且未完成的工程质量/稳定性任务，不要跳版抢做新功能。",
                "5. 若当前任务包已完成，先更新版本计划状态，再挑同版本下一个 queued 包；只有当前版本出口门槛满足后才切到下一版本。",
                "6. 如需多人协作，给 workflow_devmate / workflow_testmate / workflow_qualitymate / workflow_bugmate 创建或续挂对应任务。",
                "7. 在代码工作区完成最小必要改动并跑命中改动面的验证。",
                "8. 输出本轮结论、证据路径，并确保系统已经挂上下一轮可执行任务或唤醒计划。",
            ]
        ).strip(),
        "done_definition": "\n".join(
            [
                f"1. 当前活跃版本对应任务包有可交付结果，且版本计划 `{version_plan_path}` 已同步最新状态。",
                "2. 本轮附带验证证据，而不是只给方向性描述。",
                "3. 如有需要，本轮已经给对应小伙伴挂好下一步任务或交接任务。",
                "4. 若本轮没有新的 ready 任务，也必须保证下一次唤醒已经排上，7x24 连续推进不断链。",
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


def _assignment_pm_wake_schedule_payload(
    *,
    agent_id: str,
    result_summary: str,
    next_trigger_at: str,
) -> dict[str, Any]:
    summary_text = _short_assignment_text(result_summary, 240) or "检查 prod 当前是否仍保留未来可执行入口，并在断链时立即补链。"
    version_plan_path = ASSIGNMENT_SELF_ITERATION_VERSION_PLAN_PATH
    wake_requirement_path = ASSIGNMENT_SELF_ITERATION_WAKE_REQUIREMENT_PATH
    return {
        "schedule_name": _assignment_pm_wake_schedule_name(agent_id),
        "enabled": True,
        "assigned_agent_id": agent_id,
        "launch_summary": "\n".join(
            [
                "作为保底接力入口，检查 prod 当前是否仍存在未来可执行的 [持续迭代] workflow 或 active 版本任务。",
                f"先读版本计划：{version_plan_path}",
                f"再对照持续唤醒需求：{wake_requirement_path}",
                f"最近上下文: {summary_text}",
            ]
        ).strip(),
        "execution_checklist": "\n".join(
            [
                f"1. 读取 `{version_plan_path}` 与 `{wake_requirement_path}`。",
                "2. 检查 prod 当前 schedules、assignment graph、ready/running 节点和最近 runs 真相。",
                "3. 若 [持续迭代] workflow 没有未来入口，立即补一条未来可执行入口或当前版本任务。",
                "4. 输出本次保底巡检结论、证据路径和下一次建议唤醒时间。",
            ]
        ).strip(),
        "done_definition": "\n".join(
            [
                "1. prod 至少保留一条未来可执行的 workflow 主线入口。",
                "2. 本次巡检结论和证据可追溯。",
                "3. 若主链已断，本轮已经完成补链而不是只留口头说明。",
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
    return {
        "queued": True,
        "schedule_id": str(data.get("schedule_id") or "").strip(),
        "next_trigger_at": next_trigger_at,
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
    backup = _assignment_queue_pm_wake_schedule(
        root,
        agent_id=agent_id,
        result_summary=result_summary,
        primary_next_trigger_at=next_trigger_at,
    )
    return {
        "queued": True,
        "schedule_id": str(data.get("schedule_id") or "").strip(),
        "next_trigger_at": next_trigger_at,
        "agent_id": agent_id,
        "backup_schedule_id": str(backup.get("schedule_id") or "").strip(),
        "backup_next_trigger_at": str(backup.get("next_trigger_at") or "").strip(),
    }
