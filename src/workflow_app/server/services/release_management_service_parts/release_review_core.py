from __future__ import annotations

import os
import time

def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    if not isinstance(symbols, dict):
        return
    target = globals()
    module_name = str(target.get('__name__') or '')
    for key, value in symbols.items():
        if str(key).startswith('__'):
            continue
        current = target.get(key)
        if callable(current) and getattr(current, '__module__', '') == module_name:
            continue
        target[key] = value

def training_release_evaluation_id() -> str:
    ts = now_local()
    return f"trev-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


RELEASE_REVIEW_STATES = (
    "idle",
    "report_generating",
    "report_ready",
    "review_approved",
    "review_rejected",
    "review_discarded",
    "publish_running",
    "publish_failed",
    "report_failed",
)
RELEASE_REVIEW_PROMPT_VERSION = "2026-03-10-release-review-v8"
RELEASE_REVIEW_FALLBACK_PROMPT_VERSION = "2026-03-10-release-review-fallback-v2"
RELEASE_REVIEW_CODEX_TIMEOUT_S = 900
RELEASE_REVIEW_ENTERABLE_STATES = ("idle", "review_rejected", "review_discarded", "publish_failed", "report_failed")
RELEASE_REVIEW_DISCARDABLE_STATES = ("report_generating", "report_ready", "review_approved")
RELEASE_REVIEW_CONFIRMABLE_STATES = ("review_approved", "publish_failed")
RELEASE_REVIEW_REPORT_FIELDS = (
    "target_version",
    "current_workspace_ref",
    "previous_release_version",
    "first_person_summary",
    "full_capability_inventory",
    "knowledge_scope",
    "agent_skills",
    "applicable_scenarios",
    "change_summary",
    "capability_delta",
    "risk_list",
    "validation_evidence",
    "release_recommendation",
    "next_action_suggestion",
    "warnings",
)
RELEASE_REVIEW_REQUIRED_FIELDS = (
    "target_version",
    "current_workspace_ref",
    "first_person_summary",
    "full_capability_inventory",
    "knowledge_scope",
    "agent_skills",
    "applicable_scenarios",
    "change_summary",
    "release_recommendation",
    "next_action_suggestion",
)
RELEASE_REVIEW_FAILURE_REPORT_FIELDS = (
    "target_version",
    "current_workspace_ref",
    "change_summary",
    "release_recommendation",
    "next_action_suggestion",
)


def _release_review_codex_timeout_s() -> int:
    raw = str(os.getenv("WORKFLOW_RELEASE_REVIEW_CODEX_TIMEOUT_S") or "").strip()
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return max(60, min(1200, value))
        except Exception:
            pass
    return max(60, int(RELEASE_REVIEW_CODEX_TIMEOUT_S))


def training_release_review_id() -> str:
    ts = now_local()
    return f"trrv-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _can_enter_release_review(lifecycle_state: str, current_state: str) -> bool:
    return normalize_lifecycle_state(lifecycle_state) == "pre_release" and str(current_state or "").strip() in RELEASE_REVIEW_ENTERABLE_STATES


def _can_confirm_release_review(lifecycle_state: str, current_state: str, review_decision: str) -> bool:
    return (
        normalize_lifecycle_state(lifecycle_state) == "pre_release"
        and str(current_state or "").strip() in RELEASE_REVIEW_CONFIRMABLE_STATES
        and str(review_decision or "").strip() == "approve_publish"
    )


def _can_discard_release_review(lifecycle_state: str, current_state: str, review_id: str) -> bool:
    return (
        normalize_lifecycle_state(lifecycle_state) == "pre_release"
        and bool(str(review_id or "").strip())
        and str(current_state or "").strip() in RELEASE_REVIEW_DISCARDABLE_STATES
    )


def _release_review_field_present(value: Any) -> bool:
    if isinstance(value, list):
        return bool([item for item in value if str(item or "").strip()])
    if isinstance(value, dict):
        return bool(value)
    return bool(str(value or "").strip())


