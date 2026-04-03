

def clone_training_agent_from_current(
    cfg: AppConfig,
    *,
    agent_id: str,
    new_agent_name: str,
    operator: str,
) -> dict[str, Any]:
    root = cfg.agent_search_root
    if root is None:
        raise TrainingCenterError(
            409,
            "agent_search_root 未设置",
            "agent_search_root_not_ready",
    )
    source_agent_key = safe_token(str(agent_id or ""), "", 120)
    clone_agent_name = safe_token(str(new_agent_name or ""), "", 80).strip("-._:")
    clone_agent_id = safe_token(clone_agent_name, clone_agent_name, 120).strip("-._:")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)
    if not source_agent_key:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")
    if not clone_agent_name:
        raise TrainingCenterError(400, "new_agent_name required", "new_agent_name_required")
    if not clone_agent_id:
        raise TrainingCenterError(400, "new_agent_name invalid", "new_agent_name_invalid")

    sync_training_agent_registry(cfg)
    conn = connect_db(cfg.root)
    try:
        source = _resolve_training_agent(conn, source_agent_key)
        if source is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": source_agent_key})
        source_agent_id = str(source.get("agent_id") or "").strip()
        name_exists = conn.execute(
            "SELECT agent_id FROM agent_registry WHERE agent_name=? COLLATE NOCASE LIMIT 1",
            (clone_agent_name,),
        ).fetchone()
        if name_exists is not None:
            raise TrainingCenterError(
                409,
                "new_agent_name already exists",
                "agent_name_conflict",
                {"new_agent_name": clone_agent_name},
            )
        exists = conn.execute(
            "SELECT 1 AS ok FROM agent_registry WHERE agent_id=? LIMIT 1",
            (clone_agent_id,),
        ).fetchone()
        if exists is not None:
            raise TrainingCenterError(
                409,
                "new_agent_id already exists",
                "agent_id_conflict",
                {"new_agent_id": clone_agent_id},
            )
    finally:
        conn.close()

    source_workspace = Path(str(source.get("workspace_path") or "")).resolve(strict=False)
    if not source_workspace.exists() or not source_workspace.is_dir():
        raise TrainingCenterError(
            409,
            "source workspace missing",
            "workspace_missing",
            {"workspace_path": source_workspace.as_posix()},
        )
    clone_workspace = (root / clone_agent_id).resolve(strict=False)
    if not path_in_scope(clone_workspace, root.resolve(strict=False)):
        raise TrainingCenterError(
            409,
            "clone workspace out of scope",
            "workspace_out_of_scope",
            {"workspace_path": clone_workspace.as_posix()},
        )
    if clone_workspace.exists():
        raise TrainingCenterError(
            409,
            "clone workspace already exists",
            "agent_id_conflict",
            {"new_agent_id": clone_agent_id},
        )
    try:
        shutil.copytree(source_workspace, clone_workspace)
    except Exception as exc:  # pragma: no cover - copy failure branch
        raise TrainingCenterError(
            500,
            f"clone workspace failed: {exc}",
            "clone_workspace_failed",
            {"source": source_workspace.as_posix(), "target": clone_workspace.as_posix()},
        ) from exc

    sync_training_agent_registry(cfg)
    ts = iso_ts(now_local())
    source_current_version = str(source.get("current_version") or "").strip()
    source_bound_version = str(source.get("bound_release_version") or "").strip()
    clone_base_version = source_current_version or source_bound_version
    conn = connect_db(cfg.root)
    try:
        conn.execute(
            """
            UPDATE agent_registry
            SET agent_name=?,
                parent_agent_id=?,
                current_version=CASE WHEN ?<>'' THEN ? ELSE current_version END,
                latest_release_version=CASE WHEN ?<>'' THEN ? ELSE latest_release_version END,
                bound_release_version=CASE WHEN ?<>'' THEN ? ELSE bound_release_version END,
                lifecycle_state='released',
                training_gate_state='trainable',
                updated_at=?
            WHERE agent_id=?
            """,
            (
                clone_agent_name,
                source_agent_id,
                clone_base_version,
                clone_base_version,
                clone_base_version,
                clone_base_version,
                clone_base_version,
                clone_base_version,
                ts,
                clone_agent_id,
            ),
        )
        conn.commit()
        cloned = _resolve_training_agent(conn, clone_agent_id) or {}
    finally:
        conn.close()

    sync_training_agent_registry(cfg)
    audit_id = append_training_center_audit(
        cfg.root,
        action="clone_agent",
        operator=operator_text,
        target_id=clone_agent_id,
        detail={
            "clone_agent_id_generated": True,
            "source_agent_id": source_agent_id,
            "source_workspace": source_workspace.as_posix(),
            "clone_workspace": clone_workspace.as_posix(),
            "clone_agent_name": clone_agent_name,
            "clone_base_version": clone_base_version,
        },
    )
    return {
        "agent_id": clone_agent_id,
        "agent_name": str(cloned.get("agent_name") or clone_agent_name or clone_agent_id),
        "workspace_path": clone_workspace.as_posix(),
        "parent_agent_id": source_agent_id,
        "current_version": str(cloned.get("current_version") or clone_base_version),
        "latest_release_version": str(cloned.get("latest_release_version") or clone_base_version),
        "bound_release_version": str(cloned.get("bound_release_version") or clone_base_version),
        "lifecycle_state": normalize_lifecycle_state(cloned.get("lifecycle_state")),
        "training_gate_state": normalize_training_gate_state(cloned.get("training_gate_state")),
        "audit_id": audit_id,
        "agent": cloned,
    }


