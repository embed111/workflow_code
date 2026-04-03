from __future__ import annotations

from workflow_app.server.services.codex_failure_contract import build_codex_failure, build_retry_action
from workflow_app.server.services.codex_exec_monitor import resolve_codex_command, run_monitored_subprocess

def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    globals().update(symbols)

def _split_policy_cache_reason_codes(raw: str) -> list[str]:
    text = str(raw or "").strip().lower()
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;\s]+", text):
        code = str(part or "").strip().lower()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _agent_policy_reanalyze_required_from_item(item: dict[str, Any]) -> tuple[bool, str, list[str]]:
    node = item if isinstance(item, dict) else {}
    cache_status = str(node.get("policy_cache_status") or "").strip().lower()
    reason_codes = _split_policy_cache_reason_codes(str(node.get("policy_cache_reason") or ""))
    reason_code_set = set(reason_codes)
    if cache_status == "cleared" or "manual_clear" in reason_code_set:
        return (
            True,
            "当前角色缓存已清理，请先重新生成并完成角色分析。",
            reason_codes,
        )
    if cache_status == "stale" or bool(reason_code_set.intersection(_POLICY_REANALYZE_REASON_CODES)):
        if bool(reason_code_set.intersection(_POLICY_REANALYZE_AGENTS_UPDATED_CODES)):
            return (
                True,
                "检测到 AGENTS.md 已更新且缓存已过期，请先重新进行角色分析。",
                reason_codes,
            )
        return (
            True,
            "角色缓存已过期或无效，请先重新进行角色分析。",
            reason_codes,
        )
    return False, "", reason_codes


def session_policy_reanalyze_guard(cfg: AppConfig, session: dict[str, Any]) -> dict[str, Any]:
    session_obj = session if isinstance(session, dict) else {}
    agent_name = safe_token(str(session_obj.get("agent_name") or ""), "", 80)
    session_id = safe_token(str(session_obj.get("session_id") or ""), "", 140)
    session_hash = str(session_obj.get("agents_hash") or "").strip()
    out = {
        "required": False,
        "message": "",
        "session_id": session_id,
        "agent_name": agent_name,
        "session_agents_hash": session_hash,
        "latest_agents_hash": "",
        "agents_path": "",
        "policy_cache_status": "",
        "policy_cache_reason": "",
        "reason_codes": [],
    }
    if not agent_name:
        out["required"] = True
        out["message"] = "当前会话未绑定有效 agent，请先重新选择并完成角色分析。"
        return out
    items = list_available_agents(
        cfg,
        analyze_policy=False,
        target_agent_name=agent_name,
    )
    if not items:
        out["required"] = True
        out["message"] = "当前会话对应的 agent 不可用，请重新选择 agent 并完成角色分析。"
        return out
    item = items[0] if isinstance(items[0], dict) else {}
    required, message, reason_codes = _agent_policy_reanalyze_required_from_item(item)
    out["required"] = bool(required)
    out["message"] = str(message or "")
    out["latest_agents_hash"] = str(item.get("agents_hash") or "").strip()
    out["agents_path"] = str(item.get("agents_md_path") or "").strip()
    out["policy_cache_status"] = str(item.get("policy_cache_status") or "").strip().lower()
    out["policy_cache_reason"] = str(item.get("policy_cache_reason") or "").strip().lower()
    out["reason_codes"] = reason_codes
    return out


