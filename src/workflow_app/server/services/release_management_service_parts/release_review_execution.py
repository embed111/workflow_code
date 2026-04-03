
from workflow_app.server.services.codex_exec_monitor import resolve_codex_command, run_monitored_subprocess


def _write_release_review_profile_assets(
    *,
    root: Path,
    trace_dir: Path,
    agent: dict[str, Any],
    review_id: str,
    report: dict[str, Any],
    analysis_chain: dict[str, Any],
) -> dict[str, Any]:
    snapshot = _build_release_public_profile_snapshot(
        agent=agent,
        report=report,
        analysis_chain=analysis_chain,
        review_id=review_id,
    )
    public_profile_path = trace_dir / "public-role-profile.md"
    capability_snapshot_path = trace_dir / "capability-snapshot.json"
    _write_release_review_text(public_profile_path, _build_release_public_profile_markdown(snapshot))
    snapshot["public_profile_ref"] = _path_for_ui(root, public_profile_path)
    snapshot["capability_snapshot_ref"] = _path_for_ui(root, capability_snapshot_path)
    _write_release_review_json(capability_snapshot_path, snapshot)
    return {
        "public_profile_markdown_path": snapshot["public_profile_ref"],
        "capability_snapshot_json_path": snapshot["capability_snapshot_ref"],
        "snapshot": snapshot,
    }


def _workspace_current_ref(workspace: Path) -> str:
    ok, out = _run_git_readonly(workspace, ["rev-parse", "--short", "HEAD"], timeout_s=12)
    return str(out or "").strip() if ok else ""


def _next_release_version_label(release_labels: list[str], preferred: str = "") -> str:
    labels = [str(item or "").strip() for item in release_labels if str(item or "").strip()]
    used = set(labels)
    preferred_text = str(preferred or "").strip()
    if preferred_text and preferred_text not in used:
        return preferred_text
    semvers: list[tuple[int, int, int]] = []
    for label in labels:
        matched = re.fullmatch(r"[vV]?(\d+)\.(\d+)\.(\d+)", label)
        if not matched:
            continue
        semvers.append((int(matched.group(1)), int(matched.group(2)), int(matched.group(3))))
    if not semvers:
        return "v1.0.0"
    major, minor, patch = sorted(semvers, reverse=True)[0]
    return f"v{major}.{minor}.{patch + 1}"


def _workspace_release_labels(workspace: Path) -> list[str]:
    _, _, rows = _parse_git_release_rows(workspace, limit=160)
    labels: list[str] = []
    for row in rows:
        version_label = str(row.get("version_label") or "").strip()
        if not version_label:
            continue
        labels.append(version_label)
    return labels


