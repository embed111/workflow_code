

def submit_training_agent_release_review_manual(
    cfg: AppConfig,
    *,
    agent_id: str,
    decision: str,
    reviewer: str,
    review_comment: str,
    operator: str,
) -> dict[str, Any]:
    sync_training_agent_registry(cfg)
    pid = safe_token(str(agent_id or ""), "", 120)
    if not pid:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")
    decision_text = str(decision or "").strip().lower()
    allowed = {"approve_publish", "reject_continue_training", "reject_discard_pre_release"}
    if decision_text not in allowed:
        raise TrainingCenterError(400, "decision invalid", "decision_invalid", {"allowed": sorted(allowed)})
    reviewer_text = safe_token(str(reviewer or ""), "", 80)
    if not reviewer_text:
        raise TrainingCenterError(400, "reviewer required", "reviewer_required")
    comment_text = str(review_comment or "").strip()
    operator_text = safe_token(str(operator or reviewer_text or "web-user"), "web-user", 80)

    conn = connect_db(cfg.root)
    try:
        agent = _resolve_training_agent(conn, pid)
        if agent is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": pid})
        source_agent_id = str(agent.get("agent_id") or "").strip()
        row = _latest_release_review_row(conn, source_agent_id)
    finally:
        conn.close()
    if row is None:
        raise TrainingCenterError(409, "release review not found", "release_review_not_found", {"agent_id": pid})
    current_state = str(row.get("release_review_state") or "").strip().lower()
    if current_state != "report_ready":
        raise TrainingCenterError(
            409,
            "release review report not ready",
            "release_review_report_not_ready",
            {"agent_id": source_agent_id, "release_review_state": current_state},
        )

    reviewed_at = iso_ts(now_local())
    next_state = "review_approved" if decision_text == "approve_publish" else "review_rejected"
    _update_release_review_row(
        cfg.root,
        str(row.get("review_id") or ""),
        {
            "release_review_state": next_state,
            "review_decision": decision_text,
            "reviewer": reviewer_text,
            "review_comment": comment_text,
            "reviewed_at": reviewed_at,
        },
    )

    legacy_decision = {
        "approve_publish": "approve",
        "reject_continue_training": "reject_continue_training",
        "reject_discard_pre_release": "reject_discard",
    }[decision_text]
    shadow_eval_id = _insert_release_evaluation_shadow_record(
        cfg.root,
        agent_id=source_agent_id,
        target_version=str(row.get("target_version") or ""),
        decision=legacy_decision,
        reviewer=reviewer_text,
        summary=comment_text,
    )

    decision_result: dict[str, Any] = {}
    if decision_text == "reject_discard_pre_release":
        decision_result = {
            "decision_action": "rejected_and_discarded",
            "discard_result": discard_agent_pre_release(
                cfg,
                agent_id=source_agent_id,
                operator=operator_text,
            ),
        }
    elif decision_text == "approve_publish":
        decision_result = {"decision_action": "approved_wait_confirm_publish"}
    else:
        decision_result = {"decision_action": "rejected_continue_training"}

    append_training_center_audit(
        cfg.root,
        action="release_review_manual",
        operator=operator_text,
        target_id=source_agent_id,
        detail={
            "review_id": str(row.get("review_id") or ""),
            "decision": decision_text,
            "reviewer": reviewer_text,
            "shadow_evaluation_id": shadow_eval_id,
        },
    )
    payload = get_training_agent_release_review(cfg.root, source_agent_id)
    payload["shadow_evaluation_id"] = shadow_eval_id
    payload["decision_result"] = decision_result
    return payload


