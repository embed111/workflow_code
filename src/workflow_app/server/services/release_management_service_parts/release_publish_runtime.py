

from workflow_app.server.services.codex_failure_contract import build_codex_failure, build_retry_action


def _ensure_workspace_git_ready_for_publish(
    cfg: AppConfig,
    *,
    workspace: Path,
    agent: dict[str, Any],
    execution_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    has_own_repo, detected_repo_root = _workspace_has_own_git_repo(workspace)
    repo_initialized = False
    if not has_own_repo:
        ok_init, init_out, init_err = _run_git_mutation(workspace, ["init"], timeout_s=30)
        if not ok_init:
            _append_release_review_log(
                execution_logs,
                phase="prepare",
                status="failed",
                message="自动初始化 Git 仓库失败",
                details={"stdout": _short_text(init_out, 300), "stderr": _short_text(init_err, 400)},
            )
            return {"ok": False, "error": "git_init_failed", "stdout": init_out, "stderr": init_err}
        repo_initialized = True
        _append_release_review_log(
            execution_logs,
            phase="prepare",
            status="done",
            message="当前 agent 工作区未绑定独立 Git 仓库，已自动执行 git init",
            details={
                "stdout": _short_text(init_out, 240),
                "detected_repo_root": detected_repo_root,
            },
        )

    if repo_initialized:
        desired_name, desired_email = _git_publish_identity_defaults(agent)
        ok_name, name_out, _ = _run_git_mutation(workspace, ["config", "--get", "user.name"], timeout_s=12)
        ok_email, email_out, _ = _run_git_mutation(workspace, ["config", "--get", "user.email"], timeout_s=12)
        current_name = str(name_out or "").strip() if ok_name else ""
        current_email = str(email_out or "").strip() if ok_email else ""
        configured_fields: list[str] = []
        if not current_name:
            set_name_ok, _, set_name_err = _run_git_mutation(
                workspace,
                ["config", "--local", "user.name", desired_name],
                timeout_s=12,
            )
            if not set_name_ok:
                _append_release_review_log(
                    execution_logs,
                    phase="prepare",
                    status="failed",
                    message="自动写入 Git 用户名失败",
                    details={"stderr": _short_text(set_name_err, 400)},
                )
                return {"ok": False, "error": "git_identity_config_failed", "stderr": set_name_err}
            configured_fields.append("user.name")
        if not current_email:
            set_email_ok, _, set_email_err = _run_git_mutation(
                workspace,
                ["config", "--local", "user.email", desired_email],
                timeout_s=12,
            )
            if not set_email_ok:
                _append_release_review_log(
                    execution_logs,
                    phase="prepare",
                    status="failed",
                    message="自动写入 Git 邮箱失败",
                    details={"stderr": _short_text(set_email_err, 400)},
                )
                return {"ok": False, "error": "git_identity_config_failed", "stderr": set_email_err}
            configured_fields.append("user.email")
        if configured_fields:
            _append_release_review_log(
                execution_logs,
                phase="prepare",
                status="done",
                message="已为自动初始化的 Git 仓库补齐本地提交身份",
                details={"configured_fields": configured_fields, "user_name": desired_name, "user_email": desired_email},
            )

    status_ok, _, status_err = _run_git_readonly_verbose(
        workspace,
        ["status", "--porcelain", "--untracked-files=normal"],
        timeout_s=12,
    )
    if not status_ok:
        _append_release_review_log(
            execution_logs,
            phase="prepare",
            status="failed",
            message="Git 仓库已就绪，但读取状态失败",
            details={"stderr": _short_text(status_err, 400)},
        )
        return {"ok": False, "error": "git_status_failed", "stderr": status_err}

    return {"ok": True, "repo_initialized": repo_initialized}


def _build_publish_release_note(
    *,
    agent: dict[str, Any],
    report: dict[str, Any],
    publish_version: str,
    review_comment: str,
) -> str:
    def note_first_person(value: Any, prefix: str, *, limit: int = 280) -> str:
        text = _short_text(str(value or "").strip(), limit)
        if not text:
            return ""
        if text.startswith(("我", "当前工作区", "本次发布", "本次版本")):
            return text
        return prefix + text

    workspace = Path(str(agent.get("workspace_path") or "")).resolve(strict=False)
    portrait = extract_agent_role_portrait(workspace / "AGENTS.md")
    skills = _skills_list(portrait.get("skills"))
    if not skills:
        skills = _skills_list(agent.get("skills_json"))
    if not skills:
        skills = _skills_list(agent.get("skills"))
    list_workspace_local_skills = globals().get("_list_workspace_local_skills")
    if not skills and callable(list_workspace_local_skills):
        try:
            skills = _skills_list(list_workspace_local_skills(workspace))
        except Exception:
            skills = []
    if not skills:
        skills = ["workflow"]
    capability_summary = str(
        report.get("first_person_summary")
        or portrait.get("capability_summary")
        or agent.get("capability_summary")
        or report.get("change_summary")
        or "见本次发布评审报告"
    ).strip()
    knowledge_scope = str(
        report.get("knowledge_scope")
        or portrait.get("knowledge_scope")
        or agent.get("knowledge_scope")
        or report.get("next_action_suggestion")
        or "参考当前角色知识范围"
    ).strip()
    applicable_scenarios = "；".join(_normalize_text_list(report.get("applicable_scenarios"), limit=120)) or str(
        portrait.get("applicable_scenarios")
        or agent.get("applicable_scenarios")
        or "角色发布评审与确认发布"
    ).strip()
    version_notes = str(report.get("change_summary") or review_comment or agent.get("version_notes") or publish_version).strip()
    what_i_can_do = _normalize_text_list(report.get("what_i_can_do"), limit=180)
    full_capability_inventory = _normalize_text_list(report.get("full_capability_inventory"), limit=180)
    capability_delta = _normalize_text_list(report.get("capability_delta"), limit=180)
    risk_list = _normalize_text_list(report.get("risk_list"), limit=180)
    evidence_list = _normalize_text_list(report.get("validation_evidence"), limit=220)
    lines = [
        f"发布版本: {publish_version}",
        f"第一人称摘要: {note_first_person(capability_summary, '我当前的核心能力是：')}",
        f"角色能力摘要: {note_first_person(capability_summary, '我当前的核心能力是：')}",
        f"角色知识范围: {note_first_person(knowledge_scope, '我当前覆盖的知识范围是：')}",
        "技能: " + ", ".join(skills[:12]),
        "技能明细:",
    ]
    lines.extend([f"- {item}" for item in skills[:12]])
    if what_i_can_do:
        lines.extend(["我当前能做什么:"])
        lines.extend([f"- {note_first_person(item, '我当前可以：', limit=180)}" for item in what_i_can_do[:5]])
    if full_capability_inventory:
        lines.extend(["全量能力清单:"])
        lines.extend([f"- {note_first_person(item, '我当前可以：', limit=180)}" for item in full_capability_inventory[:12]])
    lines.extend(
        [
            f"适用场景: {note_first_person(applicable_scenarios, '我当前适合用于：')}",
            f"版本说明: {note_first_person(version_notes, '我本次发布主要更新了：')}",
            "",
            "发布评审摘要:",
            f"- 工作区基线: {note_first_person(str(report.get('current_workspace_ref') or '').strip() or '-', '我当前工作区基线是：', limit=120)}",
            f"- 发布建议: {note_first_person(str(report.get('release_recommendation') or '').strip() or '-', '我当前给出的发布建议是：', limit=120)}",
        ]
    )
    if capability_delta:
        lines.append("- 能力变化: 我本次主要补充/调整了：" + "；".join(capability_delta[:5]))
    if risk_list:
        lines.append("- 风险提示: 我当前识别到的风险包括：" + "；".join(risk_list[:5]))
    if evidence_list:
        lines.append("- 验证证据: 我当前已确认的验证证据包括：" + "；".join(evidence_list[:5]))
    if review_comment:
        lines.append("- 审核意见: " + note_first_person(review_comment, "我本次发布收到的审核意见是：", limit=220))
    next_action = str(report.get("next_action_suggestion") or "").strip()
    if next_action:
        lines.append("- 下一步建议: " + note_first_person(next_action, "我建议下一步：", limit=220))
    return "\n".join(lines).strip() + "\n"


def _bind_release_profile_after_publish(
    cfg: AppConfig,
    *,
    agent_id: str,
    publish_version: str,
    review_id: str,
    analysis_chain: dict[str, Any],
    public_profile_markdown_path: str,
    capability_snapshot_json_path: str,
) -> None:
    source_agent_id = safe_token(str(agent_id or ""), "", 120)
    if not source_agent_id:
        return
    release_row: dict[str, Any] | None = None
    conn = connect_db(cfg.root)
    try:
        row = conn.execute(
            """
            SELECT release_id,version_label,released_at
            FROM agent_release_history
            WHERE agent_id=?
              AND version_label=?
              AND COALESCE(classification,'normal_commit')='release'
            ORDER BY released_at DESC, created_at DESC
            LIMIT 1
            """,
            (source_agent_id, str(publish_version or "").strip()),
        ).fetchone()
        if row is not None:
            release_row = {name: row[name] for name in row.keys()}
            conn.execute(
                """
                UPDATE agent_release_history
                SET release_source_ref=?,
                    public_profile_ref=?,
                    capability_snapshot_ref=?
                WHERE release_id=?
                """,
                (
                    str((analysis_chain or {}).get("report_path") or "").strip(),
                    str(public_profile_markdown_path or "").strip(),
                    str(capability_snapshot_json_path or "").strip(),
                    str(row["release_id"] or "").strip(),
                ),
            )
            conn.execute(
                """
                UPDATE agent_registry
                SET active_role_profile_release_id=?,
                    active_role_profile_ref=?,
                    updated_at=?
                WHERE agent_id=?
                """,
                (
                    str(row["release_id"] or "").strip(),
                    str(public_profile_markdown_path or capability_snapshot_json_path or "").strip(),
                    iso_ts(now_local()),
                    source_agent_id,
                ),
            )
            conn.commit()
    finally:
        conn.close()
    if release_row is not None:
        append_training_center_audit(
            cfg.root,
            action="release_profile_bound",
            operator="system",
            target_id=source_agent_id,
            detail={
                "review_id": review_id,
                "release_id": str(release_row.get("release_id") or "").strip(),
                "publish_version": str(publish_version or "").strip(),
                "public_profile_ref": str(public_profile_markdown_path or "").strip(),
                "capability_snapshot_ref": str(capability_snapshot_json_path or "").strip(),
            },
        )


def _verify_release_note_before_tag(
    workspace: Path,
    publish_version: str,
    release_note_text: str,
) -> tuple[bool, dict[str, Any], str]:
    parser = globals().get("parse_release_portrait_fields")
    validator = globals().get("validate_release_portrait_fields")
    skills_parser = globals().get("_skills_list")
    list_workspace_local_skills = globals().get("_list_workspace_local_skills")
    if not callable(parser) or not callable(validator):
        return True, {}, ""
    try:
        parsed = parser(str(release_note_text or ""))
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    parsed_skills = skills_parser(parsed.get("skills")) if callable(skills_parser) else []
    note_text = str(release_note_text or "")
    if (
        not parsed_skills
        and callable(list_workspace_local_skills)
        and "发布版本:" in note_text
        and "技能:" in note_text
    ):
        try:
            fallback_skills = list_workspace_local_skills(workspace)
        except Exception:
            fallback_skills = []
        parsed_skills = skills_parser(fallback_skills) if callable(skills_parser) else []
        if parsed_skills:
            parsed["skills"] = parsed_skills
    try:
        release_valid, invalid_reasons = validator(parsed)
    except Exception:
        release_valid, invalid_reasons = False, ["release_note_validate_failed"]
    reason_list = [str(item or "").strip() for item in invalid_reasons if str(item or "").strip()]
    payload = {
        "version_label": str(publish_version or "").strip(),
        "capability_summary": str(parsed.get("capability_summary") or "").strip(),
        "knowledge_scope": str(parsed.get("knowledge_scope") or "").strip(),
        "skills_json": _json_dumps_text(parsed_skills, "[]"),
        "applicable_scenarios": str(parsed.get("applicable_scenarios") or "").strip(),
        "version_notes": str(parsed.get("version_notes") or "").strip(),
        "release_valid": bool(release_valid),
        "invalid_reasons_json": _json_dumps_text(reason_list, "[]"),
        "classification": "release" if release_valid else "normal_commit",
        "raw_notes": _short_text(note_text, 4000),
    }
    if release_valid:
        return True, payload, ""
    return False, payload, ",".join(reason_list) or "release_note_invalid"


def _verify_published_release(workspace: Path, publish_version: str) -> tuple[bool, dict[str, Any], str]:
    _, _, rows = _parse_git_release_rows(workspace, limit=120)
    for row in rows:
        version_label = str(row.get("version_label") or "").strip()
        if version_label != str(publish_version or "").strip():
            continue
        if str(row.get("classification") or "normal_commit").strip().lower() != "release":
            reasons = _json_load_list(row.get("invalid_reasons_json"))
            return False, row, ",".join([str(item or "").strip() for item in reasons if str(item or "").strip()]) or "release_note_invalid"
        return True, row, ""
    return False, {}, "release_version_not_found_after_publish"


def _update_agent_after_publish(
    cfg: AppConfig,
    *,
    agent_id: str,
    publish_version: str,
    released_at: str,
) -> dict[str, Any]:
    sync_training_agent_registry(cfg)
    conn = connect_db(cfg.root)
    try:
        agent = _resolve_training_agent(conn, agent_id)
        if agent is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": agent_id})
        training_gate_state = derive_training_gate_state(
            lifecycle_state="released",
            current_version=publish_version,
            latest_release_version=publish_version,
            parent_agent_id=str(agent.get("parent_agent_id") or "").strip(),
            preferred=agent.get("training_gate_state"),
        )
        conn.execute(
            """
            UPDATE agent_registry
            SET current_version=?,
                latest_release_version=?,
                bound_release_version=?,
                lifecycle_state='released',
                training_gate_state=?,
                last_release_at=?,
                updated_at=?
            WHERE agent_id=?
            """,
            (
                publish_version,
                publish_version,
                publish_version,
                training_gate_state,
                released_at,
                iso_ts(now_local()),
                agent_id,
            ),
        )
        conn.commit()
        return _resolve_training_agent(conn, agent_id) or {}
    finally:
        conn.close()


def _insert_release_evaluation_shadow_record(
    root: Path,
    *,
    agent_id: str,
    target_version: str,
    decision: str,
    reviewer: str,
    summary: str,
) -> str:
    evaluation_id = training_release_evaluation_id()
    conn = connect_db(root)
    try:
        conn.execute(
            """
            INSERT INTO agent_release_evaluation (
                evaluation_id,agent_id,target_version,decision,reviewer,summary,created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                evaluation_id,
                agent_id,
                target_version,
                decision,
                reviewer,
                _short_text(summary, 1000),
                iso_ts(now_local()),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return evaluation_id


def _latest_release_review_row(conn: sqlite3.Connection, agent_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            review_id,agent_id,target_version,current_workspace_ref,release_review_state,prompt_version,
            analysis_chain_json,report_json,report_error,review_decision,reviewer,review_comment,reviewed_at,
            publish_version,publish_status,publish_error,execution_log_json,fallback_json,
            public_profile_markdown_path,capability_snapshot_json_path,created_at,updated_at
        FROM agent_release_review
        WHERE agent_id=?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (agent_id,),
    ).fetchone()
    if row is None:
        return None
    return {name: row[name] for name in row.keys()}


def _update_release_review_row(root: Path, review_id: str, fields: dict[str, Any]) -> None:
    payload = {str(key): value for key, value in (fields or {}).items() if str(key)}
    if not payload:
        return
    payload["updated_at"] = iso_ts(now_local())
    params: list[Any] = []
    assignments: list[str] = []
    json_defaults = {
        "analysis_chain_json": "{}",
        "report_json": "{}",
        "execution_log_json": "[]",
        "fallback_json": "{}",
    }
    for key, value in payload.items():
        assignments.append(f"{key}=?")
        if key in json_defaults:
            params.append(_json_dumps_text(value, json_defaults[key]))
        else:
            params.append(str(value or ""))
    params.append(review_id)
    conn = connect_db(root)
    try:
        conn.execute(
            f"UPDATE agent_release_review SET {', '.join(assignments)} WHERE review_id=?",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()


def _release_review_trace_refs(analysis_chain: dict[str, Any]) -> dict[str, str]:
    chain = analysis_chain if isinstance(analysis_chain, dict) else {}
    refs: dict[str, str] = {}
    for key in ("trace_dir", "prompt_path", "stdout_path", "stderr_path", "report_path", "raw_result_path"):
        value = str(chain.get(key) or "").strip()
        if value:
            refs[key] = value
    return refs


def _latest_failed_execution_log(execution_logs: list[dict[str, Any]]) -> dict[str, Any]:
    for item in reversed(list(execution_logs or [])):
        if str((item or {}).get("status") or "").strip().lower() == "failed":
            return dict(item or {})
    return {}


def _release_publish_trace_refs(
    execution_logs: list[dict[str, Any]],
    fallback: dict[str, Any],
) -> dict[str, str]:
    refs: dict[str, str] = {}
    failed_log = _latest_failed_execution_log(execution_logs)
    failed_path = str(failed_log.get("path") or "").strip()
    failed_phase = str(failed_log.get("phase") or "publish").strip()
    if failed_path:
        refs[failed_phase] = failed_path
    fallback_chain = fallback.get("analysis_chain") if isinstance(fallback.get("analysis_chain"), dict) else {}
    for key, value in _release_review_trace_refs(fallback_chain).items():
        refs[f"fallback_{key}"] = value
    retry_result = fallback.get("retry_result") if isinstance(fallback.get("retry_result"), dict) else {}
    retry_note_path = str(retry_result.get("release_note_path") or "").strip()
    if retry_note_path:
        refs["retry_release_note"] = retry_note_path
    return refs


def _release_publish_attempt_count(execution_logs: list[dict[str, Any]]) -> int:
    count = sum(
        1
        for item in list(execution_logs or [])
        if str((item or {}).get("phase") or "").strip().lower() == "prepare"
        and str((item or {}).get("status") or "").strip().lower() in {"done", "failed"}
    )
    return max(1, int(count or 0))


def _release_review_payload(agent: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    lifecycle_state = normalize_lifecycle_state(agent.get("lifecycle_state"))
    current_state = str((row or {}).get("release_review_state") or "idle").strip() or "idle"
    if current_state not in RELEASE_REVIEW_STATES:
        current_state = "idle"
    analysis_chain = _json_load_dict((row or {}).get("analysis_chain_json"))
    report = _json_load_dict((row or {}).get("report_json"))
    execution_logs = _json_load_list((row or {}).get("execution_log_json"))
    fallback = _json_load_dict((row or {}).get("fallback_json"))
    review_decision = str((row or {}).get("review_decision") or "").strip()
    publish_status = str((row or {}).get("publish_status") or "").strip()
    report_error_code = str(analysis_chain.get("report_error_code") or "").strip()
    report_missing_fields = [
        str(item or "").strip()
        for item in (analysis_chain.get("report_missing_fields") or [])
        if str(item or "").strip()
    ] if isinstance(analysis_chain.get("report_missing_fields"), list) else []
    review_id = str((row or {}).get("review_id") or "").strip()
    agent_id = str(agent.get("agent_id") or "").strip()
    report_error = str((row or {}).get("report_error") or "").strip()
    publish_error = str((row or {}).get("publish_error") or "").strip()
    report_detail_code = str(report_error_code or analysis_chain.get("error") or "").strip().lower()
    if not report_detail_code and report_error:
        report_detail_code = "release_review_report_failed"
    report_codex_failure = (
        build_codex_failure(
            feature_key="release_review",
            attempt_id=review_id or agent_id,
            attempt_count=1,
            failure_detail_code=report_detail_code,
            failure_message=report_error,
            retry_action=build_retry_action(
                "retry_release_review",
                payload={"agent_id": agent_id},
            ),
            trace_refs=_release_review_trace_refs(analysis_chain),
            failed_at=str((row or {}).get("updated_at") or "").strip(),
        )
        if report_detail_code
        else {}
    )
    publish_detail_code = publish_error.lower()
    fallback_detail_code = str(
        ((fallback.get("analysis_chain") or {}).get("error") if isinstance(fallback.get("analysis_chain"), dict) else "")
        or fallback.get("error")
        or ""
    ).strip().lower()
    if not publish_detail_code and publish_status.lower() == "failed":
        publish_detail_code = fallback_detail_code or "publish_failed"
    publish_codex_failure = (
        build_codex_failure(
            feature_key="release_publish",
            attempt_id=review_id or agent_id,
            attempt_count=_release_publish_attempt_count(execution_logs),
            failure_detail_code=publish_detail_code,
            failure_message=str(
                fallback.get("failure_reason")
                or fallback.get("next_action_suggestion")
                or publish_error
                or ""
            ).strip(),
            retry_action=build_retry_action(
                "retry_publish",
                payload={"agent_id": agent_id},
            ),
            trace_refs=_release_publish_trace_refs(execution_logs, fallback),
            failed_at=str((row or {}).get("updated_at") or "").strip(),
        )
        if publish_detail_code
        else {}
    )
    payload = {
        "review_id": review_id,
        "agent_id": agent_id,
        "agent_name": str(agent.get("agent_name") or "").strip(),
        "release_review_state": current_state,
        "target_version": str((row or {}).get("target_version") or "").strip(),
        "current_workspace_ref": str((row or {}).get("current_workspace_ref") or "").strip(),
        "prompt_version": str((row or {}).get("prompt_version") or "").strip(),
        "analysis_chain": analysis_chain,
        "report": report,
        "report_error": report_error,
        "report_error_code": report_error_code,
        "report_missing_fields": report_missing_fields,
        "required_report_fields": list(RELEASE_REVIEW_REQUIRED_FIELDS),
        "review_decision": review_decision,
        "reviewer": str((row or {}).get("reviewer") or "").strip(),
        "review_comment": str((row or {}).get("review_comment") or "").strip(),
        "reviewed_at": str((row or {}).get("reviewed_at") or "").strip(),
        "publish_version": str((row or {}).get("publish_version") or "").strip(),
        "publish_status": publish_status,
        "publish_error": publish_error,
        "execution_logs": execution_logs,
        "fallback": fallback,
        "public_profile_markdown_path": str((row or {}).get("public_profile_markdown_path") or "").strip(),
        "capability_snapshot_json_path": str((row or {}).get("capability_snapshot_json_path") or "").strip(),
        "created_at": str((row or {}).get("created_at") or "").strip(),
        "updated_at": str((row or {}).get("updated_at") or "").strip(),
        "codex_failure": report_codex_failure,
        "publish_codex_failure": publish_codex_failure,
        "can_enter": _can_enter_release_review(lifecycle_state, current_state),
        "can_discard": _can_discard_release_review(lifecycle_state, current_state, str((row or {}).get("review_id") or "").strip()),
        "can_review": current_state == "report_ready",
        "can_confirm": _can_confirm_release_review(lifecycle_state, current_state, review_decision),
        "publish_succeeded": publish_status == "success",
        "lifecycle_state": lifecycle_state,
    }
    return payload

def _list_agent_release_labels(conn: sqlite3.Connection, agent_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT version_label
        FROM agent_release_history
        WHERE agent_id=?
          AND COALESCE(classification,'normal_commit')='release'
        ORDER BY released_at DESC, created_at DESC
        """,
        (agent_id,),
    ).fetchall()
    return [str(row["version_label"] or "").strip() for row in rows if str(row["version_label"] or "").strip()]


def _switch_workspace_to_released_version(workspace_path: Path, version_label: str) -> None:
    target = str(version_label or "").strip()
    if not target:
        raise TrainingCenterError(400, "version_label required", "version_label_required")
    workspace = workspace_path.resolve(strict=False)
    if not workspace.exists() or not workspace.is_dir():
        raise TrainingCenterError(
            409,
            f"workspace missing: {workspace.as_posix()}",
            "workspace_missing",
            {"workspace_path": workspace.as_posix()},
        )
    ok, _ = _run_git_readonly(workspace, ["rev-parse", "--is-inside-work-tree"])
    if not ok:
        raise TrainingCenterError(
            409,
            "workspace git unavailable",
            "git_unavailable",
            {"workspace_path": workspace.as_posix()},
        )

    switch_cmd = [
        "git",
        "-C",
        workspace.as_posix(),
        "checkout",
        "-f",
        target,
        "--",
        ".",
    ]
    clean_cmd = ["git", "-C", workspace.as_posix(), "clean", "-fd"]
    for cmd in (switch_cmd, clean_cmd):
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=30,
            )
        except Exception as exc:  # pragma: no cover - subprocess failure branch
            raise TrainingCenterError(
                500,
                f"switch workspace failed: {exc}",
                "workspace_overwrite_failed",
                {"workspace_path": workspace.as_posix(), "version_label": target},
            ) from exc
        if proc.returncode != 0:
            raise TrainingCenterError(
                500,
                "switch workspace failed",
                "workspace_overwrite_failed",
                {
                    "workspace_path": workspace.as_posix(),
                    "version_label": target,
                    "stderr": str(proc.stderr or "").strip(),
                },
            )