def _build_release_review_prompt(
    *,
    agent: dict[str, Any],
    workspace_path: Path,
    target_version: str,
    current_workspace_ref: str,
    released_versions: list[str],
) -> str:
    agents_md_path = workspace_path / "AGENTS.md"
    return "\n".join(
        [
            "你是“角色发布评审助手”。请在指定 agent 工作区内生成结构化发布评审报告，只输出 JSON。",
            "",
            f"prompt_version: {RELEASE_REVIEW_PROMPT_VERSION}",
            "",
            "输入上下文:",
            f"- agent_id: {str(agent.get('agent_id') or '').strip()}",
            f"- agent_name: {str(agent.get('agent_name') or '').strip()}",
            f"- workspace_path: {workspace_path.as_posix()}",
            f"- agents_md_path: {agents_md_path.as_posix()}",
            f"- target_version: {target_version or '-'}",
            f"- current_workspace_ref: {current_workspace_ref or '-'}",
            f"- current_registry_version: {str(agent.get('current_version') or '').strip() or '-'}",
            f"- latest_release_version: {str(agent.get('latest_release_version') or '').strip() or '-'}",
            f"- bound_release_version: {str(agent.get('bound_release_version') or '').strip() or '-'}",
            f"- released_versions: {', '.join(released_versions[:20]) or '(none)'}",
            "",
            "任务:",
            "1) 这是一份“角色发布评审报告”，不是纯仓库卫生巡检单。你的主目标是回答：",
            "   - 当前角色完整能做什么；",
            "   - 相对上一正式发布版本变了什么；",
            "   - 当前是否适合确认发布。",
            "2) 这是一次性发布评审任务，不是常规对话，也不是工作区状态维护任务。",
            "   - 不要执行会话恢复、状态快照维护、偏好写回、复盘归档、训练计划、方法编排、技能编排等与发布评审无关的流程。",
            "   - 不要读取 `workspace_state/`、`user_profile/`、`logs/`、`runs/`、`incidents/`、`metrics/` 等目录来做会话恢复或工作流维护。",
            "   - 不要读取本地 skill 的 `SKILL.md` 正文来展开技能工作流；如需识别技能，只允许根据 `.codex/skills/` 目录名枚举技能名称。",
            "   - 不要输出过程说明、计划、进度播报、todo、推理文字；只允许在任务结束时输出最终 JSON。",
            "3) 阅读 AGENTS.md、当前工作区 Git 信息、最近已发布版本，评估当前预发布内容是否适合确认发布。",
            "   - 生成 first_person_summary / full_capability_inventory / knowledge_scope / agent_skills / applicable_scenarios 时，优先结合 AGENTS.md、当前角色画像字段、本地 skills、工作区说明文档与版本上下文补齐。",
            "   - 优先只读取：AGENTS.md、README.md、CHANGELOG.md（若存在）、最近 release note、git status、git log 最近 20 条、git tag 最近 20 条。",
            "   - 不要递归扫描大型目录；不要遍历 .git 全量历史、node_modules、dist、build、coverage、.venv、site-packages、logs 等大目录。",
            "   - Git 风险判断默认只限当前目标工作区路径范围；工作区外或兄弟目录的脏文件只能作为 warnings，不能主导 release_recommendation。",
            "   - README / CHANGELOG / release note 缺失默认写入 warnings，除非输入上下文明确声明其为硬门禁，不要仅因这些缺失直接 reject。",
            "4) 报告要同时服务两个用途：",
            "   - 用途 A：作为发布评审页的“功能差异报告”，重点说明相对上一正式发布版本的变化、风险与证据。",
            "   - 用途 B：作为正式发布成功后可绑定到角色详情页的“第一人称角色述职介绍”，用于说明当前正式发布版本完整能做什么。",
            "5) 输出一份结构化发布报告，必须覆盖：",
            "   - target_version",
            "   - current_workspace_ref",
            "   - previous_release_version",
            "   - first_person_summary",
            "   - full_capability_inventory",
            "   - knowledge_scope",
            "   - agent_skills",
            "   - applicable_scenarios",
            "   - change_summary",
            "   - capability_delta",
            "   - risk_list",
            "   - validation_evidence",
            "   - release_recommendation",
            "   - next_action_suggestion",
            "6) full_capability_inventory / agent_skills / applicable_scenarios / capability_delta / risk_list / validation_evidence 必须是字符串数组。",
            "7) release_recommendation 只允许输出：approve / reject / needs_more_validation 之一。不要输出人工审核决策枚举。",
            "8) 将这份报告理解为该 agent 面向发布评审环节提交的“述职报告”，自然语言字段统一使用第一人称视角描述。",
            "   - 例如：“我当前补充了… / 我识别到… / 我已完成… / 我建议下一步…”。",
            "   - 适用字段包括：first_person_summary、change_summary、capability_delta[]、risk_list[]、validation_evidence[]、next_action_suggestion、warnings[]。",
            "   - 人工审核结论不在本 JSON 中表达，因此这里不需要输出 reviewer 视角内容。",
            "9) full_capability_inventory 必须描述“当前目标版本完整能做什么”，不能只写 capability_delta。",
            "10) capability_delta 必须明确说明“相对上一正式发布版本”的变化；若上一正式发布版本不存在，则按“首发基线评审”处理：previous_release_version 允许为空，但仍必须输出完整第一人称全量能力报告，并在 warnings[] 里写明当前是首发基线。",
            "11) 若输入上下文中的版本元数据自相矛盾，请在 warnings[] 和 next_action_suggestion 中明确指出元数据冲突，不要把它伪装成 agent 能力风险。",
            "12) 若信息不足，不要编造；在 warnings[] 里明确指出。",
            "13) target_version 必须直接复制输入上下文中的 target_version；current_workspace_ref 必须直接复制输入上下文中的 current_workspace_ref。",
            "14) 即使信息不足，也不要省略字段；必须保留完整 JSON 结构，并在 warnings[] / next_action_suggestion 里说明不足。",
            "",
            "输出要求:",
            "- 仅输出一个 JSON 对象。",
            "- 不要输出 Markdown，不要输出代码块，不要输出额外解释文字。",
            "- 任何字段都不要改名。",
            "- 字段至少包含：",
            "{",
            '  "target_version": "",',
            '  "current_workspace_ref": "",',
            '  "previous_release_version": "",',
            '  "first_person_summary": "",',
            '  "full_capability_inventory": ["..."],',
            '  "knowledge_scope": "",',
            '  "agent_skills": ["..."],',
            '  "applicable_scenarios": ["..."],',
            '  "change_summary": "",',
            '  "capability_delta": ["..."],',
            '  "risk_list": ["..."],',
            '  "validation_evidence": ["..."],',
            '  "release_recommendation": "approve|reject|needs_more_validation",',
            '  "next_action_suggestion": "",',
            '  "warnings": []',
            "}",
        ]
    )


