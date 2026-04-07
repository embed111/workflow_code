from __future__ import annotations

import sqlite3
from typing import Any

SCHEDULE_TEXT_FIELDS = ("schedule_name", "launch_summary", "execution_checklist", "done_definition")
SCHEDULE_SNAPSHOT_FIELD_MAP = {
    "schedule_name": "schedule_name_snapshot",
    "launch_summary": "launch_summary_snapshot",
    "execution_checklist": "execution_checklist_snapshot",
    "done_definition": "done_definition_snapshot",
}
SCHEDULE_SELF_ITERATION_EXPECTED_ARTIFACT = "continuous-improvement-report.md"
SCHEDULE_PM_WAKE_EXPECTED_ARTIFACT = "workflow-pm-wake-summary"
SCHEDULE_VERSION_PLAN_PATH = "docs/workflow/governance/PM版本推进计划.md"
SCHEDULE_WAKE_REQUIREMENT_PATH = "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md"


def _schedule_text_needs_repair(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if "\ufffd" in text:
        return True
    question_count = text.count("?")
    if question_count <= 0:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return False
    compact = "".join(ch for ch in text if not ch.isspace())
    return question_count >= 3 and (question_count * 4) >= max(1, len(compact))


def _normalize_text_for_schedule_display(value: Any, *, max_len: int = 8000) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > max_len:
        text = text[:max_len]
    if "\ufffd" in text:
        return ""
    if any(ord(ch) >= 128 for ch in text):
        # Try to recover from common mojibake path: utf-8 bytes decoded as latin-1/cp1252.
        for codec in ("latin-1", "cp1252"):
            try:
                repaired = text.encode(codec, errors="strict").decode("utf-8", errors="strict").strip()
            except Exception:
                continue
            if repaired and repaired != text:
                text = repaired[:max_len]
                break
    if _schedule_text_needs_repair(text):
        return ""
    return text


def _schedule_template_texts(*, expected_artifact: Any, assigned_agent_id: Any) -> dict[str, str]:
    artifact = str(expected_artifact or "").strip()
    agent_id = str(assigned_agent_id or "").strip() or "workflow"
    if artifact == SCHEDULE_PM_WAKE_EXPECTED_ARTIFACT:
        schedule_name = (
            "pm持续唤醒 - workflow 主线巡检"
            if agent_id.lower() == "workflow"
            else f"pm持续唤醒 - {agent_id} 主线巡检"
        )
        return {
            "schedule_name": schedule_name,
            "launch_summary": "\n".join(
                [
                    "作为保底接力入口，检查 prod 当前是否仍存在未来可执行的 [持续迭代] workflow 或 active 版本任务。",
                    f"先读版本计划：{SCHEDULE_VERSION_PLAN_PATH}",
                    f"再对照持续唤醒需求：{SCHEDULE_WAKE_REQUIREMENT_PATH}",
                    "最近上下文: 主链触发未成功，需要保底巡检续挂。",
                ]
            ).strip(),
            "execution_checklist": "\n".join(
                [
                    f"1. 读取 `{SCHEDULE_VERSION_PLAN_PATH}` 与 `{SCHEDULE_WAKE_REQUIREMENT_PATH}`。",
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
        }
    if artifact == SCHEDULE_SELF_ITERATION_EXPECTED_ARTIFACT:
        return {
            "schedule_name": f"[持续迭代] {agent_id}",
            "launch_summary": "\n".join(
                [
                    "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 连续迭代。",
                    f"先读版本计划：{SCHEDULE_VERSION_PLAN_PATH}",
                    f"再对照持续唤醒需求：{SCHEDULE_WAKE_REQUIREMENT_PATH}",
                    "上一轮结果: 当前需要继续推进 active 版本里最高优先的工程质量/稳定性任务。",
                ]
            ).strip(),
            "execution_checklist": "\n".join(
                [
                    f"1. 先读取 `{SCHEDULE_VERSION_PLAN_PATH}`，确认当前 active 版本和当前优先任务包。",
                    f"2. 同时对照 `{SCHEDULE_WAKE_REQUIREMENT_PATH}`，确保本轮推进不会把持续唤醒和 7x24 连续性做断。",
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
                    f"1. 当前活跃版本对应任务包有可交付结果，且版本计划 `{SCHEDULE_VERSION_PLAN_PATH}` 已同步最新状态。",
                    "2. 本轮附带验证证据，而不是只给方向性描述。",
                    "3. 如有需要，本轮已经给对应小伙伴挂好下一步任务或交接任务。",
                    "4. 若本轮没有新的 ready 任务，也必须保证下一次唤醒已经排上，7x24 连续推进不断链。",
                ]
            ).strip(),
        }
    return {}


def _load_schedule_snapshot_text_fallbacks(
    conn: sqlite3.Connection,
    schedule_id: str,
    *,
    cache: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    schedule_key = str(schedule_id or "").strip()
    if not schedule_key:
        return {}
    if cache is not None and schedule_key in cache:
        return dict(cache[schedule_key])
    rows = conn.execute(
        """
        SELECT schedule_name_snapshot,launch_summary_snapshot,execution_checklist_snapshot,done_definition_snapshot
        FROM schedule_trigger_instances
        WHERE schedule_id=?
        ORDER BY planned_trigger_at DESC, created_at DESC
        LIMIT 20
        """,
        (schedule_key,),
    ).fetchall()
    repaired: dict[str, str] = {}
    for row in rows:
        for field_name, snapshot_field in SCHEDULE_SNAPSHOT_FIELD_MAP.items():
            if repaired.get(field_name):
                continue
            normalized = _normalize_text_for_schedule_display(row[snapshot_field])
            if normalized:
                repaired[field_name] = normalized
    if cache is not None:
        cache[schedule_key] = dict(repaired)
    return repaired


def _repair_schedule_text_fields(
    item: sqlite3.Row | dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    snapshot_cache: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    raw = dict(item or {})
    schedule_id = str(raw.get("schedule_id") or "").strip()
    expected_artifact = raw.get("expected_artifact") or raw.get("expected_artifact_snapshot")
    assigned_agent_id = raw.get("assigned_agent_id") or raw.get("assigned_agent_id_snapshot")
    snapshot_fallbacks = (
        _load_schedule_snapshot_text_fallbacks(conn, schedule_id, cache=snapshot_cache)
        if conn is not None and schedule_id
        else {}
    )
    template = _schedule_template_texts(
        expected_artifact=expected_artifact,
        assigned_agent_id=assigned_agent_id,
    )
    repaired: dict[str, str] = {}
    for field_name in SCHEDULE_TEXT_FIELDS:
        normalized = _normalize_text_for_schedule_display(raw.get(field_name))
        if normalized:
            repaired[field_name] = normalized
            continue
        repaired[field_name] = (
            str(snapshot_fallbacks.get(field_name) or "").strip()
            or str(template.get(field_name) or "").strip()
        )
    return repaired


def _load_schedule_plan_text_fallbacks(
    conn: sqlite3.Connection,
    schedule_id: str,
    *,
    plan_cache: dict[str, dict[str, str]] | None = None,
    snapshot_cache: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    schedule_key = str(schedule_id or "").strip()
    if not schedule_key:
        return {}
    if plan_cache is not None and schedule_key in plan_cache:
        return dict(plan_cache[schedule_key])
    row = conn.execute(
        """
        SELECT schedule_id,schedule_name,launch_summary,execution_checklist,done_definition,expected_artifact,assigned_agent_id
        FROM schedule_plans
        WHERE schedule_id=?
        LIMIT 1
        """,
        (schedule_key,),
    ).fetchone()
    repaired = (
        _repair_schedule_text_fields(row, conn=conn, snapshot_cache=snapshot_cache)
        if row is not None
        else {}
    )
    if plan_cache is not None:
        plan_cache[schedule_key] = dict(repaired)
    return repaired


def _coerce_schedule_body_text_fields(
    body: dict[str, Any],
    *,
    existing: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(body or {})
    current = dict(existing or {})
    for field_name in SCHEDULE_TEXT_FIELDS:
        if field_name not in payload:
            continue
        candidate = str(payload.get(field_name) or "").strip()
        if not candidate or not _schedule_text_needs_repair(candidate):
            continue
        fallback = str(current.get(field_name) or "").strip()
        if fallback:
            payload[field_name] = fallback
    return payload
