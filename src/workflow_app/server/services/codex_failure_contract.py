from __future__ import annotations

import re
from typing import Any


_FAILURE_CODE_EXACT = {
    "codex_command_not_found": "environment_unavailable",
    "workspace_missing": "workspace_missing",
    "workspace_root_missing": "workspace_missing",
    "analyst_workspace_not_found": "workspace_missing",
    "agents_md_not_found": "input_missing",
    "target_agents_path_out_of_scope": "out_of_scope",
    "agent_policy_out_of_scope": "out_of_scope",
    "codex_exec_timeout": "execution_timeout",
    "codex_stream_disconnected": "stream_disconnected",
    "codex_output_invalid_json": "result_invalid",
    "codex_result_missing": "result_missing",
    "release_review_report_incomplete": "contract_invalid",
    "release_review_metadata_conflict": "state_blocked",
    "role_creation_retry_running": "state_blocked",
    "role_creation_retry_no_pending_messages": "state_blocked",
    "role_creation_session_completed": "state_blocked",
    "role_creation_session_not_found": "input_missing",
    "git_status_failed": "publish_failed",
    "git_add_failed": "publish_failed",
    "git_commit_failed": "publish_failed",
    "git_tag_failed": "publish_failed",
    "release_note_invalid": "publish_failed",
    "release_version_not_found_after_publish": "publish_failed",
    "publish_failed": "publish_failed",
    "assignment_run_not_found": "input_missing",
    "assignment_execution_failed": "execution_failed",
    "policy_contract_invalid": "contract_invalid",
    "policy_extract_failed": "execution_failed",
    "release_review_report_failed": "review_failed",
    "role_creation_analysis_failed": "execution_failed",
}

_FAILURE_CODE_PREFIXES = (
    ("codex_exec_failed_exit_", "execution_failed"),
    ("codex_exec_exception", "execution_exception"),
    ("git_", "publish_failed"),
)

_FAILURE_STAGE_EXACT = {
    "agents_md_not_found": "input_prepare",
    "target_agents_path_out_of_scope": "scope_validate",
    "agent_policy_out_of_scope": "scope_validate",
    "workspace_missing": "workspace_prepare",
    "workspace_root_missing": "workspace_prepare",
    "analyst_workspace_not_found": "workspace_prepare",
    "codex_command_not_found": "runtime_prepare",
    "codex_exec_timeout": "codex_exec",
    "codex_stream_disconnected": "codex_exec",
    "codex_output_invalid_json": "result_parse",
    "codex_result_missing": "result_parse",
    "release_review_report_incomplete": "contract_validate",
    "release_review_metadata_conflict": "metadata_validate",
    "git_status_failed": "publish_prepare",
    "git_add_failed": "publish_prepare",
    "git_commit_failed": "publish_execute",
    "git_tag_failed": "publish_execute",
    "release_note_invalid": "publish_execute",
    "release_version_not_found_after_publish": "publish_verify",
    "publish_failed": "publish_execute",
    "role_creation_retry_running": "retry_dispatch",
    "role_creation_retry_no_pending_messages": "retry_dispatch",
    "role_creation_session_completed": "retry_dispatch",
}

_DEFAULT_STAGE_BY_FEATURE = {
    "policy_analysis": "codex_exec",
    "session_task_execution": "codex_exec",
    "role_creation_analysis": "codex_exec",
    "release_review": "codex_exec",
    "release_publish": "publish_execute",
    "assignment_node_execution": "codex_exec",
}