def _build_release_review_fallback_prompt(
    *,
    review: dict[str, Any],
    publish_version: str,
    publish_error: str,
    execution_logs: list[dict[str, Any]],
) -> str:
    payload = json.dumps(
        {
            "review_id": review.get("review_id"),
            "agent_id": review.get("agent_id"),
            "target_version": review.get("target_version"),
            "publish_version": publish_version,
            "publish_error": publish_error,
            "execution_logs": execution_logs,
            "report": review.get("report") if isinstance(review.get("report"), dict) else {},
        },
        ensure_ascii=False,
        indent=2,
    )
    return "\n".join(
        [
            "你是“角色发布失败兜底助手”。请先分析失败原因，再尽量在当前 agent 工作区内执行可落地修复，然后给出一次自动重试所需的结构化结果，只输出 JSON。",
            "",
            f"prompt_version: {RELEASE_REVIEW_FALLBACK_PROMPT_VERSION}",
            "",
            "输入上下文(JSON):",
            payload,
            "",
            "任务:",
            "1) 分析本次 Git 发布 / release note / 校验失败原因。",
            "2) 若问题位于当前 agent 工作区内且你能在当前权限内修复，请直接执行修复动作；若属于环境/系统依赖问题且当前权限无法修复，请明确说明无法自动修复。",
            "3) 给出并执行一次自动重试前需要补充的 release note 建议（如无需修改可留空）。",
            "4) 输出已执行的修复动作、自动重试建议与下一步人工建议。",
            "",
            "输出要求:",
            "{",
            '  "failure_reason": "",',
            '  "repair_summary": "",',
            '  "repair_actions": ["..."],',
            '  "retry_target_version": "",',
            '  "retry_release_notes": "",',
            '  "next_action_suggestion": "",',
            '  "warnings": []',
            "}",
        ]
    )