def discard_agent_pre_release(
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
        lifecycle_state = normalize_lifecycle_state(agent.get("lifecycle_state"))
        release_labels = _list_agent_release_labels(conn, source_agent_id)
    finally:
        conn.close()

    if lifecycle_state != "pre_release":
        return {
            "agent_id": source_agent_id,
            "lifecycle_state": lifecycle_state,
            "training_gate_state": normalize_training_gate_state(agent.get("training_gate_state")),
            "discarded": False,
            "message": "not_in_pre_release",
            "code": "not_in_pre_release",
        }
    if not release_labels:
        raise TrainingCenterError(
            409,
            "discard requires at least one released version",
            "no_released_version_to_discard",
            {"agent_id": source_agent_id},
        )

    current_version = str(agent.get("current_version") or "").strip()
    latest_release_version = str(agent.get("latest_release_version") or "").strip()
    parent_agent_id = str(agent.get("parent_agent_id") or "").strip()
    bound_release_version = str(agent.get("bound_release_version") or "").strip()
    release_set = set(release_labels)
    target_release_version = bound_release_version
    if release_labels:
        if not target_release_version or target_release_version not in release_set:
            target_release_version = latest_release_version or release_labels[0]
    if target_release_version and target_release_version != current_version and target_release_version in release_set:
        _switch_workspace_to_released_version(
            Path(str(agent.get("workspace_path") or "")),
            target_release_version,
        )

    final_version = target_release_version or current_version
    training_gate_state = derive_training_gate_state(
        lifecycle_state="released",
        current_version=final_version,
        latest_release_version=latest_release_version,
        parent_agent_id=parent_agent_id,
        preferred=agent.get("training_gate_state"),
    )
    ts = iso_ts(now_local())
    conn = connect_db(cfg.root)
    try:
        conn.execute(
            """
            UPDATE agent_registry
            SET current_version=CASE WHEN ?<>'' THEN ? ELSE current_version END,
                bound_release_version=CASE WHEN ?<>'' THEN ? ELSE bound_release_version END,
                lifecycle_state='released',
                training_gate_state=?,
                updated_at=?
            WHERE agent_id=?
            """,
            (
                final_version,
                final_version,
                final_version,
                final_version,
                training_gate_state,
                ts,
                source_agent_id,
            ),
        )
        conn.commit()
        updated = _resolve_training_agent(conn, source_agent_id) or {}
    finally:
        conn.close()

    audit_id = append_training_center_audit(
        cfg.root,
        action="discard_pre_release",
        operator=operator_text,
        target_id=source_agent_id,
        detail={
            "from_version": current_version,
            "to_version": final_version,
            "bound_release_version": bound_release_version,
            "latest_release_version": latest_release_version,
        },
    )
    return {
        "agent_id": source_agent_id,
        "discarded": True,
        "current_version": final_version,
        "bound_release_version": final_version,
        "lifecycle_state": "released",
        "training_gate_state": training_gate_state,
        "audit_id": audit_id,
        "agent": updated,
    }


def submit_manual_release_evaluation(
    cfg: AppConfig,
    *,
    agent_id: str,
    decision: str,
    reviewer: str,
    summary: str,
    operator: str,
) -> dict[str, Any]:
    sync_training_agent_registry(cfg)
    pid = safe_token(str(agent_id or ""), "", 120)
    if not pid:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")
    decision_text = str(decision or "").strip().lower()
    if decision_text not in {"approve", "reject_continue_training", "reject_discard"}:
        raise TrainingCenterError(
            400,
            "decision invalid",
            "decision_invalid",
            {"allowed": ["approve", "reject_continue_training", "reject_discard"]},
        )
    reviewer_text = safe_token(str(reviewer or ""), "", 80)
    if not reviewer_text:
        raise TrainingCenterError(400, "reviewer required", "reviewer_required")
    summary_text = str(summary or "").strip()
    operator_text = safe_token(str(operator or reviewer_text or "web-user"), "web-user", 80)

    conn = connect_db(cfg.root)
    try:
        agent = _resolve_training_agent(conn, pid)
        if agent is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": pid})
        source_agent_id = str(agent.get("agent_id") or "").strip()
        lifecycle_state = normalize_lifecycle_state(agent.get("lifecycle_state"))
        release_labels = _list_agent_release_labels(conn, source_agent_id)
        if lifecycle_state != "pre_release":
            raise TrainingCenterError(
                409,
                "agent not in pre_release",
                "not_in_pre_release",
                {"agent_id": source_agent_id, "lifecycle_state": lifecycle_state},
            )
        if decision_text == "reject_discard" and not release_labels:
            raise TrainingCenterError(
                409,
                "reject_discard requires at least one released version",
                "no_released_version_to_discard",
                {"agent_id": source_agent_id},
            )

        evaluation_id = training_release_evaluation_id()
        ts = iso_ts(now_local())
        target_version = str(agent.get("current_version") or "").strip()
        conn.execute(
            """
            INSERT INTO agent_release_evaluation (
                evaluation_id,agent_id,target_version,decision,reviewer,summary,created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                evaluation_id,
                source_agent_id,
                target_version,
                decision_text,
                reviewer_text,
                _short_text(summary_text, 1000),
                ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    decision_result: dict[str, Any] = {}
    if decision_text == "approve":
        latest_release_version = str(agent.get("latest_release_version") or "").strip()
        parent_agent_id = str(agent.get("parent_agent_id") or "").strip()
        current_version = str(agent.get("current_version") or "").strip()
        bound_release_version = str(agent.get("bound_release_version") or "").strip() or current_version
        training_gate_state = derive_training_gate_state(
            lifecycle_state="released",
            current_version=current_version,
            latest_release_version=latest_release_version,
            parent_agent_id=parent_agent_id,
            preferred=agent.get("training_gate_state"),
        )
        ts = iso_ts(now_local())
        conn = connect_db(cfg.root)
        try:
            conn.execute(
                """
                UPDATE agent_registry
                SET lifecycle_state='released',
                    bound_release_version=CASE WHEN ?<>'' THEN ? ELSE bound_release_version END,
                    training_gate_state=?,
                    updated_at=?
                WHERE agent_id=?
                """,
                (
                    bound_release_version,
                    bound_release_version,
                    training_gate_state,
                    ts,
                    source_agent_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        decision_result = {
            "decision_action": "approved_to_released",
            "lifecycle_state": "released",
            "training_gate_state": training_gate_state,
        }
    elif decision_text == "reject_discard":
        decision_result = {
            "decision_action": "rejected_and_discarded",
            "discard_result": discard_agent_pre_release(
                cfg,
                agent_id=source_agent_id,
                operator=operator_text,
            ),
        }
    else:
        decision_result = {
            "decision_action": "rejected_continue_training",
            "lifecycle_state": "pre_release",
            "training_gate_state": normalize_training_gate_state(agent.get("training_gate_state")),
        }

    conn = connect_db(cfg.root)
    try:
        updated = _resolve_training_agent(conn, source_agent_id) or {}
    finally:
        conn.close()

    audit_id = append_training_center_audit(
        cfg.root,
        action="manual_release_evaluation",
        operator=operator_text,
        target_id=source_agent_id,
        detail={
            "evaluation_id": evaluation_id,
            "decision": decision_text,
            "reviewer": reviewer_text,
            "summary": _short_text(summary_text, 180),
            "decision_action": decision_result.get("decision_action"),
        },
    )
    return {
        "evaluation_id": evaluation_id,
        "agent_id": source_agent_id,
        "target_version": str(agent.get("current_version") or ""),
        "decision": decision_text,
        "reviewer": reviewer_text,
        "summary": summary_text,
        "audit_id": audit_id,
        "decision_result": decision_result,
        "agent": updated,
    }


def get_training_agent_release_review(
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    pid = safe_token(str(agent_id or ""), "", 120)
    if not pid:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")
    conn = connect_db(root)
    try:
        agent = _resolve_training_agent(conn, pid)
        if agent is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": pid})
        source_agent_id = str(agent.get("agent_id") or "").strip()
        row = _latest_release_review_row(conn, source_agent_id)
    finally:
        conn.close()
    return {"review": _release_review_payload(agent, row)}


def enter_training_agent_release_review(
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
        lifecycle_state = normalize_lifecycle_state(agent.get("lifecycle_state"))
        if lifecycle_state != "pre_release":
            raise TrainingCenterError(
                409,
                "agent not in pre_release",
                "not_in_pre_release",
                {"agent_id": source_agent_id, "lifecycle_state": lifecycle_state},
            )
        latest_row = _latest_release_review_row(conn, source_agent_id)
        latest_state = str((latest_row or {}).get("release_review_state") or "idle").strip() or "idle"
        if not _can_enter_release_review(lifecycle_state, latest_state):
            raise TrainingCenterError(
                409,
                "release review already active",
                "release_review_already_active",
                {"agent_id": source_agent_id, "release_review_state": latest_state},
            )
        release_labels = _list_agent_release_labels(conn, source_agent_id)
    finally:
        conn.close()

    workspace_path = Path(str(agent.get("workspace_path") or "")).resolve(strict=False)
    if not workspace_path.exists() or not workspace_path.is_dir():
        raise TrainingCenterError(
            409,
            "workspace missing",
            "workspace_missing",
            {"workspace_path": workspace_path.as_posix()},
        )
    current_workspace_ref = _workspace_current_ref(workspace_path) or str(agent.get("current_version") or "").strip()
    review_id = training_release_review_id()
    created_at = iso_ts(now_local())
    target_version = _next_release_version_label(release_labels)
    trace_dir = _release_review_trace_dir(cfg.root, str(agent.get("agent_name") or source_agent_id), review_id)
    conn = connect_db(cfg.root)
    try:
        conn.execute(
            """
            INSERT INTO agent_release_review (
                review_id,agent_id,target_version,current_workspace_ref,release_review_state,prompt_version,
                analysis_chain_json,report_json,report_error,review_decision,reviewer,review_comment,reviewed_at,
                publish_version,publish_status,publish_error,execution_log_json,fallback_json,
                public_profile_markdown_path,capability_snapshot_json_path,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                review_id,
                source_agent_id,
                target_version,
                current_workspace_ref,
                "report_generating",
                RELEASE_REVIEW_PROMPT_VERSION,
                "{}",
                "{}",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "[]",
                "{}",
                "",
                "",
                created_at,
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    enter_audit_id = append_training_center_audit(
        cfg.root,
        action="release_review_enter",
        operator=operator_text,
        target_id=source_agent_id,
        detail={
            "review_id": review_id,
            "target_version": target_version,
            "current_workspace_ref": current_workspace_ref,
            "prompt_version": RELEASE_REVIEW_PROMPT_VERSION,
        },
    )

    metadata_conflicts = _release_review_metadata_conflicts(
        agent=agent,
        target_version=target_version,
        released_versions=release_labels,
    )
    if metadata_conflicts:
        metadata_exc = TrainingCenterError(
            409,
            "release review metadata conflict",
            "release_review_metadata_conflict",
            {"metadata_conflicts": metadata_conflicts},
        )
        report_error = _describe_release_review_report_failure(metadata_exc)
        failure_report = _build_release_review_failure_report(
            {"metadata_conflicts": metadata_conflicts},
            agent=agent,
            target_version=target_version,
            current_workspace_ref=current_workspace_ref,
            codex_error="metadata_conflict",
            error_code=metadata_exc.code,
            error_message=report_error,
            metadata_conflicts=metadata_conflicts,
        )
        _write_release_review_json(trace_dir / "parsed-result.json", failure_report)
        analysis_chain = {
            "trace_dir": _path_for_ui(cfg.root, trace_dir),
            "report_path": _path_for_ui(cfg.root, trace_dir / "parsed-result.json"),
            "prompt_version": RELEASE_REVIEW_PROMPT_VERSION,
            "error": "metadata_conflict",
            "report_error_code": metadata_exc.code,
            "report_missing_fields": [],
            "metadata_conflicts": metadata_conflicts,
        }
        _update_release_review_row(
            cfg.root,
            review_id,
            {
                "release_review_state": "report_failed",
                "analysis_chain_json": analysis_chain,
                "report_json": failure_report,
                "report_error": report_error,
            },
        )
        append_training_center_audit(
            cfg.root,
            action="release_review_report_failed",
            operator=operator_text,
            target_id=source_agent_id,
            detail={
                "review_id": review_id,
                "error": str(metadata_exc),
                "code": metadata_exc.code,
                "metadata_conflicts": metadata_conflicts,
                "enter_audit_id": enter_audit_id,
            },
        )
        return get_training_agent_release_review(cfg.root, source_agent_id)

    prompt_text = _build_release_review_prompt(
        agent=agent,
        workspace_path=workspace_path,
        target_version=target_version,
        current_workspace_ref=current_workspace_ref,
        released_versions=release_labels,
    )
    codex_result = _run_codex_exec_for_release_review(
        root=cfg.root,
        workspace_root=workspace_path,
        trace_dir=trace_dir,
        prompt_text=prompt_text,
    )
    try:
        codex_error = str(codex_result.get("error") or "").strip()
        if codex_error and codex_error != "codex_result_missing":
            raise TrainingCenterError(
                500,
                "release review report failed",
                "release_review_report_failed",
                {"reason": codex_error or "codex_result_missing"},
            )
        report = _normalize_release_review_report(
            codex_result.get("parsed_result") if isinstance(codex_result.get("parsed_result"), dict) else {},
            agent=agent,
            target_version=target_version,
            current_workspace_ref=current_workspace_ref,
            codex_error=codex_error,
        )
        analysis_chain = codex_result.get("analysis_chain") if isinstance(codex_result.get("analysis_chain"), dict) else {}
        analysis_chain["prompt_version"] = RELEASE_REVIEW_PROMPT_VERSION
        analysis_chain["report_error_code"] = ""
        analysis_chain["report_missing_fields"] = []
        _write_release_review_json(trace_dir / "parsed-result.json", report)
        profile_assets = _write_release_review_profile_assets(
            root=cfg.root,
            trace_dir=trace_dir,
            agent=agent,
            review_id=review_id,
            report=report,
            analysis_chain=analysis_chain,
        )
        analysis_chain["public_profile_markdown_path"] = str(profile_assets.get("public_profile_markdown_path") or "")
        analysis_chain["capability_snapshot_json_path"] = str(profile_assets.get("capability_snapshot_json_path") or "")
        _update_release_review_row(
            cfg.root,
            review_id,
            {
                "target_version": str(report.get("target_version") or "").strip(),
                "current_workspace_ref": str(report.get("current_workspace_ref") or "").strip(),
                "release_review_state": "report_ready",
                "analysis_chain_json": analysis_chain,
                "report_json": report,
                "report_error": "",
                "public_profile_markdown_path": str(profile_assets.get("public_profile_markdown_path") or ""),
                "capability_snapshot_json_path": str(profile_assets.get("capability_snapshot_json_path") or ""),
            },
        )
        append_training_center_audit(
            cfg.root,
            action="release_review_report_ready",
            operator=operator_text,
            target_id=source_agent_id,
            detail={
                "review_id": review_id,
                "prompt_version": RELEASE_REVIEW_PROMPT_VERSION,
                "report_path": str(analysis_chain.get("report_path") or ""),
                "stdout_path": str(analysis_chain.get("stdout_path") or ""),
                "stderr_path": str(analysis_chain.get("stderr_path") or ""),
                "public_profile_markdown_path": str(profile_assets.get("public_profile_markdown_path") or ""),
                "capability_snapshot_json_path": str(profile_assets.get("capability_snapshot_json_path") or ""),
            },
        )
    except TrainingCenterError as exc:
        analysis_chain = codex_result.get("analysis_chain") if isinstance(codex_result.get("analysis_chain"), dict) else {}
        analysis_chain["prompt_version"] = RELEASE_REVIEW_PROMPT_VERSION
        analysis_chain["error"] = str(codex_result.get("error") or exc.code or "").strip()
        extra = getattr(exc, "extra", {}) if isinstance(getattr(exc, "extra", {}), dict) else {}
        report_error = _describe_release_review_report_failure(exc, codex_result=codex_result)
        missing_fields = [
            str(item or "").strip()
            for item in (extra.get("missing_fields") or [])
            if str(item or "").strip()
        ]
        metadata_conflicts = [
            str(item or "").strip()
            for item in (extra.get("metadata_conflicts") or [])
            if str(item or "").strip()
        ]
        failure_report = _build_release_review_failure_report(
            codex_result.get("parsed_result") if isinstance(codex_result.get("parsed_result"), dict) else {},
            agent=agent,
            target_version=target_version,
            current_workspace_ref=current_workspace_ref,
            codex_error=str(codex_result.get("error") or "").strip(),
            error_code=str(exc.code or "").strip(),
            error_message=report_error,
            missing_fields=missing_fields,
            metadata_conflicts=metadata_conflicts,
        )
        _write_release_review_json(trace_dir / "parsed-result.json", failure_report)
        analysis_chain["report_error_code"] = str(exc.code or "").strip()
        analysis_chain["report_missing_fields"] = missing_fields
        if metadata_conflicts:
            analysis_chain["metadata_conflicts"] = metadata_conflicts
        _update_release_review_row(
            cfg.root,
            review_id,
            {
                "release_review_state": "report_failed",
                "analysis_chain_json": analysis_chain,
                "report_json": failure_report,
                "report_error": report_error,
            },
        )
        append_training_center_audit(
            cfg.root,
            action="release_review_report_failed",
            operator=operator_text,
            target_id=source_agent_id,
            detail={
                "review_id": review_id,
                "error": str(exc),
                "code": exc.code,
                "enter_audit_id": enter_audit_id,
            },
        )
    return get_training_agent_release_review(cfg.root, source_agent_id)


def discard_training_agent_release_review(
    cfg: AppConfig,
    *,
    agent_id: str,
    operator: str,
    reason: str = "",
) -> dict[str, Any]:
    sync_training_agent_registry(cfg)
    pid = safe_token(str(agent_id or ""), "", 120)
    if not pid:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)
    reason_text = _short_text(str(reason or "").strip(), 500)

    conn = connect_db(cfg.root)
    try:
        agent = _resolve_training_agent(conn, pid)
        if agent is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": pid})
        source_agent_id = str(agent.get("agent_id") or "").strip()
        lifecycle_state = normalize_lifecycle_state(agent.get("lifecycle_state"))
        row = _latest_release_review_row(conn, source_agent_id)
    finally:
        conn.close()

    if lifecycle_state != "pre_release":
        raise TrainingCenterError(
            409,
            "agent not in pre_release",
            "not_in_pre_release",
            {"agent_id": source_agent_id, "lifecycle_state": lifecycle_state},
        )
    if row is None:
        raise TrainingCenterError(409, "release review not found", "release_review_not_found", {"agent_id": pid})

    review_id = str(row.get("review_id") or "").strip()
    current_state = str(row.get("release_review_state") or "").strip().lower() or "idle"
    if not _can_discard_release_review(lifecycle_state, current_state, review_id):
        raise TrainingCenterError(
            409,
            "release review not discardable",
            "release_review_not_discardable",
            {"agent_id": source_agent_id, "release_review_state": current_state},
        )

    execution_logs = _json_load_list(row.get("execution_log_json"))
    reviewed_at = iso_ts(now_local())
    comment_text = reason_text or "已废弃当前发布评审记录"
    _append_release_review_log(
        execution_logs,
        phase="review_discard",
        status="done",
        message="已废弃当前发布评审记录，可重新进入发布评审",
        details={
            "operator": operator_text,
            "reason": reason_text,
            "from_state": current_state,
        },
    )
    _update_release_review_row(
        cfg.root,
        review_id,
        {
            "release_review_state": "review_discarded",
            "review_decision": "discard_review",
            "reviewer": operator_text,
            "review_comment": comment_text,
            "reviewed_at": reviewed_at,
            "execution_log_json": execution_logs,
        },
    )
    append_training_center_audit(
        cfg.root,
        action="release_review_discard",
        operator=operator_text,
        target_id=source_agent_id,
        detail={
            "review_id": review_id,
            "from_state": current_state,
            "reason": reason_text,
        },
    )
    payload = get_training_agent_release_review(cfg.root, source_agent_id)
    payload["discarded"] = True
    payload["discard_reason"] = reason_text
    return payload