def clear_agent_policy_cache(
    root: Path,
    *,
    clear_all: bool,
    agent_path: str = "",
) -> dict[str, Any]:
    conn = connect_db(root)
    scope = "all" if clear_all else "selected"
    path_text = str(agent_path or "").strip()
    try:
        before = int(
            conn.execute("SELECT COUNT(1) AS cnt FROM agent_policy_cache").fetchone()["cnt"]
        )
        if clear_all:
            ret = conn.execute("DELETE FROM agent_policy_cache")
        elif path_text:
            ret = conn.execute("DELETE FROM agent_policy_cache WHERE agent_path=?", (path_text,))
        else:
            ret = conn.execute("DELETE FROM agent_policy_cache WHERE 1=0")
        deleted_count = int(ret.rowcount if ret.rowcount is not None else 0)
        after = int(
            conn.execute("SELECT COUNT(1) AS cnt FROM agent_policy_cache").fetchone()["cnt"]
        )
        conn.commit()
        return {
            "scope": scope,
            "agent_path": path_text,
            "deleted_count": max(0, deleted_count),
            "before_count": max(0, before),
            "remaining_count": max(0, after),
        }
    finally:
        conn.close()


def _extract_first_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(raw[start : end + 1])
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _normalize_policy_recommendation_payload(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    role_profile = str(payload.get("role_profile") or "").strip()
    session_goal = str(payload.get("session_goal") or "").strip()
    duty_items = normalize_duty_constraints_input(
        payload.get("duty_constraints")
        if isinstance(payload.get("duty_constraints"), list)
        else payload.get("duty_constraints_text")
    )
    duty_text = "\n".join(duty_items).strip()
    valid, _reason = validate_policy_fields(role_profile, session_goal, duty_text)
    if not valid:
        return {}
    return {
        "role_profile": role_profile,
        "session_goal": session_goal,
        "duty_constraints": duty_items,
        "duty_constraints_text": duty_text,
    }


def _fallback_policy_recommendation(
    *,
    agent_name: str,
    instruction: str,
    role_profile: str,
    session_goal: str,
    duty_constraints: list[str],
) -> dict[str, Any]:
    topic = re.sub(r"\s+", " ", str(instruction or "").strip())
    if len(topic) > 80:
        topic = topic[:80].rstrip() + "..."
    base_role = str(role_profile or "").strip()
    if not base_role:
        base_role = f"我是 {agent_name}，负责在明确职责边界内提供分析与执行建议。"
    if topic and topic not in base_role:
        base_role = f"{base_role} 当前重点：{topic}"

    base_goal = str(session_goal or "").strip()
    if not base_goal:
        base_goal = "结合用户上下文给出可执行、可验证的下一步方案。"
    if topic and topic not in base_goal:
        base_goal = f"{base_goal} 围绕“{topic}”优先给出结果。"

    duty_items = [str(item).strip() for item in (duty_constraints or []) if str(item or "").strip()]
    if not duty_items:
        duty_items = [
            "先澄清目标与约束，再输出分步骤方案。",
            "涉及高风险或破坏性操作前必须给出风险提示并请求确认。",
            "结论需可追溯到会话上下文与可观察证据。",
        ]
    if topic:
        priority = f"优先围绕“{topic}”输出可执行建议。"
        if all(priority not in item for item in duty_items):
            duty_items.insert(0, priority)
    duty_items = duty_items[:8]
    duty_text = "\n".join(duty_items).strip()
    return {
        "role_profile": base_role,
        "session_goal": base_goal,
        "duty_constraints": duty_items,
        "duty_constraints_text": duty_text,
    }


def _build_policy_recommend_prompt(
    *,
    agent_name: str,
    instruction: str,
    role_profile: str,
    session_goal: str,
    duty_constraints: list[str],
) -> str:
    payload = {
        "agent_name": str(agent_name or "").strip(),
        "instruction": str(instruction or "").strip(),
        "current_policy": {
            "role_profile": str(role_profile or "").strip(),
            "session_goal": str(session_goal or "").strip(),
            "duty_constraints": [str(item).strip() for item in (duty_constraints or []) if str(item or "").strip()],
        },
    }
    return "\n".join(
        [
            "你是角色策略生成器。请仅输出 JSON 对象，不要输出 Markdown。",
            "必须包含字段：role_profile(string), session_goal(string), duty_constraints(array[string])。",
            "要求：边界清晰、可执行、可验证，禁止空字段。",
            "输入：",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def _recommend_agent_policy_via_codex(
    *,
    workspace_root: Path,
    agent_name: str,
    instruction: str,
    role_profile: str,
    session_goal: str,
    duty_constraints: list[str],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    root = workspace_root.resolve(strict=False)
    workspace_ok, workspace_error = validate_workspace_root_semantics(root)
    if not workspace_ok:
        warnings.append(f"codex_workspace_invalid:{workspace_error}")
        return {}, warnings
    codex_bin = resolve_codex_command()
    if not codex_bin:
        warnings.append("codex_command_not_found")
        return {}, warnings
    prompt_text = _build_policy_recommend_prompt(
        agent_name=agent_name,
        instruction=instruction,
        role_profile=role_profile,
        session_goal=session_goal,
        duty_constraints=duty_constraints,
    )
    command = [
        codex_bin,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "--add-dir",
        root.as_posix(),
        "-C",
        root.as_posix(),
        "-",
    ]
    stdout_text = ""
    stderr_text = ""
    try:
        completion_state = {"ready": False}

        def _observe_stdout(line: str) -> None:
            cleaned = str(line or "").strip()
            if not cleaned:
                return
            try:
                event = json.loads(cleaned)
            except Exception:
                return
            if not isinstance(event, dict):
                return
            if str(event.get("type") or "").strip() == "turn.completed":
                completion_state["ready"] = True
                return
            msg_text = _extract_codex_event_text(event)
            if msg_text and _extract_json_objects(msg_text):
                completion_state["ready"] = True

        result = run_monitored_subprocess(
            command=command,
            cwd=root,
            stdin_text=prompt_text,
            on_stdout_line=_observe_stdout,
            completion_checker=lambda: bool(completion_state["ready"]),
        )
        stdout_text = result.stdout_text
        stderr_text = result.stderr_text
        exit_code = int(result.exit_code or 0)
        if result.forced_exit_after_result:
            warnings.append("codex_recommend_grace_terminated")
        if exit_code != 0:
            warnings.append(f"codex_recommend_exec_failed_exit_{exit_code}")
            if stderr_text.strip():
                warnings.append(policy_text_compact(f"codex_stderr:{stderr_text}", max_chars=160))
            return {}, warnings
    except Exception as exc:
        warnings.append(f"codex_recommend_exception:{exc}")
        return {}, warnings

    message_texts: list[str] = []
    for line in stdout_text.splitlines():
        cleaned = str(line or "").strip()
        if not cleaned:
            continue
        try:
            event = json.loads(cleaned)
        except Exception:
            continue
        if isinstance(event, dict):
            msg_text = _extract_codex_event_text(event)
            if msg_text:
                message_texts.append(msg_text)
    json_candidates: list[dict[str, Any]] = []
    for text in message_texts:
        json_candidates.extend(_extract_json_objects(text))
    if not json_candidates:
        json_candidates.extend(_extract_json_objects(stdout_text))
    if not json_candidates:
        warnings.append("codex_recommend_output_invalid_json")
        return {}, warnings
    if len(json_candidates) > 1:
        warnings.append("codex_recommend_multiple_json_objects")
    normalized = _normalize_policy_recommendation_payload(json_candidates[-1])
    if not normalized:
        warnings.append("codex_recommend_payload_invalid")
        return {}, warnings
    return normalized, warnings


def recommend_agent_policy(
    *,
    agent_name: str,
    instruction: str,
    role_profile: str,
    session_goal: str,
    duty_constraints: list[str],
    codex_workspace_root: Path | None = None,
) -> tuple[dict[str, Any], str, list[str]]:
    warnings: list[str] = []
    fallback = _fallback_policy_recommendation(
        agent_name=agent_name,
        instruction=instruction,
        role_profile=role_profile,
        session_goal=session_goal,
        duty_constraints=duty_constraints,
    )
    current_payload = {
        "role_profile": str(role_profile or "").strip(),
        "session_goal": str(session_goal or "").strip(),
        "duty_constraints": [str(item).strip() for item in (duty_constraints or []) if str(item or "").strip()],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是角色策略生成器。仅输出 JSON 对象，不要输出 Markdown。"
                "JSON 必须包含 role_profile(string), session_goal(string), duty_constraints(array[string])。"
                "内容必须具体、可执行、边界清晰，且不得违反用户输入约束。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "agent_name": str(agent_name or "").strip(),
                    "instruction": str(instruction or "").strip(),
                    "current_policy": current_payload,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = chat_once(messages)
        parsed = _extract_first_json_object(raw)
        normalized = _normalize_policy_recommendation_payload(parsed)
        if normalized:
            return normalized, "ai", warnings
        warnings.append("ai_output_invalid_fallback_used")
    except AgentConfigError:
        warnings.append("agent_runtime_not_configured_fallback_used")
    except AgentRuntimeError as exc:
        warnings.append(f"agent_runtime_error_fallback_used:{exc}")
    except Exception as exc:
        warnings.append(f"ai_recommend_unexpected_error:{exc}")

    if codex_workspace_root is not None:
        codex_recommendation, codex_warnings = _recommend_agent_policy_via_codex(
            workspace_root=codex_workspace_root,
            agent_name=agent_name,
            instruction=instruction,
            role_profile=role_profile,
            session_goal=session_goal,
            duty_constraints=duty_constraints,
        )
        warnings.extend(codex_warnings)
        if codex_recommendation:
            return codex_recommendation, "codex_exec", warnings

    return fallback, "template_fallback", warnings


def validate_policy_recommend_instruction(text: str) -> tuple[bool, str]:
    raw = str(text or "").strip()
    if not raw:
        return False, "请先输入一句话优化需求。"
    compact = re.sub(r"\s+", "", raw)
    semantic = re.sub(r"[，。！？；：、,.;:!?~`'\"“”‘’（）()【】\[\]{}<>《》_/\\|\-]+", "", compact)
    if len(semantic) < 6:
        return False, "信息过少，请补充具体目标、边界或场景。"
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", semantic):
        return False, "缺少可识别语义，请补充关键目标或约束。"
    weak_tokens = {
        "优化",
        "优化一下",
        "改一下",
        "调整一下",
        "随便",
        "都行",
        "同上",
        "一样",
        "继续",
        "默认",
        "test",
        "ok",
        "none",
    }
    if semantic.lower() in weak_tokens:
        return False, "内容过于笼统，请补充具体优化方向。"
    normalized_lower = raw.lower()
    direction_tokens = (
        "参考业界实践",
        "业界实践",
        "最佳实践",
        "best practice",
        "industry practice",
        "目标",
        "边界",
        "约束",
        "风险",
        "必须",
        "禁止",
        "前置",
        "场景",
        "用户",
        "步骤",
        "流程",
        "输出",
        "格式",
        "证据",
        "一致",
        "评分",
        "门禁",
        "缓存",
        "性能",
        "安全",
        "补充",
        "完善",
        "修复",
        "收敛",
        "细化",
        "清晰",
        "清楚",
        "可执行",
        "可追溯",
    )
    has_direction = any(token in normalized_lower for token in direction_tokens)
    if not has_direction:
        if re.search(r"如果.*(没有|无|未发现).*(优化|改进|问题).*(不优化|不改|保持|不变)", raw):
            has_direction = True
    if not has_direction:
        return False, "未识别到明确优化方向，请补充要优化的目标、边界或参考标准。"
    return True, ""


def validate_policy_fields(role_profile: str, session_goal: str, duty_constraints: str) -> tuple[bool, str]:
    role_text = str(role_profile or "").strip()
    goal_text = str(session_goal or "").strip()
    duty_text = str(duty_constraints or "").strip()
    if not role_text:
        return False, "missing_role_profile"
    if not goal_text:
        return False, "missing_session_goal"
    if not duty_text:
        return False, "missing_duty_constraints"
    return True, ""


def build_session_policy_snapshot(
    *,
    agent_name: str,
    agents_path: str,
    agents_hash: str,
    agents_version: str,
    role_profile: str,
    session_goal: str,
    duty_constraints: str,
    policy_source: str = "auto",
) -> dict[str, Any]:
    source_kind = str(policy_source or "auto").strip().lower()
    if source_kind not in {"auto", "manual_fallback"}:
        source_kind = "auto"
    return {
        "version": 1,
        "agent_name": str(agent_name or ""),
        "source": {
            "agents_path": str(agents_path or ""),
            "agents_hash": str(agents_hash or ""),
            "agents_version": str(agents_version or ""),
            "policy_source": source_kind,
        },
        "role_profile": str(role_profile or ""),
        "session_goal": str(session_goal or ""),
        "duty_constraints": str(duty_constraints or ""),
    }


def session_policy_summary(snapshot: dict[str, Any], *, max_chars: int = 220) -> str:
    goal = str(snapshot.get("session_goal") or "").strip()
    duty = str(snapshot.get("duty_constraints") or "").strip()
    text = f"goal={goal}; constraints={duty}"
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) > max_chars:
        return compact[:max_chars].rstrip() + "..."
    return compact


def append_policy_to_analysis_summary(summary: str, snapshot: dict[str, Any] | None) -> str:
    text = str(summary or "").strip()
    if "policy_alignment=" in text:
        return text
    if not snapshot:
        marker = f"policy_alignment={POLICY_ALIGNMENT_DEVIATED}"
        return marker if not text else f"{text}; {marker}"
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    source_type = session_policy_source_type(snapshot)
    extras = [
        f"policy_alignment={POLICY_ALIGNMENT_ALIGNED}",
        f"policy_source={source_type}",
        f"policy_goal={first_non_empty_sentence(str(snapshot.get('session_goal') or ''), max_chars=80)}",
        f"policy_source_version={str((source or {}).get('agents_version') or '')}",
    ]
    if not text:
        return "; ".join(extras)
    return f"{text}; {'; '.join(extras)}"


def parse_policy_snapshot_json(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def session_policy_source_type(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return "auto"
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    value = str((source or {}).get("policy_source") or snapshot.get("policy_source") or "auto").strip().lower()
    if value not in {"auto", "manual_fallback"}:
        return "auto"
    return value


def extract_policy_snapshot_from_agent_item(item: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    role_profile = str(item.get("role_profile") or "").strip()
    session_goal = str(item.get("session_goal") or "").strip()
    duty_raw = item.get("duty_constraints")
    duty_items: list[str] = []
    if isinstance(duty_raw, list):
        duty_items = [str(v).strip() for v in duty_raw if str(v or "").strip()]
    elif isinstance(duty_raw, str):
        duty_items = [line_clean_for_summary(v) for v in duty_raw.splitlines() if line_clean_for_summary(v)]
    duty_constraints = str(item.get("duty_constraints_text") or "").strip()
    if not duty_constraints and duty_items:
        duty_constraints = "\n".join(duty_items)
    parse_status = str(item.get("parse_status") or "").strip().lower()
    if parse_status == "failed":
        return None, str(item.get("policy_error") or "policy_extract_failed")
    ok, reason = validate_policy_fields(role_profile, session_goal, duty_constraints)
    if not ok:
        return None, str(item.get("policy_error") or reason or "policy_extract_failed")
    return (
        build_session_policy_snapshot(
            agent_name=str(item.get("agent_name") or ""),
            agents_path=str(item.get("agents_md_path") or ""),
            agents_hash=str(item.get("agents_hash") or ""),
            agents_version=str(item.get("agents_version") or ""),
            role_profile=role_profile,
            session_goal=session_goal,
            duty_constraints=duty_constraints,
        ),
        "",
    )


def normalize_duty_constraints_input(raw: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()

    def is_heading_or_placeholder(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return True
        compact = re.sub(r"[\s:：()（）_./\\-]+", "", value.lower())
        if compact in {
            "must",
            "mustnot",
            "preconditions",
            "precondition",
            "must必须项",
            "mustnot禁止项",
            "preconditions前置条件",
            "职责边界",
            "无",
            "none",
            "n/a",
        }:
            return True
        if value in {"(无)", "-", "--", "---"}:
            return True
        return False

    def push(text: str) -> None:
        cleaned = line_clean_for_summary(text)
        if not cleaned:
            return
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return
        if is_heading_or_placeholder(cleaned):
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        values.append(cleaned)

    if isinstance(raw, list):
        for item in raw:
            part = str(item or "").strip()
            if not part:
                continue
            for seg in re.split(r"\r?\n|[；;]", part):
                push(seg)
    else:
        text = str(raw or "").strip()
        if text:
            for seg in re.split(r"\r?\n|[；;]", text):
                push(seg)
    return values


def _policy_codex_failure_payload(
    item: dict[str, Any],
    *,
    policy_error: str,
    analysis_chain: dict[str, Any],
) -> dict[str, Any]:
    node = item if isinstance(item, dict) else {}
    chain = analysis_chain if isinstance(analysis_chain, dict) else {}
    detail_code = str(policy_error or node.get("policy_error") or "").strip().lower()
    parse_status = str(node.get("parse_status") or "").strip().lower()
    contract_status = str(node.get("policy_contract_status") or "").strip().lower()
    if not detail_code and parse_status == "failed":
        detail_code = "policy_contract_invalid" if contract_status == "failed" else "policy_extract_failed"
    if not detail_code:
        return {}
    files = chain.get("files") if isinstance(chain.get("files"), dict) else {}
    return build_codex_failure(
        feature_key="policy_analysis",
        attempt_id=str(files.get("trace_dir") or node.get("agents_hash") or "").strip(),
        attempt_count=1,
        failure_detail_code=detail_code,
        failure_message=str(
            policy_error
            or node.get("policy_gate_reason")
            or node.get("clarity_gate_reason")
            or node.get("policy_error")
            or ""
        ).strip(),
        failure_stage="contract_validate" if detail_code == "policy_contract_invalid" else "",
        retry_action=build_retry_action(
            "retry_policy_analysis",
            payload={
                "agent_name": str(node.get("agent_name") or "").strip(),
                "agents_path": str(node.get("agents_md_path") or "").strip(),
            },
        ),
        trace_refs=files,
        failed_at=str(node.get("policy_cache_cached_at") or "").strip(),
    )


def agent_policy_gate_payload(
    item: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None,
    policy_error: str = "",
    allow_manual_policy_input: bool = False,
) -> dict[str, Any]:
    duty_items = normalize_duty_constraints_input(
        item.get("duty_constraints")
        if isinstance(item.get("duty_constraints"), list)
        else item.get("duty_constraints_text")
    )
    duty_text = str(item.get("duty_constraints_text") or "").strip()
    if not duty_text and duty_items:
        duty_text = "\n".join(duty_items)
    source = snapshot.get("source") if snapshot and isinstance(snapshot.get("source"), dict) else {}
    extracted_policy = {
        "role_profile": str(item.get("role_profile") or ""),
        "session_goal": str(item.get("session_goal") or ""),
        "duty_constraints": duty_items,
        "duty_constraints_text": duty_text,
    }
    constraints_payload = (
        item.get("constraints")
        if isinstance(item.get("constraints"), dict)
        else {
            "must": [],
            "must_not": [],
            "preconditions": [],
            "issues": [],
            "conflicts": [],
            "missing_evidence_count": 0,
            "total": 0,
        }
    )
    score_dimensions_payload = item.get("score_dimensions") if isinstance(item.get("score_dimensions"), dict) else {}
    score_weights_payload = item.get("score_weights") if isinstance(item.get("score_weights"), dict) else {}
    parse_status = str(item.get("parse_status") or "failed").strip().lower() or "failed"
    clarity_score = int(item.get("clarity_score") or 0)
    manual_fallback_allowed = bool(allow_manual_policy_input)
    analysis_chain = item.get("analysis_chain") if isinstance(item.get("analysis_chain"), dict) else {}
    codex_failure = _policy_codex_failure_payload(
        item,
        policy_error=str(policy_error or "").strip(),
        analysis_chain=analysis_chain,
    )
    return {
        "agent_name": str(item.get("agent_name") or ""),
        "agents_hash": str(item.get("agents_hash") or ""),
        "agents_version": str(item.get("agents_version") or ""),
        "agents_path": str(item.get("agents_md_path") or ""),
        "parse_status": parse_status,
        "parse_warnings": [
            str(v).strip()
            for v in (item.get("parse_warnings") or [])
            if str(v or "").strip()
        ],
        "clarity_score": clarity_score,
        "clarity_details": item.get("clarity_details")
        if isinstance(item.get("clarity_details"), dict)
        else {},
        "clarity_gate": str(item.get("clarity_gate") or "block"),
        "clarity_gate_reason": str(item.get("clarity_gate_reason") or ""),
        "risk_tips": [
            str(v).strip()
            for v in (item.get("risk_tips") or [])
            if str(v or "").strip()
        ],
        "evidence_snippets": item.get("evidence_snippets")
        if isinstance(item.get("evidence_snippets"), dict)
        else {"role": "", "goal": "", "duty": ""},
        "constraints": constraints_payload,
        "score_model": str(item.get("score_model") or POLICY_SCORE_MODEL),
        "score_total": int(item.get("score_total") or clarity_score),
        "score_weights": score_weights_payload if score_weights_payload else dict(POLICY_SCORE_WEIGHTS),
        "score_dimensions": score_dimensions_payload,
        "extracted_policy": extracted_policy,
        "policy_extract_source": str(item.get("policy_extract_source") or POLICY_EXTRACT_SOURCE),
        "policy_prompt_version": str(item.get("policy_prompt_version") or POLICY_PROMPT_VERSION),
        "policy_contract_status": str(item.get("policy_contract_status") or "failed"),
        "policy_contract_missing_fields": [
            str(v).strip()
            for v in (item.get("policy_contract_missing_fields") or [])
            if str(v or "").strip()
        ],
        "policy_contract_issues": [
            str(v).strip()
            for v in (item.get("policy_contract_issues") or [])
            if str(v or "").strip()
        ],
        "policy_gate_state": str(item.get("policy_gate_state") or ""),
        "policy_gate_reason": str(item.get("policy_gate_reason") or ""),
        "analysis_chain": analysis_chain,
        "source": {
            "agents_hash": str((source or {}).get("agents_hash") or item.get("agents_hash") or ""),
            "agents_version": str((source or {}).get("agents_version") or item.get("agents_version") or ""),
            "agents_path": str((source or {}).get("agents_path") or item.get("agents_md_path") or ""),
            "extract_source": str(item.get("policy_extract_source") or POLICY_EXTRACT_SOURCE),
        },
        "allow_manual_policy_input": bool(allow_manual_policy_input),
        "manual_fallback_allowed": manual_fallback_allowed,
        "policy_cache_hit": bool(item.get("policy_cache_hit")),
        "policy_cache_status": str(item.get("policy_cache_status") or ""),
        "policy_cache_reason": str(item.get("policy_cache_reason") or ""),
        "policy_cache_cached_at": str(item.get("policy_cache_cached_at") or ""),
        "policy_cache_trace": [
            {
                "step": str((step or {}).get("step") or ""),
                "status": str((step or {}).get("status") or ""),
                "detail": str((step or {}).get("detail") or ""),
            }
            for step in (item.get("policy_cache_trace") or [])
            if isinstance(step, dict)
        ],
        "policy_error": str(policy_error or ""),
        "codex_failure": codex_failure,
    }


def _normalize_policy_warning_codes(raw: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    source = raw if isinstance(raw, list) else []
    for item in source:
        code = str(item or "").strip()
        if not code:
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out