def _release_review_missing_fields(report: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    node = report if isinstance(report, dict) else {}
    return [field for field in fields if not _release_review_field_present(node.get(field))]


def _json_dumps_text(payload: Any, fallback: str) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return str(fallback or "")


def _json_load_dict(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_load_list(raw: Any) -> list[Any]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def _release_review_trace_root(root: Path) -> Path:
    path = root / "logs" / "release-review"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _release_review_trace_dir(root: Path, agent_name: str, review_id: str) -> Path:
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    token = safe_token(agent_name, "agent", 40) or "agent"
    folder = _release_review_trace_root(root) / f"{stamp}-{token}-{safe_token(review_id, 'review', 80)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _release_review_attempt_dir(trace_dir: Path, prefix: str) -> Path:
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    token = safe_token(prefix, "attempt", 40) or "attempt"
    folder = trace_dir / f"{token}-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_release_review_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


def _write_release_review_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _path_for_ui(root: Path, path: Path | str) -> str:
    try:
        if isinstance(path, Path):
            target = path.resolve(strict=False)
        else:
            target = Path(str(path or "")).resolve(strict=False)
        return relative_to_root(root, target)
    except Exception:
        if isinstance(path, Path):
            return path.as_posix()
        return str(path or "")


def _release_review_extract_codex_event_text(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    if str(event.get("type") or "").strip() != "item.completed":
        return ""
    item = event.get("item")
    if not isinstance(item, dict):
        return ""
    if str(item.get("type") or "").strip() != "agent_message":
        return ""
    text = str(item.get("text") or "").strip()
    if text:
        return text
    content = item.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for node in content:
        if not isinstance(node, dict):
            continue
        part = str(node.get("text") or node.get("output_text") or "").strip()
        if part:
            parts.append(part)
    return "\n".join(parts).strip()


def _release_review_extract_json_objects(text: str) -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    idx = 0
    total = len(raw)
    while idx < total:
        start = raw.find("{", idx)
        if start < 0:
            break
        try:
            value, consumed = decoder.raw_decode(raw[start:])
        except Exception:
            idx = start + 1
            continue
        idx = start + max(1, consumed)
        if isinstance(value, dict):
            out.append(value)
    return out


def _release_review_structured_result_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    expected_keys = {
        "target_version",
        "current_workspace_ref",
        "previous_release_version",
        "first_person_summary",
        "full_capability_inventory",
        "knowledge_scope",
        "agent_skills",
        "applicable_scenarios",
        "change_summary",
        "capability_delta",
        "risk_list",
        "validation_evidence",
        "release_recommendation",
        "next_action_suggestion",
        "failure_reason",
        "retry_target_version",
        "retry_release_notes",
    }
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        keys = {str(key or "").strip() for key in candidate.keys()}
        if keys & expected_keys:
            out.append(candidate)
    return out


def _release_review_collect_payload_candidates(raw: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 4 or raw is None:
        return []
    out: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        out.append(raw)
        for key, value in raw.items():
            key_text = str(key or "").strip().lower()
            if key_text in {
                "item",
                "report",
                "result",
                "data",
                "output",
                "final",
                "response",
                "message",
                "text",
                "content",
                "payload",
                "output_text",
            }:
                out.extend(_release_review_collect_payload_candidates(value, depth=depth + 1))
    elif isinstance(raw, list):
        for item in raw[:10]:
            out.extend(_release_review_collect_payload_candidates(item, depth=depth + 1))
    elif isinstance(raw, str) and "{" in raw:
        for item in _release_review_extract_json_objects(raw):
            out.extend(_release_review_collect_payload_candidates(item, depth=depth + 1))
    return out


def _release_review_payload_score(candidate: dict[str, Any]) -> int:
    if not isinstance(candidate, dict):
        return -1
    score = 0
    for key in (
        "target_version",
        "current_workspace_ref",
        "previous_release_version",
        "first_person_summary",
        "full_capability_inventory",
        "knowledge_scope",
        "agent_skills",
        "applicable_scenarios",
        "change_summary",
        "capability_delta",
        "risk_list",
        "validation_evidence",
        "release_recommendation",
        "next_action_suggestion",
        "warnings",
        "failure_reason",
        "retry_target_version",
        "retry_release_notes",
    ):
        if key not in candidate:
            continue
        value = candidate.get(key)
        if isinstance(value, list):
            score += 3 if value else 1
        elif isinstance(value, dict):
            score += 1 if value else 0
        else:
            score += 3 if str(value or "").strip() else 1
    for alias_key in ("summary", "recommendation", "next_action", "workspace_ref", "version"):
        if alias_key in candidate and str(candidate.get(alias_key) or "").strip():
            score += 1
    return score


def _release_review_best_payload(raw: Any) -> dict[str, Any]:
    candidates = _release_review_collect_payload_candidates(raw)
    if not candidates:
        return {}
    ranked = sorted(candidates, key=_release_review_payload_score, reverse=True)
    best = ranked[0] if ranked else {}
    return best if isinstance(best, dict) else {}


def _release_review_pick_text(source: dict[str, Any], *keys: str) -> str:
    if not isinstance(source, dict):
        return ""
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if isinstance(value, list):
            text = "\n".join([str(item or "").strip() for item in value if str(item or "").strip()]).strip()
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _release_review_normalize_recommendation(value: Any) -> str:
    key = str(value or "").strip().lower()
    if not key:
        return ""
    mapping = {
        "approve_publish": "approve",
        "approve": "approve",
        "approve_release": "approve",
        "publish": "approve",
        "go": "approve",
        "通过": "approve",
        "review_approved": "approve",
        "reject_continue_training": "needs_more_validation",
        "continue_training": "needs_more_validation",
        "continue_train": "needs_more_validation",
        "needs_more_validation": "needs_more_validation",
        "hold": "needs_more_validation",
        "retry": "needs_more_validation",
        "继续训练": "needs_more_validation",
        "reject_discard_pre_release": "reject",
        "discard_pre_release": "reject",
        "discard": "reject",
        "abandon": "reject",
        "舍弃预发布": "reject",
        "reject": "reject",
    }
    return mapping.get(key, "")


def _release_review_default_next_action(recommendation: str, *, has_structured_content: bool) -> str:
    key = str(recommendation or "").strip().lower()
    if key == "approve":
        return "我建议人工复核风险与验证证据，无误后提交审核结论并进入确认发布。"
    if key == "reject":
        return "我建议人工确认本次预发布是否应直接舍弃；若确认无保留价值，可提交“不通过：舍弃预发布”。"
    if has_structured_content:
        return "我建议先根据本次报告补齐风险说明或验证证据，再重新进入发布评审。"
    return "我建议先查看分析链路中的 stdout / stderr / 报告文件，修正结构化输出后重新进入发布评审。"


def _normalize_text_list(raw: Any, *, limit: int = 280) -> list[str]:
    if isinstance(raw, list):
        out = []
        for item in raw:
            text = _short_text(str(item or "").strip(), limit)
            if text:
                out.append(text)
        return out
    text = str(raw or "").strip()
    if not text:
        return []
    return [_short_text(line.strip("- •\t "), limit) for line in text.splitlines() if line.strip()]


def _text_items(raw: Any, *, limit: int = 8, item_limit: int = 220) -> list[str]:
    values = raw if isinstance(raw, list) else re.split(r"[\r\n]+|(?<=[。；;!?！？])", str(raw or "").strip())
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _short_text(str(item or "").strip().strip("-•* \t"), item_limit)
        if not text:
            continue
        key = re.sub(r"\s+", "", text).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max(1, int(limit or 1)):
            break
    return out


def _ensure_first_person_text(value: Any, prefix: str, *, limit: int = 320) -> str:
    text = _short_text(str(value or "").strip(), limit)
    if not text:
        return ""
    if text.startswith(("我是", "我当前", "我能", "我已", "我会", "我建议", "本次发布", "当前工作区")):
        return text
    if text.startswith("你是"):
        return "我" + text[1:]
    if text.startswith("作为"):
        return "我" + text
    return prefix + text


def _ensure_first_person_list(raw: Any, prefix: str, *, limit: int = 8, item_limit: int = 220) -> list[str]:
    out: list[str] = []
    for item in _text_items(raw, limit=limit, item_limit=item_limit):
        out.append(_ensure_first_person_text(item, prefix, limit=item_limit))
    return out


def _release_review_agent_context(agent: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(str(agent.get("workspace_path") or "")).resolve(strict=False)
    agents_md_path = workspace / "AGENTS.md"
    portrait_parser = globals().get("extract_agent_role_portrait")
    policy_parser = globals().get("extract_agent_policy_fields")
    list_workspace_local_skills = globals().get("_list_workspace_local_skills")

    portrait: dict[str, Any] = {}
    if callable(portrait_parser):
        try:
            portrait = portrait_parser(agents_md_path)
        except Exception:
            portrait = {}

    agents_text = ""
    try:
        if agents_md_path.exists():
            agents_text = agents_md_path.read_text(encoding="utf-8")
    except Exception:
        agents_text = ""

    policy_payload: dict[str, Any] = {}
    if agents_text and callable(policy_parser):
        try:
            policy_payload = policy_parser(agents_text)
        except Exception:
            policy_payload = {}

    duty_constraints = [
        _short_text(str(item or "").strip(), 220)
        for item in (policy_payload.get("duty_constraints") or [])
        if str(item or "").strip()
    ]
    capability_inventory: list[str] = []
    for item in _text_items(policy_payload.get("session_goal"), limit=3, item_limit=220):
        if item not in capability_inventory:
            capability_inventory.append(item)
    for item in duty_constraints:
        if item not in capability_inventory:
            capability_inventory.append(item)
        if len(capability_inventory) >= 12:
            break
    if not capability_inventory:
        for item in _text_items(
            str(portrait.get("capability_summary") or agent.get("core_capabilities") or policy_payload.get("role_profile") or ""),
            limit=8,
            item_limit=220,
        ):
            if item not in capability_inventory:
                capability_inventory.append(item)
    if not capability_inventory:
        fallback_item = _short_text(str(agent.get("capability_summary") or portrait.get("capability_summary") or "").strip(), 220)
        if fallback_item:
            capability_inventory.append(fallback_item)

    knowledge_scope = str(
        portrait.get("knowledge_scope")
        or agent.get("knowledge_scope")
        or policy_payload.get("session_goal")
        or policy_payload.get("role_profile")
        or ""
    ).strip()
    applicable_scenarios = _text_items(
        portrait.get("applicable_scenarios") or agent.get("applicable_scenarios") or policy_payload.get("session_goal") or "",
        limit=6,
        item_limit=140,
    )
    local_skills: list[str] = []
    if callable(list_workspace_local_skills):
        try:
            local_skills = _skills_list(list_workspace_local_skills(workspace))
        except Exception:
            local_skills = []
    if not local_skills:
        local_skills = _skills_list(portrait.get("skills") or agent.get("skills") or agent.get("skills_json"))

    first_person_seed = str(
        portrait.get("capability_summary")
        or agent.get("capability_summary")
        or policy_payload.get("role_profile")
        or policy_payload.get("session_goal")
        or ""
    ).strip()
    return {
        "first_person_summary": _ensure_first_person_text(first_person_seed, "我当前的核心能力是：", limit=320),
        "full_capability_inventory": capability_inventory,
        "knowledge_scope": knowledge_scope,
        "agent_skills": local_skills,
        "applicable_scenarios": applicable_scenarios,
        "previous_release_version": str(agent.get("latest_release_version") or "").strip(),
    }


def _derive_what_i_can_do(summary: str, inventory: list[str]) -> list[str]:
    items = _ensure_first_person_list(inventory, "我当前可以：", limit=5, item_limit=180)
    if items:
        return items[:5]
    return _ensure_first_person_list(summary, "我当前可以：", limit=5, item_limit=180)


def _release_review_warning_text(value: Any, *, limit: int = 220) -> str:
    return _ensure_first_person_text(value, "我当前补充说明：", limit=limit)


def _release_review_is_traceability_warning(text: str) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return False
    return any(
        token in value
        for token in (
            "readme",
            "changelog",
            "release note",
            "release-note",
            "release notes",
            "release_note",
            "发布说明",
            "发布 note",
        )
    )


def _release_review_is_workspace_external_warning(text: str) -> bool:
    value = str(text or "").strip()
    lowered = value.lower()
    if not value:
        return False
    if "../" in value or "..\\" in value:
        return True
    return any(
        token in lowered
        for token in (
            "工作区外",
            "兄弟目录",
            "sibling",
            "outside workspace",
            "external workspace",
            "other workspace",
        )
    )


def _release_review_is_metadata_conflict_text(text: str) -> bool:
    value = str(text or "").strip()
    lowered = value.lower()
    if not value:
        return False
    if "metadata_conflict" in lowered:
        return True
    keys = (
        "target_version",
        "current_registry_version",
        "latest_release_version",
        "bound_release_version",
        "released_versions",
    )
    conflict_markers = ("冲突", "矛盾", "不一致", "conflict", "mismatch", "inconsistent")
    return any(key in lowered for key in keys) and any(marker in lowered for marker in conflict_markers)


def _release_review_filter_risks(raw_items: Any) -> dict[str, Any]:
    filtered: list[str] = []
    warnings: list[str] = []
    metadata_conflicts: list[str] = []
    demoted_count = 0
    for item in _normalize_text_list(raw_items, limit=220):
        if _release_review_is_traceability_warning(item):
            warnings.append(_release_review_warning_text(item))
            demoted_count += 1
            continue
        if _release_review_is_workspace_external_warning(item):
            warnings.append(_release_review_warning_text(item))
            demoted_count += 1
            continue
        if _release_review_is_metadata_conflict_text(item):
            metadata_conflicts.append(_short_text(item, 220))
            warnings.append(_release_review_warning_text("我识别到版本元数据存在冲突，本次需要先修复元数据再重新进入发布评审。"))
            continue
        filtered.append(_ensure_first_person_text(item, "我当前识别到的风险是：", limit=220))
    return {
        "risk_list": filtered,
        "warnings": warnings,
        "metadata_conflicts": metadata_conflicts,
        "demoted_count": demoted_count,
    }


def _release_review_metadata_conflicts(
    *,
    agent: dict[str, Any],
    target_version: str,
    released_versions: list[str],
) -> list[str]:
    labels = [str(item or "").strip() for item in released_versions if str(item or "").strip()]
    label_set = set(labels)
    conflicts: list[str] = []
    latest_release_version = str(agent.get("latest_release_version") or "").strip()
    bound_release_version = str(agent.get("bound_release_version") or "").strip()
    if target_version and target_version in label_set:
        conflicts.append(f"target_version={target_version} 已存在于 released_versions 中，无法作为新的正式发布目标版本。")
    if latest_release_version and label_set and latest_release_version not in label_set:
        conflicts.append(
            f"latest_release_version={latest_release_version} 未出现在 released_versions 中，请先修复版本元数据。"
        )
    if bound_release_version and label_set and bound_release_version not in label_set:
        conflicts.append(
            f"bound_release_version={bound_release_version} 未出现在 released_versions 中，请先修复版本元数据。"
        )
    return conflicts


def _build_release_public_profile_snapshot(
    *,
    agent: dict[str, Any],
    report: dict[str, Any],
    analysis_chain: dict[str, Any],
    review_id: str,
) -> dict[str, Any]:
    summary = _ensure_first_person_text(report.get("first_person_summary"), "我当前的核心能力是：", limit=320)
    inventory = _ensure_first_person_list(report.get("full_capability_inventory"), "我当前可以：", limit=12, item_limit=220)
    knowledge_scope = _ensure_first_person_text(report.get("knowledge_scope"), "我当前覆盖的知识范围是：", limit=320)
    scenarios = _text_items(report.get("applicable_scenarios"), limit=6, item_limit=140)
    return {
        "profile_source": "latest_release_report",
        "review_id": review_id,
        "agent_id": str(agent.get("agent_id") or "").strip(),
        "agent_name": str(agent.get("agent_name") or "").strip(),
        "source_release_version": str(report.get("target_version") or "").strip(),
        "first_person_summary": summary,
        "what_i_can_do": _derive_what_i_can_do(summary, inventory),
        "full_capability_inventory": inventory,
        "knowledge_scope": knowledge_scope,
        "agent_skills": _skills_list(report.get("agent_skills")),
        "applicable_scenarios": scenarios,
        "version_notes": _short_text(str(report.get("change_summary") or "").strip(), 320),
        "change_summary": _short_text(str(report.get("change_summary") or "").strip(), 1000),
        "capability_delta": _ensure_first_person_list(report.get("capability_delta"), "我本次主要补充了：", limit=8, item_limit=220),
        "risk_list": _ensure_first_person_list(report.get("risk_list"), "我当前识别到的风险是：", limit=8, item_limit=220),
        "validation_evidence": _ensure_first_person_list(report.get("validation_evidence"), "我当前已确认的证据是：", limit=8, item_limit=240),
        "release_recommendation": str(report.get("release_recommendation") or "").strip(),
        "next_action_suggestion": _ensure_first_person_text(report.get("next_action_suggestion"), "我建议下一步：", limit=320),
        "analysis_chain_ref": str(analysis_chain.get("report_path") or analysis_chain.get("trace_dir") or "").strip(),
        "public_profile_ref": "",
        "capability_snapshot_ref": "",
    }


def _build_release_public_profile_markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        "# 最新正式发布角色述职报告",
        "",
        f"- 角色：{str(snapshot.get('agent_name') or snapshot.get('agent_id') or '').strip() or '-'}",
        f"- 目标版本：{str(snapshot.get('source_release_version') or '').strip() or '-'}",
        "",
        "## 我是 / 我当前能做什么",
        str(snapshot.get("first_person_summary") or "").strip() or "我当前暂无可展示的正式发布摘要。",
        "",
    ]
    what_i_can_do = snapshot.get("what_i_can_do") if isinstance(snapshot.get("what_i_can_do"), list) else []
    if what_i_can_do:
        lines.append("## 我当前能做什么")
        lines.extend([f"- {str(item or '').strip()}" for item in what_i_can_do if str(item or "").strip()])
        lines.append("")
    inventory = snapshot.get("full_capability_inventory") if isinstance(snapshot.get("full_capability_inventory"), list) else []
    if inventory:
        lines.append("## 全量能力清单")
        lines.extend([f"- {str(item or '').strip()}" for item in inventory if str(item or "").strip()])
        lines.append("")
    if str(snapshot.get("knowledge_scope") or "").strip():
        lines.extend(["## 角色知识范围", str(snapshot.get("knowledge_scope") or "").strip(), ""])
    skills = snapshot.get("agent_skills") if isinstance(snapshot.get("agent_skills"), list) else []
    if skills:
        lines.append("## Agent Skills")
        lines.extend([f"- {str(item or '').strip()}" for item in skills if str(item or "").strip()])
        lines.append("")
    scenarios = snapshot.get("applicable_scenarios") if isinstance(snapshot.get("applicable_scenarios"), list) else []
    if scenarios:
        lines.append("## 适用场景")
        lines.extend([f"- {str(item or '').strip()}" for item in scenarios if str(item or "").strip()])
        lines.append("")
    if str(snapshot.get("version_notes") or "").strip():
        lines.extend(["## 版本说明", str(snapshot.get("version_notes") or "").strip(), ""])
    delta = snapshot.get("capability_delta") if isinstance(snapshot.get("capability_delta"), list) else []
    if delta:
        lines.append("## 相对上一正式发布版本的能力增量")
        lines.extend([f"- {str(item or '').strip()}" for item in delta if str(item or "").strip()])
        lines.append("")
    risks = snapshot.get("risk_list") if isinstance(snapshot.get("risk_list"), list) else []
    if risks:
        lines.append("## 风险清单")
        lines.extend([f"- {str(item or '').strip()}" for item in risks if str(item or "").strip()])
        lines.append("")
    evidence = snapshot.get("validation_evidence") if isinstance(snapshot.get("validation_evidence"), list) else []
    if evidence:
        lines.append("## 验证证据")
        lines.extend([f"- {str(item or '').strip()}" for item in evidence if str(item or "").strip()])
        lines.append("")
    if str(snapshot.get("next_action_suggestion") or "").strip():
        lines.extend(["## 下一步建议", str(snapshot.get("next_action_suggestion") or "").strip(), ""])
    return "\n".join(lines).strip() + "\n"
