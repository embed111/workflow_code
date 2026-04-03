from __future__ import annotations

from workflow_app.server.services.codex_exec_monitor import resolve_codex_command, run_monitored_subprocess

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

def _policy_extract_trace_dir(runtime_root: Path, agent_name: str, agents_hash: str) -> Path:
    stamp = now_local().strftime("%Y%m%d-%H%M%S-%f")
    token = safe_token(agent_name, "agent", 40) or "agent"
    digest = safe_token(str(agents_hash or "")[:10], "nohash", 16) or "nohash"
    trace_dir = policy_extract_trace_root(runtime_root) / f"{stamp}-{token}-{digest}"
    trace_dir.mkdir(parents=True, exist_ok=True)
    return trace_dir


def _write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _extract_codex_event_text(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type") or "").strip()
    if event_type != "item.completed":
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
    if isinstance(content, list):
        parts: list[str] = []
        for node in content:
            if not isinstance(node, dict):
                continue
            text_part = str(node.get("text") or node.get("output_text") or "").strip()
            if text_part:
                parts.append(text_part)
        return "\n".join(parts).strip()
    return ""


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
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


def _normalize_string_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v or "").strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    return [line_clean_for_summary(v) for v in text.splitlines() if line_clean_for_summary(v)]


def _normalize_responsibility_entries(raw: Any, source_title: str) -> tuple[list[dict[str, str]], int, int]:
    out: list[dict[str, str]] = []
    legacy_schema_count = 0
    missing_evidence_count = 0
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("content") or "").strip()
                if not text:
                    continue
                evidence = policy_text_compact(str(item.get("evidence") or ""), max_chars=420)
                if not evidence:
                    missing_evidence_count += 1
                out.append(
                    {
                        "text": policy_text_compact(text, max_chars=280),
                        "evidence": evidence,
                        "source_title": str(item.get("source_title") or source_title),
                    }
                )
                continue
            text = str(item or "").strip()
            if not text:
                continue
            legacy_schema_count += 1
            missing_evidence_count += 1
            out.append(
                {
                    "text": policy_text_compact(text, max_chars=280),
                    "evidence": "",
                    "source_title": source_title,
                }
            )
        return out, legacy_schema_count, missing_evidence_count
    for text in _normalize_string_list(raw):
        legacy_schema_count += 1
        missing_evidence_count += 1
        out.append(
            {
                "text": policy_text_compact(text, max_chars=280),
                "evidence": "",
                "source_title": source_title,
            }
        )
    return out, legacy_schema_count, missing_evidence_count


def _collect_evidence_snippets(raw_result: dict[str, Any], constraints: dict[str, Any]) -> dict[str, str]:
    evidence_raw = raw_result.get("evidence")
    snippets = {"role": "", "goal": "", "duty": ""}
    if isinstance(evidence_raw, dict):
        snippets["role"] = str(evidence_raw.get("role") or evidence_raw.get("role_profile") or "").strip()
        snippets["goal"] = str(evidence_raw.get("goal") or evidence_raw.get("session_goal") or "").strip()
        snippets["duty"] = str(evidence_raw.get("duty") or evidence_raw.get("responsibilities") or "").strip()
    elif isinstance(evidence_raw, list):
        for node in evidence_raw:
            if not isinstance(node, dict):
                continue
            field = str(node.get("field") or node.get("type") or "").strip().lower()
            snippet = str(node.get("snippet") or node.get("text") or "").strip()
            if not snippet:
                continue
            if field in {"role", "role_profile"} and not snippets["role"]:
                snippets["role"] = snippet
            elif field in {"goal", "session_goal"} and not snippets["goal"]:
                snippets["goal"] = snippet
            elif field in {"duty", "responsibility", "responsibilities"} and not snippets["duty"]:
                snippets["duty"] = snippet
    evidence_snippets_raw = raw_result.get("evidence_snippets")
    if isinstance(evidence_snippets_raw, dict):
        if not snippets["role"]:
            snippets["role"] = str(evidence_snippets_raw.get("role") or "").strip()
        if not snippets["goal"]:
            snippets["goal"] = str(evidence_snippets_raw.get("goal") or "").strip()
        if not snippets["duty"]:
            snippets["duty"] = str(evidence_snippets_raw.get("duty") or "").strip()
    if not snippets["duty"]:
        duty_evidences: list[str] = []
        for key in ("must", "must_not", "preconditions"):
            for entry in constraints.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                evidence = str(entry.get("evidence") or "").strip()
                if evidence:
                    duty_evidences.append(evidence)
        snippets["duty"] = policy_text_compact("\n\n".join(duty_evidences), max_chars=680) if duty_evidences else ""
    snippets["role"] = policy_text_compact(snippets["role"], max_chars=380)
    snippets["goal"] = policy_text_compact(snippets["goal"], max_chars=320)
    snippets["duty"] = policy_text_compact(snippets["duty"], max_chars=680)
    return snippets


