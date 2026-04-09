from __future__ import annotations

import json
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from workflow_app.server.services.release_boundary_service import (
    RELEASE_BOUNDARY_REPORT_PATH,
    collect_release_boundary_snapshot,
    format_release_boundary_prompt_lines,
)

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
ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT = (
    "UCD/设计优化、测试探测、工程质量探测、需求分析、架构优化、功能开发、高价值功能探索"
)
ASSIGNMENT_SELF_ITERATION_LIFECYCLE_TEXT = (
    "需求提出 -> 澄清/评审 -> 形成基线 -> 变更控制 -> 开发实现 -> 基于基线测试 -> 验收 -> 归档回溯"
)
ASSIGNMENT_SELF_ITERATION_TEAMMATES_TEXT = (
    "workflow_devmate / workflow_testmate / workflow_qualitymate / workflow_bugmate"
)
ASSIGNMENT_SELF_UPGRADE_OPERATOR = "assignment-self-upgrade"
ASSIGNMENT_SELF_UPGRADE_TIMEOUT_SECONDS = 8.0
ASSIGNMENT_SELF_UPGRADE_HINT = (
    "若只剩当前主线/巡检节点占用 running 槽，可带 `exclude_assignment_ticket_id` / "
    "`exclude_assignment_node_id` 再复核 `/api/runtime-upgrade/status`，确认后直接调用 "
    "`/api/runtime-upgrade/apply`。"
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
    release_boundary = collect_release_boundary_snapshot(runtime_root=root) if root is not None else {}
    release_boundary_lines = format_release_boundary_prompt_lines(release_boundary)
    return {
        "schedule_name": _assignment_self_iteration_schedule_name(agent_id),
        "enabled": True,
        "assigned_agent_id": agent_id,
        "launch_summary": "\n".join(
            [
                "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 连续迭代。",
                "7x24 的业务目标是持续推进当前 active 版本，不是只维持存活或空转。",
                f"先读版本计划：{version_plan_path}",
                f"再对照持续唤醒需求：{wake_requirement_path}",
                f"周期性工作泳道：{ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT}",
                *release_boundary_lines,
                f"上一轮 ticket: {ticket_id}",
                f"上一轮 node: {node_id}",
                f"上一轮结果: {summary_text}",
            ]
        ).strip(),
        "execution_checklist": "\n".join(
            [
                f"1. 先读取 `{version_plan_path}`，确认当前 active 版本和当前优先任务包。",
                f"2. 同时对照 `{wake_requirement_path}`，先定位当前生命周期阶段：`{ASSIGNMENT_SELF_ITERATION_LIFECYCLE_TEXT}`。",
                f"3. 从 `{ASSIGNMENT_SELF_ITERATION_PERIODIC_LANES_TEXT}` 中选出本轮最高价值泳道；若当前 active 版本没有可执行任务，就先补 baseline、变更控制或下一个任务包，不允许空转。",
                "4. 先记录当前根仓同步快照里的 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`，不要只写“继续收 Git 边界”。",
                f"4.1 若快照显示根仓未同步或本地工作区 dirty，就立即读取 `{RELEASE_BOUNDARY_REPORT_PATH}` 并进入发布边界收口模式：先冻结同工作区新增实现，按小批次验证并推回 `../workflow_code/main`。",
                "4.2 在至少一个已验证小批次推回根仓，或明确写出阻塞原因前，不要继续扩当前同工作区功能面；除非 `prod` 主链断裂、升级止血或高优先事故。",
                "5. 再检查 healthz、dashboard、assignments、schedules、runs 的真实状态，不要只看前端表象。",
                "6. 检查 `/api/runtime-upgrade/status`；若 `can_upgrade=true` 且当前无运行中任务，直接调用 `/api/runtime-upgrade/apply` 完成无痛升级，并在重连后继续推进。",
                f"6.1 {ASSIGNMENT_SELF_UPGRADE_HINT}",
                "7. 在推进开发实现前，先明确本轮沿用的 baseline、需要变更控制的内容，以及基于哪条基线做后续测试与验收。",
                "8. 优先推进当前 active 版本里最高优先级且未完成的任务包，不要跳版抢做新功能。",
                "9. 若当前任务包已完成，先更新版本计划状态，再挑同版本下一个 queued 包；只有当前版本出口门槛满足后才切到下一版本。",
                f"10. 定期评估并派发小伙伴：对开发/测试/质量/缺陷修复相关工作，给 {ASSIGNMENT_SELF_ITERATION_TEAMMATES_TEXT} 创建或续挂对应任务，不要长期让协作链闲置。",
                "11. 在代码工作区完成最小必要改动，并跑命中改动面的验证、基于基线测试和必要验收。",
                "12. 更新 `.codex/memory/...` 时，在 `next` 明确写出下一次主线/保底触发时间，同时写清本轮泳道与生命周期阶段。",
                "13. 输出本轮结论、证据路径，并确保系统已经挂上下一轮可执行任务或唤醒计划。",
            ]
        ).strip(),
        "done_definition": "\n".join(
            [
                f"1. 当前活跃版本对应任务包有可交付结果，且版本计划 `{version_plan_path}` 已同步最新状态。",
                "2. 本轮明确记录了当前周期性泳道、生命周期阶段，以及是否发生 baseline/变更控制更新。",
                "3. 本轮显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`。",
                "4. 若 release boundary 未收口，本轮至少完成了一个已验证小批次推回根仓，或明确写清阻塞原因与下一批次。",
                "5. 本轮附带验证证据，而不是只给方向性描述。",
                "6. 如有需要，本轮已经给对应小伙伴挂好下一步任务或交接任务。",
                "7. 若本轮没有新的 ready 任务，也必须保证下一次唤醒已经排上，7x24 连续推进不断链。",
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
    release_boundary = collect_release_boundary_snapshot(runtime_root=root) if root is not None else {}
    release_boundary_lines = format_release_boundary_prompt_lines(release_boundary)
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
                "3. 先记录当前根仓同步快照里的 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`。",
                f"3.1 若快照显示根仓未同步或本地工作区 dirty，就立即读取 `{RELEASE_BOUNDARY_REPORT_PATH}` 并切到发布边界收口模式：先冻结同工作区新增实现，优先恢复小步推根仓节奏。",
                "4. 检查 prod 当前 schedules、assignment graph、ready/running 节点、最近 runs 与 `/api/runtime-upgrade/status` 真相。",
                "4.1 若看到 `workflow` 已到时的 ready 节点堆积、`running_task_count=0`，或 recent trigger/message 出现 `assigned agent already has running node` 但找不到真实 live workflow run.json/events.log，必须判定为断链/假健康，立即补链或重派发，不能按“还有 future 入口”算通过。",
                "5. 若 `can_upgrade=true` 且当前无运行中任务，直接调用 `/api/runtime-upgrade/apply` 完成无痛升级，再继续巡检。",
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
                "4. 本次巡检显式记录了 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`。",
                "5. 若主链已断，本轮已经完成补链而不是只留口头说明。",
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


def _assignment_runtime_upgrade_json_request(
    *,
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = ASSIGNMENT_SELF_UPGRADE_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
    url = f"{str(base_url or '').rstrip('/')}{str(path or '').strip()}"
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=data,
        headers=headers,
        method=str(method or "GET").strip().upper() or "GET",
    )
    try:
        with urllib_request.urlopen(request, timeout=max(1.0, float(timeout_seconds or 0.0))) as response:
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
            raw = response.read().decode("utf-8", "replace")
    except urllib_error.HTTPError as exc:
        status = int(exc.code or 0)
        raw = exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return 0, {
            "ok": False,
            "error": str(exc),
            "code": "runtime_upgrade_loopback_request_failed",
        }
    try:
        payload_data = json.loads(raw) if raw else {}
    except Exception:
        payload_data = {
            "ok": False,
            "error": "runtime upgrade loopback response invalid json",
            "code": "runtime_upgrade_loopback_invalid_json",
            "raw_body": raw[:1000],
        }
    if not isinstance(payload_data, dict):
        payload_data = {
            "ok": False,
            "error": "runtime upgrade loopback response payload invalid",
            "code": "runtime_upgrade_loopback_invalid_payload",
        }
    return status, payload_data


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
    if not base_url:
        return {
            "requested": False,
            "suppress_dispatch": False,
            "reason": "runtime_upgrade_loopback_unavailable",
        }
    ticket_id = str(task_record.get("ticket_id") or "").strip()
    node_id = str(node_record.get("node_id") or "").strip()
    query = urllib_parse.urlencode(
        {
            "exclude_assignment_ticket_id": ticket_id,
            "exclude_assignment_node_id": node_id,
        }
    )
    status_code, status_payload = _assignment_runtime_upgrade_json_request(
        base_url=base_url,
        method="GET",
        path=f"/api/runtime-upgrade/status?{query}",
    )
    if status_code != 200 or not bool((status_payload or {}).get("ok")):
        return {
            "requested": False,
            "suppress_dispatch": False,
            "reason": "runtime_upgrade_status_unavailable",
            "status_code": int(status_code or 0),
            "status_payload": status_payload,
        }
    request_pending = bool((status_payload or {}).get("request_pending"))
    if request_pending:
        return {
            "requested": False,
            "suppress_dispatch": True,
            "reason": "runtime_upgrade_already_requested",
            "status_code": int(status_code or 0),
            "status_payload": status_payload,
            "current_version": str((status_payload or {}).get("current_version") or "").strip(),
            "candidate_version": str((status_payload or {}).get("candidate_version") or "").strip(),
        }
    if not bool((status_payload or {}).get("can_upgrade")):
        return {
            "requested": False,
            "suppress_dispatch": False,
            "reason": str((status_payload or {}).get("blocking_reason_code") or "runtime_upgrade_blocked").strip()
            or "runtime_upgrade_blocked",
            "status_code": int(status_code or 0),
            "status_payload": status_payload,
            "current_version": str((status_payload or {}).get("current_version") or "").strip(),
            "candidate_version": str((status_payload or {}).get("candidate_version") or "").strip(),
        }
    apply_body = {
        "operator": ASSIGNMENT_SELF_UPGRADE_OPERATOR,
        "exclude_assignment_ticket_id": ticket_id,
        "exclude_assignment_node_id": node_id,
    }
    apply_status, apply_payload = _assignment_runtime_upgrade_json_request(
        base_url=base_url,
        method="POST",
        path="/api/runtime-upgrade/apply",
        payload=apply_body,
    )
    requested = int(apply_status or 0) == 202 and bool((apply_payload or {}).get("ok"))
    apply_code = str((apply_payload or {}).get("code") or "").strip()
    suppress_dispatch = requested or apply_code == "runtime_upgrade_already_requested" or bool(
        (apply_payload or {}).get("request_pending")
    )
    return {
        "requested": requested,
        "suppress_dispatch": bool(suppress_dispatch),
        "reason": "prod_upgrade_requested" if requested else (apply_code or "runtime_upgrade_apply_failed"),
        "base_url": base_url,
        "ticket_id": ticket_id,
        "node_id": node_id,
        "status_code": int(status_code or 0),
        "apply_status": int(apply_status or 0),
        "current_version": str((status_payload or {}).get("current_version") or "").strip(),
        "candidate_version": str((status_payload or {}).get("candidate_version") or "").strip(),
        "status_payload": status_payload,
        "apply_payload": apply_payload,
    }