def _run_codex_exec_for_release_review(
    *,
    root: Path,
    workspace_root: Path,
    trace_dir: Path,
    prompt_text: str,
) -> dict[str, Any]:
    prompt_path = trace_dir / "prompt.txt"
    stdout_path = trace_dir / "stdout.txt"
    stderr_path = trace_dir / "stderr.txt"
    raw_result_path = trace_dir / "codex-result.raw.json"
    parsed_result_path = trace_dir / "parsed-result.json"
    _write_release_review_text(prompt_path, prompt_text)

    command_summary = "codex exec --json --skip-git-repo-check --sandbox workspace-write --add-dir <workspace_root> -C <workspace_root> -"
    codex_bin = resolve_codex_command()
    stdout_text = ""
    stderr_text = ""
    codex_exit_code = None
    error_text = ""
    codex_events: list[dict[str, Any]] = []
    parsed_result: dict[str, Any] = {}
    monitor_info: dict[str, Any] = {}
    started_ms = int(time.time() * 1000)
    finished_ms = started_ms
    if not codex_bin:
        error_text = "codex_command_not_found"
    else:
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
                event_type = str(event.get("type") or "").strip().lower()
                if event_type == "turn.completed":
                    completion_state["ready"] = True
                    return
                msg_text = _release_review_extract_codex_event_text(event)
                if not msg_text:
                    return
                structured = _release_review_structured_result_candidates(
                    _release_review_extract_json_objects(msg_text)
                )
                if structured:
                    completion_state["ready"] = True

            result = run_monitored_subprocess(
                command=command,
                cwd=workspace_root,
                stdin_text=prompt_text,
                on_stdout_line=_observe_stdout,
                completion_checker=lambda: bool(completion_state["ready"]),
            )
            stdout_text = result.stdout_text
            stderr_text = result.stderr_text
            codex_exit_code = result.exit_code
            monitor_info = dict(result.monitor or {})
            started_ms = int(result.started_at_ms or started_ms)
            finished_ms = int(result.finished_at_ms or finished_ms)
            if codex_exit_code != 0:
                error_text = f"codex_exec_failed_exit_{codex_exit_code}"
        except Exception as exc:
            error_text = f"codex_exec_exception:{exc}"

    _write_release_review_text(stdout_path, stdout_text)
    _write_release_review_text(stderr_path, stderr_text)

    message_texts: list[str] = []
    event_errors: list[str] = []
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
            msg = _release_review_extract_codex_event_text(event)
            if msg:
                message_texts.append(msg)
            err_text = str(event.get("message") or "").strip()
            if err_text and str(event.get("type") or "").strip().lower() == "error":
                event_errors.append(err_text)
            failed_error = event.get("error")
            if isinstance(failed_error, dict):
                failed_message = str(failed_error.get("message") or "").strip()
                if failed_message:
                    event_errors.append(failed_message)

    stream_disconnected = any(
        "stream disconnected before completion" in str(item or "").strip().lower()
        or "stream closed before response.completed" in str(item or "").strip().lower()
        for item in event_errors
    )
    if stream_disconnected:
        error_text = "codex_stream_disconnected"

    message_candidates: list[dict[str, Any]] = []
    for text in message_texts:
        message_candidates.extend(_release_review_extract_json_objects(text))
    stdout_candidates = _release_review_extract_json_objects(stdout_text)
    structured_candidates = _release_review_structured_result_candidates(message_candidates)
    if not structured_candidates:
        structured_candidates = _release_review_structured_result_candidates(stdout_candidates)
    if structured_candidates:
        parsed_result = _release_review_best_payload(structured_candidates[-1]) or structured_candidates[-1]
    elif message_candidates:
        parsed_result = _release_review_best_payload(message_candidates[-1]) or message_candidates[-1]
    else:
        parsed_result = _release_review_best_payload(message_texts + stdout_candidates + [stdout_text])

    raw_payload = {
        "command_summary": command_summary,
        "exit_code": codex_exit_code,
        "error": error_text,
        "event_count": len(codex_events),
        "events": codex_events,
    }
    _write_release_review_json(raw_result_path, raw_payload)
    _write_release_review_json(parsed_result_path, parsed_result if parsed_result else {})

    analysis_chain = {
        "trace_dir": _path_for_ui(root, trace_dir),
        "prompt_path": _path_for_ui(root, prompt_path),
        "stdout_path": _path_for_ui(root, stdout_path),
        "stderr_path": _path_for_ui(root, stderr_path),
        "report_path": _path_for_ui(root, parsed_result_path),
        "raw_result_path": _path_for_ui(root, raw_result_path),
        "prompt_text": prompt_text,
        "stdout_preview": _short_text(stdout_text, 2000),
        "stderr_preview": _short_text(stderr_text, 1600),
        "command_summary": command_summary,
        "codex_summary": {
            "exit_code": codex_exit_code,
            "event_count": len(codex_events),
            "duration_ms": max(0, finished_ms - started_ms),
            "monitor": monitor_info,
        },
    }
    return {
        "ok": not error_text and bool(parsed_result),
        "error": error_text or ("codex_result_missing" if not parsed_result else ""),
        "analysis_chain": analysis_chain,
        "parsed_result": parsed_result,
    }