def _execute_publish_attempt(
    cfg: AppConfig,
    *,
    agent: dict[str, Any],
    report: dict[str, Any],
    publish_version: str,
    review_comment: str,
    trace_dir: Path,
    execution_logs: list[dict[str, Any]],
    release_note_override: str = "",
) -> dict[str, Any]:
    workspace = Path(str(agent.get("workspace_path") or "")).resolve(strict=False)
    if not workspace.exists() or not workspace.is_dir():
        return {"ok": False, "error": "workspace_missing", "agent": agent}
    git_ready = _ensure_workspace_git_ready_for_publish(
        cfg,
        workspace=workspace,
        agent=agent,
        execution_logs=execution_logs,
    )
    if not git_ready.get("ok"):
        return {
            "ok": False,
            "error": str(git_ready.get("error") or "git_unavailable").strip() or "git_unavailable",
            "agent": agent,
            "stderr": str(git_ready.get("stderr") or "").strip(),
        }

    current_ref_before = _workspace_current_ref(workspace)
    status_ok, status_out, status_err = _run_git_readonly_verbose(
        workspace,
        ["status", "--porcelain", "--untracked-files=normal"],
        timeout_s=12,
    )
    if not status_ok:
        return {"ok": False, "error": "git_status_failed", "agent": agent, "stderr": status_err}
    dirty_lines = [str(line or "").rstrip() for line in str(status_out or "").splitlines() if str(line or "").strip()]
    _append_release_review_log(
        execution_logs,
        phase="prepare",
        status="done",
        message=f"准备发布版本 {publish_version}，工作区基线 {current_ref_before or '-'}，变更数={len(dirty_lines)}",
    )

    release_note_path = trace_dir / (f"release-note-{safe_token(publish_version, 'version', 80)}.md")
    release_note_text = (
        str(release_note_override or "").strip()
        if str(release_note_override or "").strip() and ("角色能力摘要" in str(release_note_override) or "version_notes" in str(release_note_override).lower())
        else _build_publish_release_note(
            agent=agent,
            report=report,
            publish_version=publish_version,
            review_comment=str(release_note_override or "").strip() or review_comment,
        )
    )
    _write_release_review_text(release_note_path, release_note_text)
    _append_release_review_log(
        execution_logs,
        phase="release_note",
        status="done",
        message="已生成 release note",
        path=_path_for_ui(cfg.root, release_note_path),
    )

    if dirty_lines:
        ok_add, _, add_err = _run_git_mutation(workspace, ["add", "-A"], timeout_s=30)
        if not ok_add:
            _append_release_review_log(
                execution_logs,
                phase="git_execute",
                status="failed",
                message="git add -A 失败",
                details={"stderr": _short_text(add_err, 400)},
            )
            return {"ok": False, "error": "git_add_failed", "agent": agent, "stderr": add_err}
        ok_commit, commit_out, commit_err = _run_git_mutation(
            workspace,
            ["commit", "-m", f"release: {publish_version}"],
            timeout_s=60,
        )
        if not ok_commit:
            _append_release_review_log(
                execution_logs,
                phase="git_execute",
                status="failed",
                message="git commit 失败",
                details={"stdout": _short_text(commit_out, 300), "stderr": _short_text(commit_err, 400)},
            )
            return {"ok": False, "error": "git_commit_failed", "agent": agent, "stderr": commit_err or commit_out}
        _append_release_review_log(
            execution_logs,
            phase="git_execute",
            status="done",
            message="已提交当前预发布内容",
            details={"stdout": _short_text(commit_out, 240)},
        )
    else:
        _append_release_review_log(
            execution_logs,
            phase="git_execute",
            status="done",
            message="工作区无额外改动，跳过提交",
        )

    preverified, precheck_row, precheck_error = _verify_release_note_before_tag(
        workspace,
        publish_version,
        release_note_text,
    )
    if not preverified:
        _append_release_review_log(
            execution_logs,
            phase="verify",
            status="failed",
            message="发布预校验失败，未创建标签",
            details={"reason": precheck_error, "publish_version": publish_version},
        )
        return {
            "ok": False,
            "error": precheck_error,
            "agent": agent,
            "publish_row": precheck_row,
            "release_note_path": _path_for_ui(cfg.root, release_note_path),
        }
    _append_release_review_log(
        execution_logs,
        phase="verify",
        status="done",
        message="发布预校验通过，准备创建标签",
        details={"publish_version": publish_version},
    )

    ok_tag, tag_out, tag_err = _run_git_mutation(
        workspace,
        ["tag", "-a", publish_version, "-F", release_note_path.as_posix()],
        timeout_s=30,
    )
    if not ok_tag:
        _append_release_review_log(
            execution_logs,
            phase="git_execute",
            status="failed",
            message="git tag 发布失败",
            details={"stdout": _short_text(tag_out, 300), "stderr": _short_text(tag_err, 400)},
        )
        return {"ok": False, "error": "git_tag_failed", "agent": agent, "stderr": tag_err or tag_out}
    _append_release_review_log(
        execution_logs,
        phase="git_execute",
        status="done",
        message=f"已创建发布标签 {publish_version}",
    )

    verified, publish_row, verify_error = _verify_published_release(workspace, publish_version)
    if not verified:
        _append_release_review_log(
            execution_logs,
            phase="verify",
            status="failed",
            message="发布成功校验失败",
            details={"reason": verify_error, "publish_version": publish_version},
        )
        return {"ok": False, "error": verify_error, "agent": agent, "publish_row": publish_row}
    released_at = str(publish_row.get("released_at") or "").strip() or iso_ts(now_local())
    updated_agent = _update_agent_after_publish(
        cfg,
        agent_id=str(agent.get("agent_id") or ""),
        publish_version=publish_version,
        released_at=released_at,
    )
    _append_release_review_log(
        execution_logs,
        phase="verify",
        status="done",
        message=f"发布成功校验通过：{publish_version}",
    )
    return {
        "ok": True,
        "agent": updated_agent,
        "publish_version": publish_version,
        "publish_row": publish_row,
        "release_note_path": _path_for_ui(cfg.root, release_note_path),
    }