_MESSAGE_EXACT = {
    "codex_command_not_found": "当前环境未找到 codex 命令。",
    "workspace_missing": "目标工作区不存在或不可访问。",
    "workspace_root_missing": "目标工作区不存在或不可访问。",
    "analyst_workspace_not_found": "未找到角色分析师工作区。",
    "agents_md_not_found": "未找到 AGENTS.md。",
    "target_agents_path_out_of_scope": "目标 AGENTS.md 超出允许工作区范围。",
    "agent_policy_out_of_scope": "当前策略分析目标超出允许工作区范围。",
    "codex_exec_timeout": "Codex 执行超时。",
    "codex_stream_disconnected": "Codex 连接中断。",
    "codex_output_invalid_json": "已收到输出，但结构化结果无法解析。",
    "codex_result_missing": "执行完成，但没有返回可用结果。",
    "release_review_report_incomplete": "结构化发布报告缺少必填字段。",
    "release_review_metadata_conflict": "发布评审前置元数据冲突，暂不能继续。",
    "git_status_failed": "发布前 Git 状态检查失败。",
    "git_add_failed": "发布前 Git 暂存失败。",
    "git_commit_failed": "发布提交失败。",
    "git_tag_failed": "发布标签创建失败。",
    "release_note_invalid": "发布说明生成或校验失败。",
    "release_version_not_found_after_publish": "发布完成后未识别到目标版本。",
    "publish_failed": "发布执行失败。",
    "role_creation_retry_running": "当前对话仍在分析中，不能重复发起重试。",
    "role_creation_retry_no_pending_messages": "当前没有失败或待处理消息可重试。",
    "role_creation_session_completed": "当前角色创建已完成，不能再重试本轮分析。",
    "role_creation_session_not_found": "角色创建会话不存在。",
    "policy_contract_invalid": "结构化策略结果缺少必填字段。",
    "policy_extract_failed": "角色策略分析失败。",
    "release_review_report_failed": "发布评审报告生成失败。",
    "role_creation_analysis_failed": "角色创建分析失败。",
}

_MESSAGE_PREFIXES = (
    ("codex_exec_failed_exit_", "Codex 执行异常退出。"),
    ("codex_exec_exception", "执行过程出现异常。"),
    ("git_", "发布执行失败。"),
)

