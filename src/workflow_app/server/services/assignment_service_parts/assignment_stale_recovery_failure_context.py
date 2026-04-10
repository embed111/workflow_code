from __future__ import annotations


_ASSIGNMENT_STALE_RECOVERY_GENERIC_FAILURE_MARKERS = (
    "运行句柄缺失",
    "workflow 已重启",
    "已自动结束当前批次",
    "后台结果不再回写节点状态",
)
_ASSIGNMENT_STALE_RECOVERY_GENERIC_STATUS_MARKERS = (
    "已创建运行批次",
    "等待 provider 启动",
    "provider 已启动",
    "执行中",
)
_ASSIGNMENT_STALE_RECOVERY_NOISE_PREFIXES = (
    "at line:",
    "line |",
    "+ ",
    "~",
    "categoryinfo",
    "fullyqualifiederrorid",
    "wall time:",
    "output:",
    "stderr 输出",
    "stdout 输出",
)
_ASSIGNMENT_STALE_RECOVERY_ERROR_MARKERS = (
    "无法",
    "失败",
    "错误",
    "异常",
    "请先",
    "error",
    "failed",
    "failure",
    "missing",
    "cannot",
    "could not",
    "not found",
    "not exist",
    "not a valid",
    "invalid",
    "denied",
    "timeout",
    "timed out",
    "disconnect",
    "parsererror",
    "exception",
)