def switch_training_agent_release(
    cfg: AppConfig,
    *,
    agent_id: str,
    version_label: str,
    operator: str,
) -> dict[str, Any]:
    sync_training_agent_registry(cfg)
    pid = safe_token(str(agent_id or ""), "", 120)
    target_version = str(version_label or "").strip()
    if not pid:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")
    if not target_version:
        raise TrainingCenterError(400, "version_label required", "version_label_required")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)

    conn = connect_db(cfg.root)
    try:
        agent = _resolve_training_agent(conn, pid)
        if agent is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": pid})
        source_agent_id = str(agent.get("agent_id") or "").strip()
        releases = _list_agent_release_labels(conn, source_agent_id)
    finally:
        conn.close()

    if target_version not in set(releases):
        raise TrainingCenterError(
            409,
            "仅支持已发布版本",
            "version_not_released",
            {"agent_id": source_agent_id, "version_label": target_version, "released_versions": releases[:80]},
        )

    current_version = str(agent.get("current_version") or "").strip()
    latest_release_version = (
        str(agent.get("latest_release_version") or "").strip()
        or (releases[0] if releases else "")
    )
    parent_agent_id = str(agent.get("parent_agent_id") or "").strip()
    if current_version != target_version:
        _switch_workspace_to_released_version(Path(str(agent.get("workspace_path") or "")), target_version)

    training_gate_state = derive_training_gate_state(
        lifecycle_state="released",
        current_version=target_version,
        latest_release_version=latest_release_version,
        parent_agent_id=parent_agent_id,
    )
    ts = iso_ts(now_local())
    conn = connect_db(cfg.root)
    try:
        conn.execute(
            """
            UPDATE agent_registry
            SET current_version=?,
                bound_release_version=?,
                lifecycle_state='released',
                training_gate_state=?,
                updated_at=?
            WHERE agent_id=?
            """,
            (target_version, target_version, training_gate_state, ts, source_agent_id),
        )
        conn.commit()
        updated = _resolve_training_agent(conn, source_agent_id) or {}
    finally:
        conn.close()

    audit_id = append_training_center_audit(
        cfg.root,
        action="switch_release",
        operator=operator_text,
        target_id=source_agent_id,
        detail={
            "mode": "overwrite_workspace",
            "from_version": current_version,
            "to_version": target_version,
            "latest_release_version": latest_release_version,
            "training_gate_state": training_gate_state,
        },
    )
    return {
        "agent_id": source_agent_id,
        "current_version": target_version,
        "bound_release_version": target_version,
        "latest_release_version": latest_release_version,
        "lifecycle_state": "released",
        "training_gate_state": training_gate_state,
        "frozen": training_gate_state == "frozen_switched",
        "audit_id": audit_id,
        "agent": updated,
    }