_RETRY_ACTION_LABELS = {
    "retry_policy_analysis": "重新分析角色策略",
    "retry_session_round": "重试上一轮",
    "retry_role_creation_analysis": "重试本轮分析",
    "retry_release_review": "重新进入发布评审",
    "retry_publish": "重试发布",
    "rerun_assignment_node": "重跑任务",
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_detail_code(detail_code: Any) -> str:
    return _clean_text(detail_code).lower()


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def derive_failure_code(detail_code: Any) -> str:
    detail = _normalized_detail_code(detail_code)
    if not detail:
        return "execution_failed"
    exact = _FAILURE_CODE_EXACT.get(detail)
    if exact:
        return exact
    for prefix, code in _FAILURE_CODE_PREFIXES:
        if detail.startswith(prefix):
            return code
    return "execution_failed"


def derive_failure_stage(
    feature_key: Any,
    detail_code: Any,
    *,
    stage_hint: Any = "",
) -> str:
    hint = _clean_text(stage_hint)
    if hint:
        return hint
    detail = _normalized_detail_code(detail_code)
    if detail in _FAILURE_STAGE_EXACT:
        return _FAILURE_STAGE_EXACT[detail]
    if detail.startswith("codex_exec_failed_exit_") or detail.startswith("codex_exec_exception"):
        return "codex_exec"
    return _DEFAULT_STAGE_BY_FEATURE.get(_clean_text(feature_key), "codex_exec")


def describe_failure_message(
    feature_key: Any,
    detail_code: Any,
    *,
    fallback_message: Any = "",
) -> str:
    fallback = _clean_text(fallback_message)
    detail = _normalized_detail_code(detail_code)
    if fallback and fallback.lower() not in {
        "publish_failed",
        "release review report failed",
        "assignment execution failed",
    }:
        return fallback
    exact = _MESSAGE_EXACT.get(detail)
    if exact:
        return exact
    for prefix, message in _MESSAGE_PREFIXES:
        if detail.startswith(prefix):
            return message
    feature = _clean_text(feature_key)
    if feature == "release_publish":
        return "发布执行失败。"
    if feature == "release_review":
        return "发布评审生成失败。"
    if feature == "role_creation_analysis":
        return "角色创建分析失败。"
    if feature == "policy_analysis":
        return "角色策略分析失败。"
    if feature == "assignment_node_execution":
        return "任务节点执行失败。"
    return fallback or "执行失败。"


def normalize_trace_refs(trace_refs: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []

    def push(label: Any, path: Any) -> None:
        path_text = _clean_text(path)
        if not path_text:
            return
        label_text = _clean_text(label) or "evidence"
        refs.append({"label": label_text, "path": path_text})

    def visit(value: Any, label_hint: str = "") -> None:
        if isinstance(value, dict):
            maybe_path = _clean_text(value.get("path"))
            if maybe_path:
                push(value.get("label") or label_hint or value.get("name"), maybe_path)
                return
            for key, item in value.items():
                visit(item, _clean_text(key))
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                visit(item, label_hint)
            return
        if isinstance(value, str):
            push(label_hint, value)

    visit(trace_refs)

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in refs:
        path_text = _clean_text(item.get("path"))
        label_text = _clean_text(item.get("label")) or "evidence"
        if not path_text:
            continue
        key = path_text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": label_text, "path": path_text})
    return out


def build_retry_action(
    kind: Any,
    *,
    retryable: bool = True,
    blocked_reason: Any = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_kind = _clean_text(kind)
    return {
        "kind": action_kind,
        "label": _RETRY_ACTION_LABELS.get(action_kind, action_kind or "重试"),
        "retryable": bool(retryable),
        "blocked_reason": _clean_text(blocked_reason),
        "payload": dict(payload or {}),
    }


def _normalize_retry_action(
    retry_action: Any,
    *,
    retryable: bool,
) -> dict[str, Any]:
    if isinstance(retry_action, dict):
        action = build_retry_action(
            retry_action.get("kind"),
            retryable=bool(retry_action.get("retryable", retryable)),
            blocked_reason=retry_action.get("blocked_reason"),
            payload=retry_action.get("payload") if isinstance(retry_action.get("payload"), dict) else {},
        )
        if _clean_text(retry_action.get("label")):
            action["label"] = _clean_text(retry_action.get("label"))
        return action
    return build_retry_action(retry_action, retryable=retryable)


def next_step_suggestion(
    retry_action: dict[str, Any] | None,
    *,
    has_trace_refs: bool,
) -> str:
    action = retry_action if isinstance(retry_action, dict) else {}
    label = _clean_text(action.get("label"))
    blocked_reason = _clean_text(action.get("blocked_reason"))
    if blocked_reason:
        return blocked_reason
    if label:
        if has_trace_refs:
            return f"建议先查看证据，再点击“{label}”。"
        return f"建议点击“{label}”重新触发。"
    if has_trace_refs:
        return "建议先查看证据定位原因。"
    return "建议先处理失败原因后再继续。"


def build_codex_failure(
    *,
    feature_key: Any,
    attempt_id: Any,
    attempt_count: Any,
    failure_detail_code: Any,
    failure_message: Any = "",
    failure_stage: Any = "",
    failure_code: Any = "",
    retry_action: Any = None,
    trace_refs: Any = None,
    failed_at: Any = "",
) -> dict[str, Any]:
    feature = _clean_text(feature_key)
    detail_code = _normalized_detail_code(failure_detail_code)
    if not feature or not detail_code:
        return {}
    attempt_text = _clean_text(attempt_id)
    try:
        attempt_value = max(1, int(attempt_count or 0))
    except Exception:
        attempt_value = 1
    code = _clean_text(failure_code) or derive_failure_code(detail_code)
    stage = derive_failure_stage(feature, detail_code, stage_hint=failure_stage)
    trace_ref_rows = normalize_trace_refs(trace_refs)
    action = _normalize_retry_action(retry_action, retryable=True)
    retryable = bool(action.get("retryable"))
    if not _clean_text(action.get("kind")):
        retryable = False
    action["retryable"] = retryable
    message = describe_failure_message(feature, detail_code, fallback_message=failure_message)
    failed_at_text = _clean_text(failed_at)
    return {
        "feature_key": feature,
        "attempt_id": attempt_text,
        "attempt_count": attempt_value,
        "failure_code": code,
        "failure_detail_code": detail_code,
        "failure_stage": stage,
        "failure_message": message,
        "retryable": retryable,
        "retry_action": action,
        "trace_refs": trace_ref_rows,
        "failed_at": failed_at_text,
        "next_step_suggestion": next_step_suggestion(action, has_trace_refs=bool(trace_ref_rows)),
    }


def infer_codex_failure_detail_code(
    raw_error: Any,
    *,
    fallback: str = "",
) -> str:
    text = _normalized_detail_code(raw_error)
    if not text:
        return _normalized_detail_code(fallback)
    if text in _FAILURE_CODE_EXACT:
        return text
    for prefix, _code in _FAILURE_CODE_PREFIXES:
        if text.startswith(prefix):
            return text
    if "codex command not found" in text:
        return "codex_command_not_found"
    if "codex returned no agent message" in text:
        return "codex_result_missing"
    match = re.search(r"command exit code=(\d+)", text)
    if match:
        return f"codex_exec_failed_exit_{match.group(1)}"
    if "timeout" in text:
        return "codex_exec_timeout"
    if "workspace missing" in text:
        return "workspace_missing"
    return _normalized_detail_code(fallback) or "execution_failed"