def _assignment_stale_recovery_strip_trace_prefix(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return re.sub(r"^\[[^\]]+\]\s*", "", value).strip()


def _assignment_stale_recovery_failure_text_is_generic(text: str) -> bool:
    value = _assignment_stale_recovery_strip_trace_prefix(text)
    if not value:
        return True
    lowered = value.lower()
    if value in {"thread.started", "turn.started"}:
        return True
    if _assignment_result_summary_is_startup_only(value):
        return True
    if any(marker.lower() in lowered for marker in _ASSIGNMENT_STALE_RECOVERY_GENERIC_FAILURE_MARKERS):
        return True
    has_error_marker = any(marker in lowered for marker in _ASSIGNMENT_STALE_RECOVERY_ERROR_MARKERS)
    if any(marker.lower() in lowered for marker in _ASSIGNMENT_STALE_RECOVERY_GENERIC_STATUS_MARKERS) and not has_error_marker:
        return True
    return False


def _assignment_stale_recovery_candidate_score(text: str) -> int:
    value = _assignment_stale_recovery_strip_trace_prefix(text)
    if not value or _assignment_stale_recovery_failure_text_is_generic(value):
        return -100
    lowered = value.lower()
    score = 0
    if len(value) >= 12:
        score += 1
    if ":" in value:
        score += 1
    score += sum(4 for marker in _ASSIGNMENT_STALE_RECOVERY_ERROR_MARKERS if marker in lowered)
    if any(lowered.startswith(prefix) for prefix in _ASSIGNMENT_STALE_RECOVERY_NOISE_PREFIXES):
        score -= 8
    if "codex_core::tools::router" in lowered:
        score -= 4
    if value.startswith("{") and value.endswith("}"):
        score -= 6
    if re.fullmatch(r"[-=~+^| ]+", value):
        score -= 12
    return score


def _assignment_stale_recovery_trace_candidates(raw_text: str, *, source: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, raw_line in enumerate(str(raw_text or "").splitlines()):
        text = _assignment_stale_recovery_strip_trace_prefix(raw_line)
        score = _assignment_stale_recovery_candidate_score(text)
        if score <= 0:
            continue
        candidates.append(
            {
                "text": text,
                "source": source,
                "score": score,
                "sequence": index,
            }
        )
    return candidates


def _assignment_stale_recovery_stdout_error_candidates(stdout_text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, raw_line in enumerate(str(stdout_text or "").splitlines()):
        payload_text = _assignment_stale_recovery_strip_trace_prefix(raw_line)
        if not payload_text.startswith("{"):
            continue
        try:
            payload = json.loads(payload_text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type") or "").strip().lower()
        if event_type == "error":
            message_text = str(payload.get("message") or "").strip()
            score = _assignment_stale_recovery_candidate_score(message_text)
            if score > 0:
                candidates.append(
                    {
                        "text": message_text,
                        "source": "stdout.error",
                        "score": score,
                        "sequence": index,
                    }
                )
        error_payload = payload.get("error")
        if isinstance(error_payload, dict):
            message_text = str(error_payload.get("message") or "").strip()
            score = _assignment_stale_recovery_candidate_score(message_text)
            if score > 0:
                candidates.append(
                    {
                        "text": message_text,
                        "source": "stdout.error_payload",
                        "score": score,
                        "sequence": index,
                    }
                )
    return candidates


def _assignment_stale_recovery_cancelled_run_message(failure_reason: str) -> str:
    clue = _short_assignment_text(str(failure_reason or "").strip(), 360)
    if not clue:
        return "检测到运行句柄缺失，已自动结束当前批次。"
    return _short_assignment_text(f"检测到运行句柄缺失，已自动结束当前批次；最近失败线索：{clue}", 1000)


def _assignment_stale_recovery_failure_context(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    node_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    current_failure_reason = str((node_record or {}).get("failure_reason") or "").strip()
    current_failure_score = _assignment_stale_recovery_candidate_score(current_failure_reason)
    if current_failure_score > 0:
        candidates.append(
            {
                "text": current_failure_reason,
                "source": "node.failure_reason",
                "score": current_failure_score,
                "sequence": 0,
            }
        )
    for run_offset, run in enumerate(_assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id)):
        status = str(run.get("status") or "").strip().lower()
        if status not in {"starting", "running"}:
            continue
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            continue
        latest_event = str(run.get("latest_event") or "").strip()
        latest_event_score = _assignment_stale_recovery_candidate_score(latest_event)
        if latest_event_score > 0:
            candidates.append(
                {
                    "text": latest_event,
                    "source": "run.latest_event",
                    "score": latest_event_score,
                    "sequence": (run_offset + 1) * 1000,
                    "run_id": run_id,
                    "evidence_ref": str(run.get("stderr_ref") or "").strip(),
                }
            )
        refs = _assignment_run_file_paths(root, ticket_id, run_id)
        stderr_ref = str(run.get("stderr_ref") or refs["stderr"].as_posix()).strip()
        stdout_ref = str(run.get("stdout_ref") or refs["stdout"].as_posix()).strip()
        stderr_text = _read_assignment_run_text(stderr_ref)
        stdout_text = _read_assignment_run_text(stdout_ref)
        for candidate in _assignment_stale_recovery_trace_candidates(stderr_text, source="stderr"):
            item = dict(candidate)
            item["run_id"] = run_id
            item["sequence"] = (run_offset + 1) * 1000 + int(candidate.get("sequence") or 0)
            item["evidence_ref"] = stderr_ref
            candidates.append(item)
        for candidate in _assignment_stale_recovery_stdout_error_candidates(stdout_text):
            item = dict(candidate)
            item["run_id"] = run_id
            item["sequence"] = (run_offset + 1) * 1000 + int(candidate.get("sequence") or 0)
            item["evidence_ref"] = stdout_ref
            candidates.append(item)
    if not candidates:
        return {}
    best = max(
        candidates,
        key=lambda item: (
            int(item.get("score") or 0),
            int(item.get("sequence") or 0),
        ),
    )
    failure_reason = _short_assignment_text(str(best.get("text") or "").strip(), 500)
    if not failure_reason:
        return {}
    return {
        "failure_reason": failure_reason,
        "run_latest_event": _assignment_stale_recovery_cancelled_run_message(failure_reason),
        "audit_detail": {
            "run_id": str(best.get("run_id") or "").strip(),
            "source": str(best.get("source") or "").strip(),
            "evidence_ref": str(best.get("evidence_ref") or "").strip(),
            "failure_reason": failure_reason,
        },
    }
