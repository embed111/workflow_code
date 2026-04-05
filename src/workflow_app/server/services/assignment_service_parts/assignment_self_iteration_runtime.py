from __future__ import annotations


ASSIGNMENT_SELF_ITERATION_AGENT_IDS = {"workflow"}
ASSIGNMENT_SELF_ITERATION_SCHEDULE_PREFIX = "[持续迭代]"
ASSIGNMENT_SELF_ITERATION_SUCCESS_DELAY_MINUTES = 15
ASSIGNMENT_SELF_ITERATION_FAILURE_DELAY_MINUTES = 30
ASSIGNMENT_SELF_ITERATION_EXPECTED_ARTIFACT = "continuous-improvement-report.md"


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
    return {
        "schedule_name": _assignment_self_iteration_schedule_name(agent_id),
        "enabled": True,
        "assigned_agent_id": agent_id,
        "launch_summary": "\n".join(
            [
                "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 工程质量提升。",
                f"上一轮 ticket: {ticket_id}",
                f"上一轮 node: {node_id}",
                f"上一轮结果: {summary_text}",
            ]
        ).strip(),
        "execution_checklist": "\n".join(
            [
                "1. 先检查 healthz、dashboard、assignments、schedules 的真实状态，不要只看前端表象。",
                "2. 识别当前最影响 7x24 连续运行、工程质量或可观测性的一个最高优先级问题。",
                "3. 在代码工作区完成最小必要改动并跑对应验证。",
                "4. 输出本轮结论、证据路径和下一轮应继续推进的点。",
            ]
        ).strip(),
        "done_definition": "给出可交付的改进结果和验证证据，并确保系统会继续排上下一轮可执行任务。",
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


def _assignment_find_self_iteration_schedule(root: Path, *, agent_id: str) -> dict[str, Any]:
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
                _assignment_self_iteration_schedule_name(agent_id),
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


def _assignment_self_iteration_next_trigger_at(*, success: bool) -> str:
    from datetime import timedelta

    delay_minutes = (
        ASSIGNMENT_SELF_ITERATION_SUCCESS_DELAY_MINUTES
        if success
        else ASSIGNMENT_SELF_ITERATION_FAILURE_DELAY_MINUTES
    )
    trigger_dt = now_local() + timedelta(minutes=max(1, int(delay_minutes)))
    return trigger_dt.isoformat(timespec="seconds")


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
        existing_next = str(existing.get("next_trigger_at") or "").strip()
        if existing_next and existing_next > now_local().isoformat(timespec="seconds") and existing_next < next_trigger_at:
            next_trigger_at = existing_next
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
    return {
        "queued": True,
        "schedule_id": str(data.get("schedule_id") or "").strip(),
        "next_trigger_at": next_trigger_at,
        "agent_id": agent_id,
    }