def _build_policy_extract_prompt(
    *,
    workspace_root: Path,
    target_agent_workspace: Path,
    agents_md_path: Path,
) -> str:
    return "\n".join(
        [
            "你是“角色策略提取助手”。请读取指定 AGENTS.md 并输出结构化 JSON，不要输出与 JSON 无关的说明文字。",
            "",
            f"prompt_version: {POLICY_PROMPT_VERSION}",
            "",
            "输入:",
            f"- workspace_root: {workspace_root.as_posix()}",
            f"- target_agent_workspace: {target_agent_workspace.as_posix()}",
            f"- agents_md_path: {agents_md_path.as_posix()}",
            "",
            "任务:",
            "1) 仅基于 AGENTS.md 内容提取:",
            "   - role",
            "   - goal",
            "   - responsibilities.must",
            "   - responsibilities.must_not",
            "   - responsibilities.preconditions",
            "2) 对每个关键结论给 evidence（原文片段或段落定位）。",
            "3) 给出 parse_status、clarity_score(0-100)、clarity_gate(auto|confirm|block)、warnings[]。",
            "4) 若信息不足，必须显式标记 missing_fields[]，不要编造。",
            "5) responsibilities.must/must_not/preconditions 每个元素必须是对象，并且 text 与 evidence 均为非空字符串。",
            "6) evidence 必须是 AGENTS.md 原文摘录或可定位段落（标题+要点），禁止输出空 evidence。",
            "",
            "输出要求:",
            "- 仅输出一个 JSON 对象。",
            "- responsibilities 中不得使用纯字符串数组；每条职责均需 text + evidence。",
            "- 若某条职责无法给出证据，不要编造；在 warnings 增加 constraints_evidence_missing，并在 missing_fields 标注对应职责 evidence 缺失。",
            "- 字段至少包含:",
            "{",
            '  "role": "",',
            '  "goal": "",',
            '  "responsibilities": {',
            '    "must": [{"text": "", "evidence": "", "source_title": "must"}],',
            '    "must_not": [{"text": "", "evidence": "", "source_title": "must_not"}],',
            '    "preconditions": [{"text": "", "evidence": "", "source_title": "preconditions"}]',
            "  },",
            '  "evidence": [],',
            '  "parse_status": "ok|incomplete|failed",',
            '  "clarity_score": 0,',
            '  "clarity_gate": "auto|confirm|block",',
            '  "warnings": [],',
            '  "missing_fields": []',
            "}",
        ]
    )


