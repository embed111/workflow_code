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
SCHEDULE_PM_GOVERNANCE_README_PATH = "pm/README.md"
SCHEDULE_MASTER_PLAN_PATH = "pm/PM版本推进计划.md"
SCHEDULE_VERSION_PLAN_PATH = "pm/PM当前版本计划.md"
SCHEDULE_DAILY_TASK_PATH = "pm/PM每日任务清单.md"
SCHEDULE_DAILY_HISTORY_HINT = "pm/daily-execution-history/YYYY-MM-DD.md"
SCHEDULE_VERSION_HISTORY_HINT = "pm/versions/<active_version>/history/YYYY-MM/YYYY-MM-DD.md"
SCHEDULE_WAKE_REQUIREMENT_PATH = "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md"
SCHEDULE_SELF_UPGRADE_HINT = (
    "正式升级改由 `prod` supervisor 托管的 idle watcher 周期检查并发起；"
    "当前主线/巡检节点不要再通过自排除方式自己触发 `/api/runtime-upgrade/apply`。"
)


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
                    "保底巡检不代替主线做整轮开发；只有主链断了或当前窗口明确要求兜底时，才补链或接管异常治理。",
                    f"先读 PM 治理入口：{SCHEDULE_PM_GOVERNANCE_README_PATH}",
                    f"必读：{SCHEDULE_MASTER_PLAN_PATH} / {SCHEDULE_VERSION_PLAN_PATH} / `{SCHEDULE_VERSION_PLAN_PATH}` 中 `active_version_file` 指向的版本文件 / {SCHEDULE_DAILY_TASK_PATH} / {SCHEDULE_WAKE_REQUIREMENT_PATH}",
                    (
                        f"今日例行任务是否已完成，看 `{SCHEDULE_DAILY_HISTORY_HINT}`；"
                        "每日任务现在只包含“每日 1 次系统 7x24 运维质量检查”和“团队内每个小伙伴每日学习提示”。"
                    ),
                ]
            ).strip(),
            "execution_checklist": "\n".join(
                [
                    f"1. 按 `{SCHEDULE_PM_GOVERNANCE_README_PATH} -> {SCHEDULE_MASTER_PLAN_PATH} -> {SCHEDULE_VERSION_PLAN_PATH} -> {SCHEDULE_VERSION_PLAN_PATH} 中 active_version_file 指向的版本文件 -> {SCHEDULE_DAILY_TASK_PATH} -> {SCHEDULE_WAKE_REQUIREMENT_PATH}` 的顺序补齐上下文。",
                    f"2. 先检查 `{SCHEDULE_DAILY_HISTORY_HINT}` 对应的今日日文件是否存在；若不存在，需要在当天合适窗口补做今天唯一一轮每日任务并落盘。",
                    "3. 先判断当前版本引用和当前活跃版本文件是否要求暂停、治理调整或仅观察；若是，默认不补新主线，只报告现场并保持暂停。",
                    "4. 检查 `/healthz`、`/api/status`、`/api/schedules`、`/api/runtime-upgrade/status`；必要时再看 `assignment graph / status-detail / run.json / events.log`。",
                    "5. 先记录 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`；若命中 dirty/ahead/异常治理现场，先处理 release boundary。",
                    f"6. 正式升级申请改由 `prod` supervisor 托管的 idle watcher 周期检查并发起，当前巡检节点不要自己调用 `/api/runtime-upgrade/apply`。{SCHEDULE_SELF_UPGRADE_HINT}",
                    "7. 只有主链断了或当前版本引用/当前活跃版本文件明确允许时，才补新的 [持续迭代] workflow 入口；是否派发或恢复小伙伴，也要按版本文件里的每轮必查项判断。",
                    f"8. 当天的版本推进、后移和后续版本排期判断先写 `{SCHEDULE_VERSION_HISTORY_HINT}`；只有主判断变化时，才更新 `pm/PM当前版本计划.md` 的当前状态快照。",
                    "9. 若发现高杠杆新功能或低维护价值重构项，先记录并明确它进入哪个后续版本，不要借巡检窗口把当前版本加胖。",
                    "10. 更细现场写入 `logs/runs/*.md` 或今日日记，不要把主计划正文写成长流水。",
                    "11. 更新 `.codex/memory/...` 时，在 `next` 明确写出下一次主线/保底触发时间；记忆库每一轮都要更新。",
                ]
            ).strip(),
            "done_definition": "\n".join(
                [
                    "1. 本次巡检已经明确回答：当前是继续推进、保持暂停，还是需要兜底补链。",
                    f"2. 若今日 `{SCHEDULE_DAILY_HISTORY_HINT}` 原本不存在，本轮已经补齐当天每日执行结果，或明确写清为什么仍未完成。",
                    "3. 若当前窗口允许推进，prod 至少保留一条未来可执行的 workflow 主线入口。",
                    "4. 本次巡检结论和证据可追溯。",
                    "5. 若发现上一轮遗留的 dirty/ahead 历史问题，本轮已经优先处理这批 release boundary，或明确写清阻塞原因。",
                ]
            ).strip(),
        }
    if artifact == SCHEDULE_SELF_ITERATION_EXPECTED_ARTIFACT:
        return {
            "schedule_name": f"[持续迭代] {agent_id}",
            "launch_summary": "\n".join(
                [
                    "上一轮任务已经结束，请继续作为 workflow 的长期负责人推进 7x24 连续迭代。",
                    "本轮先服务当前 active 版本与当前窗口任务，不空转，也不把保底巡检职责混进主线。",
                    f"先读 PM 治理入口：{SCHEDULE_PM_GOVERNANCE_README_PATH}",
                    f"必读：{SCHEDULE_MASTER_PLAN_PATH} / {SCHEDULE_VERSION_PLAN_PATH} / `{SCHEDULE_VERSION_PLAN_PATH}` 中 `active_version_file` 指向的版本文件 / {SCHEDULE_DAILY_TASK_PATH} / {SCHEDULE_WAKE_REQUIREMENT_PATH}",
                    (
                        f"今日例行任务是否已完成，看 `{SCHEDULE_DAILY_HISTORY_HINT}`；"
                        "每日任务现在只包含“每日 1 次系统 7x24 运维质量检查”和“团队内每个小伙伴每日学习提示”。"
                    ),
                ]
            ).strip(),
            "execution_checklist": "\n".join(
                [
                    f"1. 按 `{SCHEDULE_PM_GOVERNANCE_README_PATH} -> {SCHEDULE_MASTER_PLAN_PATH} -> {SCHEDULE_VERSION_PLAN_PATH} -> {SCHEDULE_VERSION_PLAN_PATH} 中 active_version_file 指向的版本文件 -> {SCHEDULE_DAILY_TASK_PATH} -> {SCHEDULE_WAKE_REQUIREMENT_PATH}` 的顺序补齐上下文。",
                    f"2. 先检查 `{SCHEDULE_DAILY_HISTORY_HINT}` 对应的今日日文件是否存在；若不存在，需要在本轮合适窗口完成今天唯一一轮每日任务并落盘。",
                    "3. 先确认当前窗口属于继续推进、异常治理还是治理调整；若当前版本引用或当前活跃版本文件写明暂停或仅观察，则不要自动扩面。",
                    "4. 再检查 `/healthz`、`/api/status`、`/api/schedules`、`/api/runtime-upgrade/status`；必要时再看 `status-detail / run.json / events.log`。",
                    "5. 先记录 `root_sync_state / ahead_count / dirty_tracked_count / untracked_count / push_block_reason / next_push_batch`；若命中 dirty/ahead/异常治理现场，先处理 release boundary。",
                    f"6. 正式升级申请改由 `prod` supervisor 托管的 idle watcher 周期检查并发起，当前主线节点不要自己调用 `/api/runtime-upgrade/apply`。{SCHEDULE_SELF_UPGRADE_HINT}",
                    "7. 按 `质量 / 效率 / 工作区小伙伴维护 = 4 / 4 / 2` 判断当前重点，只推进当前活跃版本文件里具体需求点的最高优先事项。",
                    "8. 每轮都要检查是否需要给小伙伴创建、续挂、恢复或调整任务；这属于 PM 主线每轮必查项，不属于每日任务。",
                    f"9. 当天的版本推进、后移和后续版本排期判断先写 `{SCHEDULE_VERSION_HISTORY_HINT}`；只有主判断变化时，才更新 `pm/PM当前版本计划.md` 的当前状态快照。",
                    "10. 若发现高杠杆新功能或低维护价值重构项，先记录并明确它进入哪个后续版本，不要继续把当前版本加胖。",
                    "11. 更细现场写入 `logs/runs/*.md` 或今日日记。",
                    "12. 更新 `.codex/memory/...` 时，在 `next` 明确写出下一次主线/保底触发时间；记忆库每一轮都要更新。",
                ]
            ).strip(),
            "done_definition": "\n".join(
                [
                    "1. 当前窗口最高优先事项有可交付结果，或已经被明确标记为 blocked。",
                    f"2. 若今日 `{SCHEDULE_DAILY_HISTORY_HINT}` 原本不存在，本轮已经补齐当天每日执行结果，或明确写清为什么仍未完成。",
                    "3. 本轮附带验证证据，而不是只给方向性描述。",
                    f"4. 当天的版本推进、后移和后续版本排期判断已写入 `{SCHEDULE_VERSION_HISTORY_HINT}`；只有主判断变化时才更新 `pm/PM当前版本计划.md` 的当前状态快照。",
                    "5. 若本轮存在已验证代码改动，本轮结束前已经完成当前工作区 `commit / push / 根仓同步`，或明确写清阻塞原因。",
                    "6. 若当前窗口不是暂停/治理调整，本轮结束时至少还保留一个后续出口；若当前窗口是暂停/治理调整，则不得误续挂新的主线推进任务。",
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