def _normalize_release_review_report(
    raw_result: dict[str, Any],
    *,
    agent: dict[str, Any] | None = None,
    target_version: str,
    current_workspace_ref: str,
    codex_error: str = "",
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    raw = raw_result if isinstance(raw_result, dict) else {}
    source = _release_review_best_payload(raw) if raw else {}
    if not source and raw:
        source = raw
    agent_payload = agent if isinstance(agent, dict) else {}
    context = _release_review_agent_context(agent_payload) if agent_payload else {}
    warnings = _normalize_text_list(source.get("warnings") if isinstance(source, dict) else [], limit=180)
    if raw and source is not raw:
        warnings.append("已自动从嵌套输出中提取结构化发布报告。")
    if str(codex_error or "").strip().lower() == "codex_result_missing":
        warnings.append("Codex 未直接返回标准结构化 JSON，系统已根据上下文自动补齐报告字段。")

    full_capability_inventory = _normalize_text_list(
        source.get("full_capability_inventory")
        if isinstance(source, dict) and "full_capability_inventory" in source
        else (
            source.get("capability_inventory")
            if isinstance(source, dict)
            else []
        ),
        limit=220,
    )
    if not full_capability_inventory:
        full_capability_inventory = _ensure_first_person_list(
            context.get("full_capability_inventory"),
            "我当前可以：",
            limit=12,
            item_limit=220,
        )
        if full_capability_inventory:
            warnings.append("全量能力清单缺失，系统已根据 AGENTS.md 与工作区上下文自动补齐。")

    knowledge_scope = _short_text(
        _release_review_pick_text(source, "knowledge_scope", "knowledge", "scope")
        or str(context.get("knowledge_scope") or "").strip(),
        320,
    )
    if knowledge_scope and not _release_review_pick_text(source, "knowledge_scope", "knowledge", "scope"):
        warnings.append("知识范围缺失，系统已根据 AGENTS.md 自动补齐。")

    agent_skills = _normalize_text_list(
        source.get("agent_skills")
        if isinstance(source, dict) and "agent_skills" in source
        else (source.get("skills") if isinstance(source, dict) else []),
        limit=80,
    )
    if not agent_skills:
        agent_skills = _skills_list(context.get("agent_skills"))
        if agent_skills:
            warnings.append("Agent Skills 缺失，系统已根据工作区本地技能自动补齐。")

    applicable_scenarios = _normalize_text_list(
        source.get("applicable_scenarios")
        if isinstance(source, dict) and "applicable_scenarios" in source
        else (source.get("scenarios") if isinstance(source, dict) else []),
        limit=140,
    )
    if not applicable_scenarios:
        applicable_scenarios = _text_items(context.get("applicable_scenarios"), limit=6, item_limit=140)
        if applicable_scenarios:
            warnings.append("适用场景缺失，系统已根据 AGENTS.md 自动补齐。")

    first_person_summary = _ensure_first_person_text(
        _release_review_pick_text(
            source,
            "first_person_summary",
            "self_summary",
            "role_summary",
            "capability_summary",
            "summary",
        )
        or str(context.get("first_person_summary") or "").strip(),
        "我当前的核心能力是：",
        limit=320,
    )
    if not _release_review_pick_text(source, "first_person_summary", "self_summary", "role_summary", "capability_summary"):
        warnings.append("第一人称角色摘要缺失，系统已根据 AGENTS.md 自动补齐。")

    capability_delta = _normalize_text_list(
        source.get("capability_delta")
        if isinstance(source, dict) and "capability_delta" in source
        else (source.get("capability_changes") if isinstance(source, dict) else []),
        limit=280,
    )
    previous_release_version = _short_text(
        _release_review_pick_text(source, "previous_release_version", "latest_release_version", "base_release_version")
        or str(context.get("previous_release_version") or "").strip(),
        80,
    )
    if not previous_release_version:
        warnings.append("当前未找到上一正式发布版本，本次按首发基线评审处理。")
    if not capability_delta and not previous_release_version and full_capability_inventory:
        capability_delta = [f"我本次首发基线已包含：{item}" for item in full_capability_inventory[:3]]
    capability_delta = _ensure_first_person_list(
        capability_delta,
        "我本次主要补充了：",
        limit=8,
        item_limit=220,
    )
    risk_filter = _release_review_filter_risks(
        source.get("risk_list")
        if isinstance(source, dict) and "risk_list" in source
        else (source.get("risks") if isinstance(source, dict) else []),
    )
    risk_list = risk_filter["risk_list"]
    warnings.extend(risk_filter["warnings"])
    validation_evidence = _normalize_text_list(
        source.get("validation_evidence")
        if isinstance(source, dict) and "validation_evidence" in source
        else (source.get("evidence") if isinstance(source, dict) else []),
        limit=320,
    )
    validation_evidence = _ensure_first_person_list(validation_evidence, "我当前已确认的验证证据是：", limit=8, item_limit=240)

    change_summary = _ensure_first_person_text(
        _release_review_pick_text(source, "change_summary", "summary", "change_overview", "release_summary"),
        "我本次版本的主要变化是：",
        limit=1000,
    )
    if not change_summary:
        if capability_delta:
            change_summary = _short_text("我本次预发布的主要变化是：" + "；".join(capability_delta[:3]), 1000)
            warnings.append("变更摘要由 capability_delta 自动汇总生成。")
        elif risk_list:
            change_summary = _short_text("我当前仍识别到待确认风险：" + "；".join(risk_list[:2]), 1000)
            warnings.append("变更摘要由 risk_list 自动汇总生成。")
        elif validation_evidence:
            change_summary = _short_text("我当前已收集的验证证据包括：" + "；".join(validation_evidence[:2]), 1000)
            warnings.append("变更摘要由 validation_evidence 自动汇总生成。")
        else:
            change_summary = "我暂未能从 Codex 输出中提取结构化变更摘要，请人工查看分析链路中的 stdout / 报告文件。"
            warnings.append("未提取到结构化变更摘要，已填入人工复核提示。")

    recommendation = _release_review_normalize_recommendation(
        _release_review_pick_text(source, "release_recommendation", "recommendation", "decision", "review_decision")
    )
    if not recommendation:
        recommendation = "needs_more_validation"
        warnings.append("未提取到有效发布建议，系统已默认保守建议为 needs_more_validation。")
    if risk_filter["metadata_conflicts"]:
        if recommendation == "approve":
            recommendation = "needs_more_validation"
            warnings.append("检测到版本元数据冲突，本次发布建议已自动降级为 needs_more_validation。")
    elif risk_filter["demoted_count"] and not risk_list and recommendation == "reject":
        recommendation = "needs_more_validation"
        warnings.append("仅识别到可追溯性或工作区外告警，系统已将发布建议从 reject 降级为 needs_more_validation。")

    has_structured_content = bool(full_capability_inventory or capability_delta or risk_list or validation_evidence or raw)
    next_action_suggestion = _ensure_first_person_text(
        _release_review_pick_text(source, "next_action_suggestion", "next_action", "suggestion", "recommended_action")
        or _release_review_default_next_action(recommendation, has_structured_content=has_structured_content),
        "我建议下一步：",
        limit=320,
    )
    if not _release_review_pick_text(source, "next_action_suggestion", "next_action", "suggestion", "recommended_action"):
        warnings.append("未提取到下一步建议，系统已自动补齐。")

    report = {
        "target_version": _short_text(
            _release_review_pick_text(source, "target_version", "version", "proposed_version") or target_version,
            80,
        ),
        "current_workspace_ref": _short_text(
            _release_review_pick_text(source, "current_workspace_ref", "workspace_ref", "current_ref", "current_version")
            or current_workspace_ref,
            80,
        ),
        "previous_release_version": previous_release_version,
        "first_person_summary": first_person_summary,
        "what_i_can_do": _derive_what_i_can_do(first_person_summary, full_capability_inventory),
        "full_capability_inventory": full_capability_inventory,
        "knowledge_scope": knowledge_scope,
        "agent_skills": _skills_list(agent_skills),
        "applicable_scenarios": applicable_scenarios,
        "change_summary": change_summary,
        "capability_delta": capability_delta,
        "risk_list": risk_list,
        "validation_evidence": validation_evidence,
        "release_recommendation": _short_text(recommendation, 80),
        "version_notes": _short_text(change_summary, 320),
        "next_action_suggestion": next_action_suggestion,
        "warnings": [
            item
            for item in dict.fromkeys(
                [
                    _release_review_warning_text(item, limit=220)
                    for item in warnings
                    if str(item or "").strip()
                ]
            )
            if item
        ],
        "raw_result": raw,
    }
    missing = _release_review_missing_fields(report, RELEASE_REVIEW_REQUIRED_FIELDS)
    if missing and not allow_incomplete:
        raise TrainingCenterError(
            500,
            "release review report incomplete",
            "release_review_report_incomplete",
            {"missing_fields": missing},
        )
    return report


def _build_release_review_failure_report(
    raw_result: dict[str, Any],
    *,
    agent: dict[str, Any] | None = None,
    target_version: str,
    current_workspace_ref: str,
    codex_error: str = "",
    error_code: str = "",
    error_message: str = "",
    missing_fields: list[str] | None = None,
    metadata_conflicts: list[str] | None = None,
) -> dict[str, Any]:
    report = _normalize_release_review_report(
        raw_result,
        agent=agent,
        target_version=target_version,
        current_workspace_ref=current_workspace_ref,
        codex_error=codex_error,
        allow_incomplete=True,
    )
    warning_items = _normalize_text_list(report.get("warnings"), limit=220)
    missing = [str(item or "").strip() for item in (missing_fields or []) if str(item or "").strip()]
    conflicts = [str(item or "").strip() for item in (metadata_conflicts or []) if str(item or "").strip()]
    code = str(error_code or "").strip().lower()

    if conflicts:
        warning_items.extend([_release_review_warning_text("版本元数据冲突：" + item) for item in conflicts])
    if missing:
        warning_items.append(_release_review_warning_text("结构化报告仍缺少关键字段：" + " / ".join(missing)))
    if error_message:
        warning_items.append(_release_review_warning_text(error_message))

    report["target_version"] = _short_text(str(report.get("target_version") or "").strip() or target_version, 80)
    report["current_workspace_ref"] = _short_text(
        str(report.get("current_workspace_ref") or "").strip() or current_workspace_ref,
        80,
    )
    if not _release_review_field_present(report.get("change_summary")):
        if code == "release_review_metadata_conflict":
            report["change_summary"] = "我在进入发布评审前识别到版本元数据存在冲突，因此本次未继续执行正常发布报告生成。"
        elif missing:
            report["change_summary"] = "我已从当前链路中提取到部分结构化内容，但关键字段仍不完整。"
        else:
            report["change_summary"] = "我本次未能成功产出完整结构化发布报告，当前已保留失败排查所需的骨架信息。"
    if not _release_review_field_present(report.get("release_recommendation")):
        report["release_recommendation"] = "needs_more_validation"
    if not _release_review_field_present(report.get("next_action_suggestion")):
        if code == "release_review_metadata_conflict":
            report["next_action_suggestion"] = "我建议先修复 target_version / latest_release_version / released_versions 等版本元数据冲突，再重新进入发布评审。"
        elif missing:
            report["next_action_suggestion"] = "我建议先检查报告文件与 stdout，补齐缺失字段后再重新进入发布评审。"
        else:
            report["next_action_suggestion"] = "我建议先查看分析链路中的 stdout / stderr / 报告文件，定位失败原因后再重新进入发布评审。"
    if not isinstance(raw_result, dict):
        report["raw_result"] = {"raw_text": _short_text(str(raw_result or "").strip(), 4000)}
    else:
        report["raw_result"] = raw_result
    report["warnings"] = [
        item
        for item in dict.fromkeys(
            [
                _release_review_warning_text(item, limit=220)
                for item in warning_items
                if str(item or "").strip()
            ]
        )
        if item
    ]
    return report


def _describe_release_review_report_failure(
    exc: TrainingCenterError,
    *,
    codex_result: dict[str, Any] | None = None,
) -> str:
    code = str(getattr(exc, "code", "") or "").strip().lower()
    extra = getattr(exc, "extra", {}) if isinstance(getattr(exc, "extra", {}), dict) else {}
    codex_payload = codex_result if isinstance(codex_result, dict) else {}
    codex_error = str(codex_payload.get("error") or extra.get("reason") or "").strip().lower()

    if code == "release_review_report_incomplete":
        missing = [
            str(item or "").strip()
            for item in (extra.get("missing_fields") or [])
            if str(item or "").strip()
        ]
        if missing:
            return "结构化发布报告缺少关键字段（" + " / ".join(missing) + "）。请先检查分析链路中的报告文件与 stdout 输出，修正后点击“重新进入发布评审”。"
        return "结构化发布报告字段不完整。请先检查分析链路中的报告文件与 stdout 输出，修正后点击“重新进入发布评审”。"

    if code == "release_review_metadata_conflict":
        conflicts = [
            str(item or "").strip()
            for item in (extra.get("metadata_conflicts") or [])
            if str(item or "").strip()
        ]
        if conflicts:
            return "进入发布评审前检测到版本元数据冲突（" + " / ".join(conflicts[:3]) + "）。请先修复版本元数据后再重新进入发布评审。"
        return "进入发布评审前检测到版本元数据冲突。请先修复 target_version / latest_release_version / released_versions 等元数据后再重新进入发布评审。"

    if code == "release_review_report_failed":
        if codex_error == "codex_command_not_found":
            return "生成发布报告失败：当前环境未找到 codex 命令。请先确认服务端已安装并可执行 codex，然后点击“重新进入发布评审”。"
        if codex_error == "codex_exec_timeout":
            return "生成发布报告失败：Codex 执行超时。请先查看分析链路中的 stdout / stderr / trace 目录定位卡点，必要时缩小本次改动范围后重试。"
        if codex_error == "codex_stream_disconnected":
            return "生成发布报告失败：Codex 在流式返回过程中断线，任务未完成。请先检查目标工作区是否触发了冗长的会话恢复/技能编排链路，再重新进入发布评审。"
        if codex_error.startswith("codex_exec_failed_exit_"):
            exit_code = codex_error.rsplit("_", 1)[-1]
            return f"生成发布报告失败：Codex 执行异常退出（exit={exit_code}）。请先查看分析链路中的 stderr / stdout，修复工作区或提示词问题后重新进入发布评审。"
        if codex_error.startswith("codex_exec_exception:"):
            detail = str(codex_payload.get("error") or extra.get("reason") or "").strip()
            return "生成发布报告失败：调用 Codex 时发生异常" + (f"（{detail}）" if detail else "") + "。请先检查服务端日志与分析链路，再重新进入发布评审。"
        if codex_error == "codex_result_missing":
            return "生成发布报告失败：Codex 已执行，但没有产出可解析的结构化 JSON 报告。请先检查 stdout / 报告文件是否混入额外文本，修正后重新进入发布评审。"
        if codex_error:
            return "生成发布报告失败：" + codex_error + "。请先查看分析链路中的 stdout / stderr / 报告文件，定位原因后重新进入发布评审。"
        return "生成发布报告失败。请先查看分析链路中的 stdout / stderr / 报告文件，定位具体原因后点击“重新进入发布评审”。"

    return str(exc)


def _append_release_review_log(
    logs: list[dict[str, Any]],
    *,
    phase: str,
    status: str,
    message: str,
    path: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    logs.append(
        {
            "phase": str(phase or "").strip() or "unknown",
            "status": str(status or "").strip() or "pending",
            "message": _short_text(str(message or "").strip(), 400),
            "path": str(path or "").strip(),
            "details": details if isinstance(details, dict) else {},
            "ts": iso_ts(now_local()),
        }
    )


def _run_git_mutation(
    workspace: Path,
    args: list[str],
    *,
    timeout_s: int = 30,
) -> tuple[bool, str, str]:
    cmd = ["git", "-C", workspace.as_posix()] + [str(arg) for arg in args]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_s,
        )
    except Exception as exc:
        return False, "", str(exc or "")
    return proc.returncode == 0, str(proc.stdout or ""), str(proc.stderr or "")


def _git_publish_identity_defaults(agent: dict[str, Any]) -> tuple[str, str]:
    token = safe_token(
        str(agent.get("agent_id") or agent.get("agent_name") or "workflow-release"),
        "workflow-release",
        80,
    )
    name = str(agent.get("agent_name") or token or "workflow-release").strip() or "workflow-release"
    email = f"{token or 'workflow-release'}@workflow.local"
    return _short_text(name, 120), _short_text(email, 160)


def _workspace_has_own_git_repo(workspace: Path) -> tuple[bool, str]:
    ok_root, root_out, _ = _run_git_readonly_verbose(
        workspace,
        ["rev-parse", "--show-toplevel"],
        timeout_s=12,
    )
    if not ok_root:
        return False, ""
    root_line = ""
    for line in str(root_out or "").splitlines():
        candidate = str(line or "").strip()
        if candidate:
            root_line = candidate
    if not root_line:
        return False, ""
    repo_root = Path(root_line).resolve(strict=False)
    workspace_root = workspace.resolve(strict=False)
    same_root = os.path.normcase(str(repo_root)) == os.path.normcase(str(workspace_root))
    return same_root, repo_root.as_posix()