def _normalize_codex_contract_result(
    raw_result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    role_profile = str(raw_result.get("role_profile") or raw_result.get("role") or "").strip()
    session_goal = str(raw_result.get("session_goal") or raw_result.get("goal") or "").strip()
    responsibilities = raw_result.get("responsibilities") if isinstance(raw_result.get("responsibilities"), dict) else {}
    must_items, must_legacy_count, must_missing_evidence = _normalize_responsibility_entries(
        responsibilities.get("must"),
        "must",
    )
    must_not_items, must_not_legacy_count, must_not_missing_evidence = _normalize_responsibility_entries(
        responsibilities.get("must_not"),
        "must_not",
    )
    pre_items, pre_legacy_count, pre_missing_evidence = _normalize_responsibility_entries(
        responsibilities.get("preconditions"),
        "preconditions",
    )
    duty_constraints_items = [
        str((item or {}).get("text") or "").strip()
        for item in (must_items + must_not_items + pre_items)
        if str((item or {}).get("text") or "").strip()
    ]
    duty_constraints_text = "\n".join(duty_constraints_items).strip()

    parse_warnings = [
        str(item).strip()
        for item in (
            raw_result.get("parse_warnings")
            if isinstance(raw_result.get("parse_warnings"), list)
            else raw_result.get("warnings")
        )
        or []
        if str(item or "").strip()
    ]

    parse_status_raw = str(raw_result.get("parse_status") or "").strip().lower()
    clarity_score_raw = raw_result.get("clarity_score")
    clarity_gate_raw = str(raw_result.get("clarity_gate") or "").strip().lower()
    missing_fields = [
        str(item).strip()
        for item in (raw_result.get("missing_fields") or [])
        if str(item or "").strip()
    ]
    contract_issues: list[str] = []
    required_contract_fields = ("parse_status", "clarity_score", "clarity_gate")
    for key in required_contract_fields:
        if key not in raw_result:
            missing_fields.append(key)
    if parse_status_raw and parse_status_raw not in {"ok", "incomplete", "failed"}:
        contract_issues.append("contract_parse_status_invalid")
    codex_clarity_score: int | None
    try:
        codex_clarity_score = int(clarity_score_raw)
    except Exception:
        codex_clarity_score = None
        contract_issues.append("contract_clarity_score_invalid")
    if clarity_gate_raw and clarity_gate_raw not in {"auto", "confirm", "block"}:
        contract_issues.append("contract_clarity_gate_invalid")

    if not role_profile and "role_profile" not in missing_fields:
        missing_fields.append("role_profile")
    if not session_goal and "session_goal" not in missing_fields:
        missing_fields.append("session_goal")
    if not duty_constraints_items and "duty_constraints" not in missing_fields:
        missing_fields.append("duty_constraints")
    missing_fields = [item for item in dict.fromkeys(missing_fields) if item]
    legacy_schema_count = int(must_legacy_count + must_not_legacy_count + pre_legacy_count)
    normalized_missing_evidence_count = int(must_missing_evidence + must_not_missing_evidence + pre_missing_evidence)

    parse_status = parse_status_raw if parse_status_raw in {"ok", "incomplete", "failed"} else ""
    if missing_fields:
        parse_status = "failed"
        contract_issues.append("missing_required_policy_fields")
    if not parse_status:
        parse_status = "ok"
    if legacy_schema_count > 0:
        if "contract_responsibility_legacy_schema" not in parse_warnings:
            parse_warnings.append("contract_responsibility_legacy_schema")
        parse_status = "incomplete" if parse_status != "failed" else parse_status
    if normalized_missing_evidence_count > 0:
        if "constraints_evidence_missing" not in parse_warnings:
            parse_warnings.append("constraints_evidence_missing")
        parse_status = "incomplete" if parse_status != "failed" else parse_status

    if contract_issues:
        parse_status = "failed"
        for issue in contract_issues:
            if issue not in parse_warnings:
                parse_warnings.append(issue)
    for item in missing_fields:
        code = f"missing_field:{item}"
        if code not in parse_warnings:
            parse_warnings.append(code)
    if parse_status == "failed" and "missing_required_policy_fields" not in parse_warnings and missing_fields:
        parse_warnings.append("missing_required_policy_fields")

    constraints = {
        "must": must_items,
        "must_not": must_not_items,
        "preconditions": pre_items,
        "issues": [],
        "conflicts": [],
        "missing_evidence_count": 0,
        "total": len(must_items) + len(must_not_items) + len(pre_items),
    }
    missing_evidence_count = int(normalized_missing_evidence_count)
    constraints["missing_evidence_count"] = missing_evidence_count
    if constraints["total"] <= 0:
        constraints["issues"].append(
            {
                "code": "constraints_missing",
                "message": "职责边界缺失",
            }
        )
        if "constraints_missing" not in parse_warnings:
            parse_warnings.append("constraints_missing")
    elif missing_evidence_count > 0:
        constraints["issues"].append(
            {
                "code": "constraints_evidence_missing",
                "message": "职责边界存在无证据条目",
            }
        )
        if "constraints_evidence_missing" not in parse_warnings:
            parse_warnings.append("constraints_evidence_missing")

    evidence_snippets = _collect_evidence_snippets(raw_result, constraints)
    clarity = compute_policy_clarity(
        role_profile=role_profile,
        session_goal=session_goal,
        duty_constraints=duty_constraints_items,
        parse_status=parse_status,
        parse_warnings=parse_warnings,
        evidence_snippets=evidence_snippets,
        constraints=constraints,
    )
    clarity_score = int(clarity.get("clarity_score") or 0)
    clarity_gate = str(clarity.get("clarity_gate") or "block").strip().lower() or "block"
    gate_reason = str(clarity.get("clarity_gate_reason") or "").strip()
    score_dimensions = clarity.get("score_dimensions") if isinstance(clarity.get("score_dimensions"), dict) else {}
    score_weights = clarity.get("score_weights") if isinstance(clarity.get("score_weights"), dict) else {}

    payload = {
        "duty_title": "职责边界",
        "duty_excerpt": first_non_empty_sentence(duty_constraints_text, max_chars=120),
        "duty_text": duty_constraints_text,
        "duty_truncated": False,
        "role_profile": role_profile,
        "session_goal": session_goal,
        "duty_constraints": duty_constraints_items,
        "duty_constraints_text": duty_constraints_text,
        "constraints": constraints,
        "parse_status": parse_status,
        "parse_warnings": parse_warnings,
        "evidence_snippets": evidence_snippets,
        "score_model": POLICY_SCORE_MODEL,
        "score_total": max(0, min(100, int(clarity.get("score_total") or clarity_score))),
        "score_weights": score_weights if score_weights else dict(POLICY_SCORE_WEIGHTS),
        "score_dimensions": score_dimensions,
        "clarity_score": max(0, min(100, clarity_score)),
        "clarity_details": clarity.get("clarity_details") if isinstance(clarity.get("clarity_details"), dict) else {},
        "clarity_gate": clarity_gate,
        "clarity_gate_reason": gate_reason,
        "risk_tips": [str(item).strip() for item in (clarity.get("risk_tips") or []) if str(item or "").strip()],
        "policy_extract_ok": bool(
            parse_status in {"ok", "incomplete"} and role_profile and session_goal and duty_constraints_text
        ),
        "policy_error": "",
    }

    contract_info = {
        "contract_status": parse_status if parse_status in {"ok", "incomplete"} else "failed",
        "contract_missing_fields": missing_fields,
        "contract_issues": contract_issues,
        "codex_clarity_score": codex_clarity_score,
        "codex_clarity_gate": clarity_gate_raw if clarity_gate_raw in {"auto", "confirm", "block"} else "",
    }
    return payload, contract_info


def build_agent_policy_payload_via_codex(
    *,
    runtime_root: Path,
    workspace_root: Path,
    agent_name: str,
    agents_file: Path,
    agents_hash: str,
    agents_version: str,
) -> dict[str, Any]:
    trace_dir = _policy_extract_trace_dir(runtime_root, agent_name, agents_hash)
    prompt_path = trace_dir / "prompt.txt"
    stdout_path = trace_dir / "stdout.txt"
    stderr_path = trace_dir / "stderr.txt"
    raw_result_path = trace_dir / "codex-result.raw.json"
    parsed_result_path = trace_dir / "parsed-result.json"
    gate_decision_path = trace_dir / "gate-decision.json"

    workspace_root = workspace_root.resolve(strict=False)
    agents_path = agents_file.resolve(strict=False)
    target_workspace = agents_path.parent.resolve(strict=False)
    prompt_text = _build_policy_extract_prompt(
        workspace_root=workspace_root,
        target_agent_workspace=target_workspace,
        agents_md_path=agents_path,
    )
    _write_text_file(prompt_path, prompt_text)

    analysis_started_ms = int(time.time() * 1000)
    running_started_ms = 0
    running_finished_ms = 0
    analyzed_started_ms = 0
    analyzed_finished_ms = 0

    stdout_text = ""
    stderr_text = ""
    codex_result_raw: dict[str, Any] = {}
    codex_events: list[dict[str, Any]] = []
    codex_exit_code: int | None = None
    parse_warnings: list[str] = []
    policy_error = ""
    monitor_info: dict[str, Any] = {}
    scope_hint = (
        f"workspace_root={workspace_root.as_posix()} ; target_agents_path={agents_path.as_posix()} ; "
        "expect target path under workspace root and workspace root contains workflow/."
    )
    workspace_ok, workspace_error = validate_workspace_root_semantics(workspace_root)
    target_in_scope = path_in_scope(agents_path, workspace_root)
    if not workspace_ok:
        policy_error = workspace_error
    elif not target_in_scope:
        policy_error = AGENT_POLICY_OUT_OF_SCOPE_CODE
    elif not agents_path.exists() or not agents_path.is_file():
        policy_error = "agents_md_not_found"

    command: list[str] = []
    command_summary = "codex exec --json --skip-git-repo-check --sandbox workspace-write --add-dir <workspace_root> -C <workspace_root> -"
    codex_bin = resolve_codex_command()
    if not policy_error and not codex_bin:
        policy_error = "codex_command_not_found"
    if codex_bin:
        command = [
            codex_bin,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "--add-dir",
            workspace_root.as_posix(),
            "-C",
            workspace_root.as_posix(),
            "-",
        ]

    if not policy_error and command:
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
                cwd=workspace_root,
                stdin_text=prompt_text,
                on_stdout_line=_observe_stdout,
                completion_checker=lambda: bool(completion_state["ready"]),
            )
            running_started_ms = int(result.started_at_ms or 0)
            running_finished_ms = int(result.finished_at_ms or 0)
            stdout_text = result.stdout_text
            stderr_text = result.stderr_text
            codex_exit_code = result.exit_code
            monitor_info = dict(result.monitor or {})
            if result.forced_exit_after_result:
                parse_warnings.append("codex_exec_grace_terminated")
            if codex_exit_code != 0:
                policy_error = f"codex_exec_failed_exit_{codex_exit_code}"
        except Exception as exc:
            policy_error = f"codex_exec_exception:{exc}"
    _write_text_file(stdout_path, stdout_text)
    _write_text_file(stderr_path, stderr_text)

    analyzed_started_ms = int(time.time() * 1000)

    if not policy_error:
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
                codex_events.append(event)
                msg_text = _extract_codex_event_text(event)
                if msg_text:
                    message_texts.append(msg_text)
        json_candidates: list[dict[str, Any]] = []
        for text in message_texts:
            json_candidates.extend(_extract_json_objects(text))
        if not json_candidates:
            json_candidates.extend(_extract_json_objects(stdout_text))
        if len(json_candidates) > 1:
            parse_warnings.append("multiple_json_objects_detected")
        if json_candidates:
            codex_result_raw = json_candidates[-1]
            _write_json_file(raw_result_path, codex_result_raw)
        else:
            policy_error = "codex_output_invalid_json"
            parse_warnings.append("codex_output_invalid_json")

    payload: dict[str, Any]
    contract_info: dict[str, Any]
    if codex_result_raw:
        payload, contract_info = _normalize_codex_contract_result(codex_result_raw)
    else:
        payload = {
            "duty_title": "职责边界",
            "duty_excerpt": "",
            "duty_text": "",
            "duty_truncated": False,
            "role_profile": "",
            "session_goal": "",
            "duty_constraints": [],
            "duty_constraints_text": "",
            "constraints": {
                "must": [],
                "must_not": [],
                "preconditions": [],
                "issues": [{"code": "constraints_missing", "message": "职责边界缺失"}],
                "conflicts": [],
                "missing_evidence_count": 0,
                "total": 0,
            },
            "parse_status": "failed",
            "parse_warnings": [],
            "evidence_snippets": {"role": "", "goal": "", "duty": ""},
            "score_model": POLICY_SCORE_MODEL,
            "score_total": 0,
            "score_weights": dict(POLICY_SCORE_WEIGHTS),
            "score_dimensions": {},
            "clarity_score": 0,
            "clarity_details": {},
            "clarity_gate": "block",
            "clarity_gate_reason": "parse_failed",
            "risk_tips": ["策略提取失败，无法保证会话与训练一致约束。"],
            "policy_extract_ok": False,
            "policy_error": "",
        }
        contract_info = {
            "contract_status": "failed",
            "contract_missing_fields": ["role_profile", "session_goal", "duty_constraints"],
            "contract_issues": [],
            "codex_clarity_score": None,
            "codex_clarity_gate": "",
        }

    if parse_warnings:
        for warn in parse_warnings:
            if warn not in payload["parse_warnings"]:
                payload["parse_warnings"].append(warn)

    if policy_error:
        payload["parse_status"] = "failed"
        payload["clarity_gate"] = "block"
        payload["clarity_gate_reason"] = "parse_failed"
        payload["policy_extract_ok"] = False
        payload["policy_error"] = policy_error
        code = f"policy_error:{policy_error}"
        if code not in payload["parse_warnings"]:
            payload["parse_warnings"].append(code)
        if policy_error == AGENT_POLICY_OUT_OF_SCOPE_CODE:
            if "target_agents_path_out_of_scope" not in payload["parse_warnings"]:
                payload["parse_warnings"].append("target_agents_path_out_of_scope")
            contract_info["contract_missing_fields"] = list(
                dict.fromkeys(list(contract_info.get("contract_missing_fields") or []) + ["target_agents_path_scope"])
            )
            contract_info["contract_status"] = "failed"

    gate_state = "policy_ready"
    if str(payload.get("parse_status") or "").strip().lower() == "failed" or str(payload.get("clarity_gate") or "").strip().lower() == "block":
        gate_state = "policy_failed"
    elif str(payload.get("clarity_gate") or "").strip().lower() == "confirm":
        gate_state = "policy_needs_confirm"
    gate_decision = {
        "policy_extract_source": POLICY_EXTRACT_SOURCE,
        "prompt_version": POLICY_PROMPT_VERSION,
        "parse_status": str(payload.get("parse_status") or "failed"),
        "clarity_gate": str(payload.get("clarity_gate") or "block"),
        "clarity_score": int(payload.get("clarity_score") or 0),
        "session_gate": gate_state,
        "policy_error": str(payload.get("policy_error") or ""),
        "contract_status": str(contract_info.get("contract_status") or "failed"),
        "contract_missing_fields": [
            str(item).strip()
            for item in (contract_info.get("contract_missing_fields") or [])
            if str(item or "").strip()
        ],
        "contract_issues": [
            str(item).strip()
            for item in (contract_info.get("contract_issues") or [])
            if str(item or "").strip()
        ],
        "workspace_root": workspace_root.as_posix(),
        "workspace_root_valid": bool(workspace_ok),
        "workspace_root_error": workspace_error,
        "target_agents_path": agents_path.as_posix(),
        "target_in_scope": bool(target_in_scope),
        "scope_hint": scope_hint,
        "command_summary": command_summary,
        "codex_exit_code": codex_exit_code,
        "fail_closed": bool(gate_state == "policy_failed"),
    }
    _write_json_file(parsed_result_path, payload)
    _write_json_file(gate_decision_path, gate_decision)
    analyzed_finished_ms = int(time.time() * 1000)

    parsed_json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    gate_json_text = json.dumps(gate_decision, ensure_ascii=False, indent=2)
    raw_json_text = json.dumps(codex_result_raw, ensure_ascii=False, indent=2) if codex_result_raw else ""
    analysis_chain = {
        "source": POLICY_EXTRACT_SOURCE,
        "prompt_version": POLICY_PROMPT_VERSION,
        "workspace_root": workspace_root.as_posix(),
        "workspace_root_valid": bool(workspace_ok),
        "workspace_root_error": workspace_error,
        "target_agent_workspace": target_workspace.as_posix(),
        "target_agents_path": agents_path.as_posix(),
        "target_in_scope": bool(target_in_scope),
        "scope_hint": scope_hint,
        "command_summary": command_summary,
        "command": command,
        "codex_exit_code": codex_exit_code,
        "monitor": monitor_info,
        "contract_status": str(contract_info.get("contract_status") or "failed"),
        "contract_missing_fields": [
            str(item).strip()
            for item in (contract_info.get("contract_missing_fields") or [])
            if str(item or "").strip()
        ],
        "contract_issues": [
            str(item).strip()
            for item in (contract_info.get("contract_issues") or [])
            if str(item or "").strip()
        ],
        "files": {
            "trace_dir": relative_to_root(runtime_root, trace_dir),
            "prompt": relative_to_root(runtime_root, prompt_path),
            "stdout": relative_to_root(runtime_root, stdout_path),
            "stderr": relative_to_root(runtime_root, stderr_path),
            "codex_result_raw": relative_to_root(runtime_root, raw_result_path) if codex_result_raw else "",
            "parsed_result": relative_to_root(runtime_root, parsed_result_path),
            "gate_decision": relative_to_root(runtime_root, gate_decision_path),
        },
        "content": {
            "prompt": prompt_text,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "codex_result_raw": raw_json_text,
            "parsed_result": parsed_json_text,
            "gate_decision": gate_json_text,
        },
        "codex_events_count": len(codex_events),
    }
    ready_end_ms = running_started_ms if running_started_ms > 0 else analyzed_started_ms
    done_finished_ms = int(time.time() * 1000)
    analysis_start_norm = max(0, int(analysis_started_ms or 0))
    ready_end_norm = max(analysis_start_norm, int(ready_end_ms or 0))
    running_start_norm = max(0, int(running_started_ms or 0))
    running_end_norm = max(0, int(running_finished_ms or 0))
    if running_start_norm > 0 and running_end_norm < running_start_norm:
        running_end_norm = running_start_norm
    analyzed_start_norm = max(0, int(analyzed_started_ms or 0))
    analyzed_end_norm = max(0, int(analyzed_finished_ms or 0))
    if analyzed_start_norm <= 0:
        analyzed_start_norm = running_end_norm if running_end_norm > 0 else ready_end_norm
    if analyzed_end_norm < analyzed_start_norm:
        analyzed_end_norm = analyzed_start_norm
    done_end_norm = max(analyzed_end_norm, int(done_finished_ms or 0))
    done_start_norm = analyzed_end_norm

    def _dur_ms(start_ms: int, end_ms: int) -> int:
        if start_ms <= 0 or end_ms <= 0:
            return 0
        if end_ms < start_ms:
            return 0
        return int(end_ms - start_ms)

    analysis_chain["ui_progress"] = {
        "source": "codex_exec",
        "active": False,
        "failed": bool(str(payload.get("parse_status") or "").strip().lower() == "failed" or policy_error),
        "started_at_ms": analysis_start_norm,
        "finished_at_ms": done_end_norm,
        "total_ms": _dur_ms(analysis_start_norm, done_end_norm),
        "stages": [
            {
                "index": 1,
                "key": "ready",
                "label": "codex与agent信息就绪",
                "started_at_ms": analysis_start_norm,
                "duration_ms": _dur_ms(analysis_start_norm, ready_end_norm),
            },
            {
                "index": 2,
                "key": "running",
                "label": "codex分析中",
                "started_at_ms": running_start_norm,
                "duration_ms": _dur_ms(running_start_norm, running_end_norm),
            },
            {
                "index": 3,
                "key": "analyzed",
                "label": "codex分析完成",
                "started_at_ms": analyzed_start_norm,
                "duration_ms": _dur_ms(analyzed_start_norm, analyzed_end_norm),
            },
            {
                "index": 4,
                "key": "done",
                "label": "角色分析结束",
                "started_at_ms": done_start_norm,
                "duration_ms": _dur_ms(done_start_norm, done_end_norm),
            },
        ],
    }
    payload["policy_extract_source"] = POLICY_EXTRACT_SOURCE
    payload["policy_prompt_version"] = POLICY_PROMPT_VERSION
    payload["analysis_chain"] = analysis_chain
    payload["policy_contract_status"] = str(contract_info.get("contract_status") or "failed")
    payload["policy_contract_missing_fields"] = [
        str(item).strip()
        for item in (contract_info.get("contract_missing_fields") or [])
        if str(item or "").strip()
    ]
    payload["policy_contract_issues"] = [
        str(item).strip()
        for item in (contract_info.get("contract_issues") or [])
        if str(item or "").strip()
    ]
    payload["policy_gate_state"] = gate_state
    payload["policy_gate_reason"] = str(gate_decision.get("policy_error") or gate_decision.get("clarity_gate") or "")

    _write_json_file(parsed_result_path, payload)
    return payload