def _run_publish_fallback_once(
    cfg: AppConfig,
    *,
    review_payload: dict[str, Any],
    agent: dict[str, Any],
    failed_publish_version: str,
    failed_error: str,
    trace_dir: Path,
    execution_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    _append_release_review_log(
        execution_logs,
        phase="fallback_trigger",
        status="running",
        message="已触发失败兜底，准备分析失败原因并自动重试一次",
    )
    fallback_dir = trace_dir / "fallback"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    prompt_text = _build_release_review_fallback_prompt(
        review=review_payload,
        publish_version=failed_publish_version,
        publish_error=failed_error,
        execution_logs=execution_logs,
    )
    codex_result = _run_codex_exec_for_release_review(
        root=cfg.root,
        workspace_root=Path(str(agent.get("workspace_path") or "")).resolve(strict=False),
        trace_dir=fallback_dir,
        prompt_text=prompt_text,
    )
    fallback_payload = {
        "status": "fallback_failed",
        "error": str(codex_result.get("error") or ""),
        "analysis_chain": codex_result.get("analysis_chain") if isinstance(codex_result.get("analysis_chain"), dict) else {},
        "result": codex_result.get("parsed_result") if isinstance(codex_result.get("parsed_result"), dict) else {},
        "repair_summary": "",
        "repair_actions": [],
        "warnings": [],
        "retry_result": {},
        "next_action_suggestion": "请先根据失败原因修复工作区或环境，再重试发布；若报告本身需要更新，再重新进入发布评审。",
    }
    if not codex_result.get("ok"):
        _append_release_review_log(
            execution_logs,
            phase="fallback_result",
            status="failed",
            message="兜底启动失败，需人工介入",
            details={"error": fallback_payload["error"]},
        )
        return fallback_payload

    fallback_result = codex_result.get("parsed_result") if isinstance(codex_result.get("parsed_result"), dict) else {}
    reason_text = _short_text(str(fallback_result.get("failure_reason") or failed_error or "发布失败").strip(), 320)
    repair_summary = _short_text(str(fallback_result.get("repair_summary") or "").strip(), 320)
    repair_actions = _ensure_first_person_list(fallback_result.get("repair_actions"), "我已执行的修复动作：", limit=8, item_limit=220)
    fallback_warnings = _ensure_first_person_list(fallback_result.get("warnings"), "我还需要提示：", limit=8, item_limit=220)
    retry_note_text = str(fallback_result.get("retry_release_notes") or "").strip()
    _append_release_review_log(
        execution_logs,
        phase="fallback_trigger",
        status="done",
        message="兜底已完成失败诊断，并给出修复动作后准备自动重试",
        details={
            "failure_reason": reason_text,
            "repair_summary": repair_summary,
            "repair_actions": repair_actions,
            "warnings": fallback_warnings,
        },
    )
    _, _, rows = _parse_git_release_rows(Path(str(agent.get("workspace_path") or "")).resolve(strict=False), limit=120)
    existing_labels = [str(row.get("version_label") or "").strip() for row in rows if str(row.get("version_label") or "").strip()]
    retry_version = _next_release_version_label(existing_labels, str(fallback_result.get("retry_target_version") or failed_publish_version).strip())
    retry_attempt = _execute_publish_attempt(
        cfg,
        agent=agent,
        report=review_payload.get("report") if isinstance(review_payload.get("report"), dict) else {},
        publish_version=retry_version,
        review_comment=str(review_payload.get("review_comment") or "").strip(),
        trace_dir=fallback_dir,
        execution_logs=execution_logs,
        release_note_override=retry_note_text,
    )
    fallback_payload = {
        "status": "fallback_done" if retry_attempt.get("ok") else "fallback_failed",
        "failure_reason": reason_text,
        "analysis_chain": codex_result.get("analysis_chain") if isinstance(codex_result.get("analysis_chain"), dict) else {},
        "result": fallback_result,
        "repair_summary": repair_summary,
        "repair_actions": repair_actions,
        "warnings": fallback_warnings,
        "retry_result": retry_attempt,
        "next_action_suggestion": _short_text(
            str(
                fallback_result.get("next_action_suggestion")
                or "请先根据兜底诊断修复工作区或环境，然后直接重试发布；若报告本身需要更新，再重新进入发布评审。"
            ).strip(),
            320,
        ),
    }
    _append_release_review_log(
        execution_logs,
        phase="fallback_result",
        status="done" if retry_attempt.get("ok") else "failed",
        message="兜底自动重试完成" if retry_attempt.get("ok") else "兜底自动重试后仍失败",
        details={
            "retry_version": retry_version,
            "error": str(retry_attempt.get("error") or ""),
        },
    )
    return fallback_payload


def confirm_training_agent_release_review(
    cfg: AppConfig,
    *,
    agent_id: str,
    operator: str,
) -> dict[str, Any]:
    sync_training_agent_registry(cfg)
    pid = safe_token(str(agent_id or ""), "", 120)
    if not pid:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)
    conn = connect_db(cfg.root)
    try:
        agent = _resolve_training_agent(conn, pid)
        if agent is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": pid})
        source_agent_id = str(agent.get("agent_id") or "").strip()
        row = _latest_release_review_row(conn, source_agent_id)
    finally:
        conn.close()
    if row is None:
        raise TrainingCenterError(409, "release review not found", "release_review_not_found", {"agent_id": pid})
    current_state = str(row.get("release_review_state") or "").strip()
    review_decision = str(row.get("review_decision") or "").strip()
    lifecycle_state = str(agent.get("lifecycle_state") or "").strip()
    if not _can_confirm_release_review(lifecycle_state, current_state, review_decision):
        raise TrainingCenterError(
            409,
            "release review not approved",
            "release_review_not_approved",
            {"release_review_state": current_state, "review_decision": review_decision, "lifecycle_state": lifecycle_state},
        )
    if review_decision != "approve_publish":
        raise TrainingCenterError(
            409,
            "review decision is not approve_publish",
            "review_decision_not_approve_publish",
            {"review_decision": review_decision},
        )

    review_payload = _release_review_payload(agent, row)
    review_id = str(row.get("review_id") or "").strip()
    trace_dir_text = str((review_payload.get("analysis_chain") or {}).get("trace_dir") or "").strip()
    trace_dir = (cfg.root / trace_dir_text).resolve(strict=False) if trace_dir_text else _release_review_trace_dir(cfg.root, str(agent.get("agent_name") or source_agent_id), review_id)
    execution_logs = review_payload.get("execution_logs") if isinstance(review_payload.get("execution_logs"), list) else []
    workspace = Path(str(agent.get("workspace_path") or "")).resolve(strict=False)
    retrying_failed_publish = current_state == "publish_failed"
    attempt_trace_dir = _release_review_attempt_dir(trace_dir, "manual-retry") if retrying_failed_publish else trace_dir
    if retrying_failed_publish:
        _append_release_review_log(
            execution_logs,
            phase="prepare",
            status="running",
            message="检测到上次确认发布失败，开始基于当前评审记录手动重试发布",
            details={"review_id": review_id},
        )
    publish_version = _next_release_version_label(
        _workspace_release_labels(workspace),
        str(review_payload.get("target_version") or "").strip(),
    )
    _update_release_review_row(
        cfg.root,
        review_id,
        {
            "release_review_state": "publish_running",
            "publish_status": "",
            "publish_error": "",
            "publish_version": publish_version,
            "execution_log_json": execution_logs,
            "fallback_json": {},
        },
    )

    append_training_center_audit(
        cfg.root,
        action="release_review_confirm",
        operator=operator_text,
        target_id=source_agent_id,
        detail={"review_id": review_id, "publish_version": publish_version, "retry_mode": "manual" if retrying_failed_publish else "initial"},
    )

    publish_result = _execute_publish_attempt(
        cfg,
        agent=agent,
        report=review_payload.get("report") if isinstance(review_payload.get("report"), dict) else {},
        publish_version=publish_version,
        review_comment=str(review_payload.get("review_comment") or "").strip(),
        trace_dir=attempt_trace_dir,
        execution_logs=execution_logs,
    )
    if publish_result.get("ok"):
        _bind_release_profile_after_publish(
            cfg,
            agent_id=source_agent_id,
            publish_version=str(publish_result.get("publish_version") or publish_version),
            review_id=review_id,
            analysis_chain=review_payload.get("analysis_chain") if isinstance(review_payload.get("analysis_chain"), dict) else {},
            public_profile_markdown_path=str(row.get("public_profile_markdown_path") or "").strip(),
            capability_snapshot_json_path=str(row.get("capability_snapshot_json_path") or "").strip(),
        )
        _update_release_review_row(
            cfg.root,
            review_id,
            {
                "release_review_state": "idle",
                "publish_status": "success",
                "publish_error": "",
                "publish_version": str(publish_result.get("publish_version") or publish_version),
                "execution_log_json": execution_logs,
                "fallback_json": {},
            },
        )
        return get_training_agent_release_review(cfg.root, source_agent_id)

    publish_error = str(publish_result.get("error") or "publish_failed").strip() or "publish_failed"
    fallback_payload = _run_publish_fallback_once(
        cfg,
        review_payload=review_payload,
        agent=agent,
        failed_publish_version=publish_version,
        failed_error=publish_error,
        trace_dir=attempt_trace_dir,
        execution_logs=execution_logs,
    )
    retry_result = fallback_payload.get("retry_result") if isinstance(fallback_payload.get("retry_result"), dict) else {}
    if retry_result.get("ok"):
        _bind_release_profile_after_publish(
            cfg,
            agent_id=source_agent_id,
            publish_version=str(retry_result.get("publish_version") or publish_version),
            review_id=review_id,
            analysis_chain=review_payload.get("analysis_chain") if isinstance(review_payload.get("analysis_chain"), dict) else {},
            public_profile_markdown_path=str(row.get("public_profile_markdown_path") or "").strip(),
            capability_snapshot_json_path=str(row.get("capability_snapshot_json_path") or "").strip(),
        )
        _update_release_review_row(
            cfg.root,
            review_id,
            {
                "release_review_state": "idle",
                "publish_status": "success",
                "publish_error": "",
                "publish_version": str(retry_result.get("publish_version") or publish_version),
                "execution_log_json": execution_logs,
                "fallback_json": fallback_payload,
            },
        )
        return get_training_agent_release_review(cfg.root, source_agent_id)

    _update_release_review_row(
        cfg.root,
        review_id,
        {
            "release_review_state": "publish_failed",
            "publish_status": "failed",
            "publish_error": publish_error,
            "publish_version": publish_version,
            "execution_log_json": execution_logs,
            "fallback_json": fallback_payload,
        },
    )
    append_training_center_audit(
        cfg.root,
        action="release_review_publish_failed",
        operator=operator_text,
        target_id=source_agent_id,
        detail={
            "review_id": review_id,
            "publish_version": publish_version,
            "publish_error": publish_error,
            "fallback_status": str(fallback_payload.get("status") or ""),
        },
    )
    return get_training_agent_release_review(cfg.root, source_agent_id)
