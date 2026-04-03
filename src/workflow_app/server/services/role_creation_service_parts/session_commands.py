def create_role_creation_session(cfg: Any, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_id = _role_creation_session_id()
    now_text = _tc_now_text()
    requested_title = _normalize_text(
        body.get("session_title") or body.get("title") or "未命名角色草稿",
        max_len=80,
    ) or "未命名角色草稿"
    dialogue_agent = _resolve_role_creation_dialogue_agent(cfg)
    conn = connect_db(cfg.root)
    try:
        conn.execute(
            """
            INSERT INTO role_creation_sessions (
                session_id,session_title,status,current_stage_key,current_stage_index,role_spec_json,missing_fields_json,
                assignment_ticket_id,created_agent_id,created_agent_name,created_agent_workspace_path,workspace_init_status,
                workspace_init_ref,dialogue_agent_name,dialogue_agent_workspace_path,dialogue_provider,last_dialogue_trace_ref,
                last_message_preview,last_message_at,started_at,completed_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                requested_title,
                "draft",
                "workspace_init",
                1,
                "{}",
                _json_dumps(list(ROLE_CREATION_ALL_FIELDS[:-1])),
                "",
                "",
                "",
                "",
                "pending",
                "",
                str(dialogue_agent.get("agent_name") or "").strip(),
                str(dialogue_agent.get("workspace_path") or "").strip(),
                str(dialogue_agent.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip(),
                "",
                "",
                "",
                "",
                "",
                now_text,
                now_text,
            ),
        )
        _append_message(
            conn,
            session_id=session_id,
            role="assistant",
            content=(
                "先和我描述你想创建的角色。"
                "你可以直接发目标、能力、边界、适用场景，也可以把图片和文字一起发进同一条消息。"
            ),
            attachments=[],
            message_type="chat",
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    append_training_center_audit(
        cfg.root,
        action="role_creation_session_created",
        operator=str(body.get("operator") or "web-user"),
        target_id=session_id,
        detail={
            "session_id": session_id,
            "session_title": requested_title,
            "dialogue_agent_name": str(dialogue_agent.get("agent_name") or "").strip(),
            "dialogue_agent_workspace_path": str(dialogue_agent.get("workspace_path") or "").strip(),
            "dialogue_provider": str(dialogue_agent.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip(),
        },
    )
    return get_role_creation_session_detail(cfg.root, session_id)


def post_role_creation_message(cfg: Any, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_key = safe_token(str(session_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    role = _normalize_text(body.get("role") or "user", max_len=20).lower() or "user"
    if role not in {"user", "assistant", "system"}:
        role = "user"
    content = _normalize_text(body.get("content"), max_len=4000)
    attachments = _normalize_message_attachments(body.get("attachments"))
    if not content and not attachments:
        raise TrainingCenterError(400, "消息内容不能为空", "role_creation_message_empty")
    operator = str(body.get("operator") or "web-user")
    client_message_id = safe_token(body.get("client_message_id"), "", 120)
    user_message: dict[str, Any] = {}
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        _row, session_summary, _messages, _task_refs, _role_spec_existing, _missing_existing = _load_session_context(conn, session_key)
        if _normalize_session_status(session_summary.get("status")) == "completed":
            raise TrainingCenterError(409, "当前角色创建已完成，不能继续追加消息", "role_creation_session_completed")
        user_message = _append_message(
            conn,
            session_id=session_key,
            role=role,
            content=content,
            attachments=attachments,
            message_type="chat",
            meta={
                "client_message_id": client_message_id,
                "processing_state": "pending" if role == "user" else "processed",
            },
        )
        messages = _list_session_messages(conn, session_key)
        _update_session_role_spec(
            conn,
            session_id=session_key,
            session_summary=session_summary,
            messages=messages,
        )
        if role == "user":
            _update_role_creation_message_queue_state(
                conn,
                session_id=session_key,
                queue_status="pending",
                queue_error="",
                updated_at=str(user_message.get("created_at") or "").strip() or _tc_now_text(),
                messages=messages,
            )
        conn.commit()
    finally:
        conn.close()
    worker_started = False
    if role == "user":
        worker_started = _ensure_role_creation_message_worker(
            cfg,
            session_id=session_key,
            operator=operator,
        )
    append_training_center_audit(
        cfg.root,
        action="role_creation_message_posted",
        operator=operator,
        target_id=session_key,
        detail={
            "message_role": role,
            "content_preview": _message_preview(content, attachments),
            "attachment_count": len(attachments),
            "user_message_id": str(user_message.get("message_id") or "").strip(),
            "client_message_id": client_message_id,
            "queued_for_processing": role == "user",
            "worker_started": worker_started,
        },
    )
    return get_role_creation_session_detail(cfg.root, session_key)


def retry_role_creation_session_analysis(cfg: Any, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_key = safe_token(str(session_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    operator = str(body.get("operator") or "web-user")
    current_detail = get_role_creation_session_detail(cfg.root, session_key)
    session_summary = dict(current_detail.get("session") or {})
    queue_status = _normalize_role_creation_queue_state(
        session_summary.get("message_processing_status"),
        default="idle",
    )
    if queue_status in {"pending", "running"}:
        return current_detail
    if _normalize_session_status(session_summary.get("status")) == "completed":
        raise TrainingCenterError(
            409,
            "当前角色创建已完成，不能再重试本轮分析",
            "role_creation_session_completed",
            {"session_id": session_key},
        )
    now_text = _tc_now_text()
    retry_message_ids: list[str] = []
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        _fetch_session_row(conn, session_key)
        messages = _list_session_messages(conn, session_key)
        retry_message_ids = [
            str(message.get("message_id") or "").strip()
            for message in list(messages or [])
            if str(message.get("role") or "").strip().lower() == "user"
            and _normalize_message_type(message.get("message_type")) == "chat"
            and _normalize_role_creation_user_message_state(
                message.get("processing_state") or (message.get("meta") or {}).get("processing_state"),
                default="processed",
            ) in {"failed", "pending"}
        ]
        if not retry_message_ids:
            raise TrainingCenterError(
                409,
                "当前没有失败或待处理消息可重试",
                "role_creation_retry_no_pending_messages",
                {
                    "session_id": session_key,
                    "message_processing_status": queue_status,
                    "unhandled_user_message_count": int(session_summary.get("unhandled_user_message_count") or 0),
                },
            )
        _update_role_creation_user_message_processing_state(
            conn,
            session_id=session_key,
            message_ids=retry_message_ids,
            processing_state="pending",
        )
        updated_messages = _list_session_messages(conn, session_key)
        _update_role_creation_message_queue_state(
            conn,
            session_id=session_key,
            queue_status="pending",
            queue_error="",
            batch_id="",
            updated_at=now_text,
            messages=updated_messages,
        )
        _append_message(
            conn,
            session_id=session_key,
            role="system",
            content="已手动触发本轮分析重试。",
            attachments=[],
            message_type="system_task_update",
            meta={
                "retry_analysis": True,
                "retry_message_ids": list(retry_message_ids),
            },
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    worker_started = _ensure_role_creation_message_worker(
        cfg,
        session_id=session_key,
        operator=operator,
    )
    append_training_center_audit(
        cfg.root,
        action="role_creation_analysis_retry_requested",
        operator=operator,
        target_id=session_key,
        detail={
            "session_id": session_key,
            "retry_message_ids": list(retry_message_ids),
            "worker_started": bool(worker_started),
        },
    )
    detail = get_role_creation_session_detail(cfg.root, session_key)
    detail["retry_requested"] = {
        "message_count": len(retry_message_ids),
        "worker_started": bool(worker_started),
        "requested_at": now_text,
    }
    return detail


def start_role_creation_session(cfg: Any, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_key = safe_token(str(session_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    operator = str(body.get("operator") or "web-user")
    current_detail = get_role_creation_session_detail(cfg.root, session_key)
    session_summary = dict(current_detail.get("session") or {})
    role_spec = dict(current_detail.get("role_spec") or {})
    missing_fields = list((current_detail.get("profile") or {}).get("missing_fields") or [])
    start_gate = dict(role_spec.get("start_gate") or {})
    status = _normalize_session_status(session_summary.get("status"))
    if status == "completed":
        raise TrainingCenterError(409, "当前角色创建已完成，不能再次启动", "role_creation_session_completed")
    if status == "creating" and str(session_summary.get("assignment_ticket_id") or "").strip():
        return current_detail
    if _role_creation_session_has_unhandled_messages(session_summary):
        raise TrainingCenterError(
            409,
            "当前还有未处理的对话消息，请等待分析完成后再开始创建",
            "role_creation_messages_unhandled",
            {
                "message_processing_status": str(session_summary.get("message_processing_status") or "").strip(),
                "unhandled_user_message_count": int(session_summary.get("unhandled_user_message_count") or 0),
            },
        )
    if not _session_can_start(role_spec):
        raise TrainingCenterError(
            409,
            "当前草案信息不足，不能开始创建",
            "role_creation_spec_incomplete",
            {
                "missing_fields": missing_fields,
                "missing_labels": _missing_field_labels(missing_fields),
                "start_gate_blockers": [str(item).strip() for item in list(start_gate.get("blockers") or []) if str(item).strip()],
            },
        )
    dialogue_agent = _resolve_role_creation_dialogue_agent(cfg)
    workspace_result = _initialize_role_workspace(
        cfg,
        session_summary=session_summary,
        role_spec=role_spec,
    )
    _upsert_created_agent_registry_row(
        cfg.root,
        agent_id=str(workspace_result.get("created_agent_id") or "").strip(),
        agent_name=str(workspace_result.get("created_agent_name") or "").strip(),
        workspace_path=str(workspace_result.get("workspace_path") or "").strip(),
        role_spec=role_spec,
        runtime_status="creating",
    )
    starter_nodes = _starter_task_blueprint(
        role_spec,
        agent_id=str(workspace_result.get("created_agent_id") or "").strip(),
        agent_name=str(workspace_result.get("created_agent_name") or "").strip(),
    )
    created_starter_nodes: list[dict[str, Any]] = []
    try:
        ticket_id = _ensure_role_creation_assignment_graph(cfg, operator=operator)
        created_starter_nodes = _create_role_creation_assignment_nodes(
            cfg,
            ticket_id=ticket_id,
            starter_nodes=starter_nodes,
            operator=operator,
        )
    except Exception as exc:
        _raise_role_creation_assignment_error(exc, "role_creation_start_graph_failed")
    if not ticket_id:
        raise TrainingCenterError(500, "映射任务中心主图失败", "role_creation_start_graph_missing_ticket")
    now_text = _tc_now_text()
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        _fetch_session_row(conn, session_key)
        _insert_task_refs(
            conn,
            session_id=session_key,
            ticket_id=ticket_id,
            starter_nodes=starter_nodes,
            created_at=now_text,
        )
        conn.execute(
            """
            UPDATE role_creation_sessions
            SET status='creating',current_stage_key='persona_collection',current_stage_index=2,
                role_spec_json=?,missing_fields_json=?,assignment_ticket_id=?,created_agent_id=?,created_agent_name=?,
                created_agent_workspace_path=?,workspace_init_status=?,workspace_init_ref=?,dialogue_agent_name=?,
                dialogue_agent_workspace_path=?,dialogue_provider=?,started_at=?,updated_at=?
            WHERE session_id=?
            """,
            (
                _json_dumps(role_spec),
                _json_dumps(missing_fields),
                ticket_id,
                str(workspace_result.get("created_agent_id") or "").strip(),
                str(workspace_result.get("created_agent_name") or "").strip(),
                str(workspace_result.get("workspace_path") or "").strip(),
                str(workspace_result.get("workspace_init_status") or "completed").strip(),
                str(workspace_result.get("workspace_init_ref") or "").strip(),
                str(dialogue_agent.get("agent_name") or "").strip(),
                str(dialogue_agent.get("workspace_path") or "").strip(),
                str(dialogue_agent.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip(),
                now_text,
                now_text,
                session_key,
            ),
        )
        _append_message(
            conn,
            session_id=session_key,
            role="system",
            content="阶段 1 已完成：真实角色工作区与记忆骨架初始化完成。",
            attachments=[],
            message_type="system_stage_update",
            meta={
                "stage_key": "workspace_init",
                "workspace_init_ref": str(workspace_result.get("workspace_init_ref") or "").strip(),
                "workspace_path": str(workspace_result.get("workspace_path") or "").strip(),
            },
            created_at=now_text,
        )
        _append_message(
            conn,
            session_id=session_key,
            role="system",
            content="已进入角色画像收集，并映射到任务中心全局主图。",
            attachments=[],
            message_type="system_task_update",
            meta={
                "stage_key": "persona_collection",
                "assignment_ticket_id": ticket_id,
                "task_ids": [str(item.get("node_id") or "").strip() for item in starter_nodes],
            },
            created_at=now_text,
        )
        _append_message(
            conn,
            session_id=session_key,
            role="assistant",
            content="创建流程已启动。我会继续在当前会话里收口画像，并把后台任务推进情况同步回你。",
            attachments=[],
            message_type="chat",
            created_at=now_text,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        for item in reversed(created_starter_nodes):
            node_id = str(item.get("node_id") or "").strip()
            if not node_id:
                continue
            try:
                assignment_service.delete_assignment_node(
                    cfg.root,
                    ticket_id_text=ticket_id,
                    node_id_text=node_id,
                    operator=operator,
                    reason="rollback role creation starter nodes",
                    include_test_data=True,
                )
            except Exception:
                pass
        raise
    finally:
        conn.close()
    append_training_center_audit(
        cfg.root,
        action="role_creation_started",
        operator=operator,
        target_id=session_key,
        detail={
            "session_id": session_key,
            "assignment_ticket_id": ticket_id,
            "created_agent_id": str(workspace_result.get("created_agent_id") or "").strip(),
            "workspace_init_ref": str(workspace_result.get("workspace_init_ref") or "").strip(),
            "dialogue_agent_name": str(dialogue_agent.get("agent_name") or "").strip(),
            "dialogue_agent_workspace_path": str(dialogue_agent.get("workspace_path") or "").strip(),
        },
    )
    _resume_role_creation_scheduler(
        cfg,
        session_id=session_key,
        ticket_id=ticket_id,
        operator=operator,
    )
    return get_role_creation_session_detail(cfg.root, session_key)


def update_role_creation_session_stage(cfg: Any, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_key = safe_token(str(session_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    stage_key = _normalize_stage_key(body.get("stage_key"))
    if stage_key == "complete_creation":
        raise TrainingCenterError(409, "完成角色创建请走独立完成接口", "role_creation_complete_stage_locked")
    operator = str(body.get("operator") or "web-user")
    reason = _normalize_text(body.get("reason") or body.get("note"), max_len=500)
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        _row, session_summary, messages, _task_refs, _role_spec, _missing_fields = _load_session_context(conn, session_key)
        status = _normalize_session_status(session_summary.get("status"))
        if status == "completed":
            raise TrainingCenterError(409, "当前角色创建已完成，不能切换阶段", "role_creation_session_completed")
        if status != "creating":
            raise TrainingCenterError(409, "当前角色还未开始创建，不能切换阶段", "role_creation_not_started")
        stage_index = int((ROLE_CREATION_STAGE_BY_KEY.get(stage_key) or {}).get("index") or 0)
        conn.execute(
            """
            UPDATE role_creation_sessions
            SET current_stage_key=?,current_stage_index=?,updated_at=?
            WHERE session_id=?
            """,
            (stage_key, stage_index, _tc_now_text(), session_key),
        )
        _append_message(
            conn,
            session_id=session_key,
            role="system",
            content=_role_creation_stage_update_text(stage_key),
            attachments=[],
            message_type="system_stage_update",
            meta={"stage_key": stage_key, "reason": reason},
        )
        role_spec, _missing_fields, _title = _update_session_role_spec(
            conn,
            session_id=session_key,
            session_summary={**session_summary, "current_stage_key": stage_key, "current_stage_index": stage_index},
            messages=messages,
        )
        if str(session_summary.get("created_agent_workspace_path") or "").strip():
            _sync_workspace_profile(cfg.root, session_summary, role_spec)
        conn.commit()
    finally:
        conn.close()
    append_training_center_audit(
        cfg.root,
        action="role_creation_stage_updated",
        operator=operator,
        target_id=session_key,
        detail={"stage_key": stage_key, "reason": reason},
    )
    return get_role_creation_session_detail(cfg.root, session_key)


def create_role_creation_task(cfg: Any, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_key = safe_token(str(session_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    detail = get_role_creation_session_detail(cfg.root, session_key)
    session_summary = dict(detail.get("session") or {})
    task_refs = list(detail.get("task_refs") or [])
    if _normalize_session_status(session_summary.get("status")) != "creating":
        raise TrainingCenterError(409, "当前角色还未进入创建流程", "role_creation_not_started")
    stage_key = _normalize_stage_key(
        body.get("stage_key")
        or _infer_task_stage_key(
            str(body.get("node_goal") or body.get("goal") or body.get("content") or ""),
            str(session_summary.get("current_stage_key") or "persona_collection"),
        )
    )
    node_name = _normalize_text(
        body.get("node_name") or body.get("task_name") or body.get("title"),
        max_len=200,
    )
    node_goal = _normalize_text(
        body.get("node_goal") or body.get("goal") or body.get("content"),
        max_len=4000,
    )
    if not node_name and node_goal:
        node_name = _delegate_task_title(node_goal, str(session_summary.get("session_title") or ""))
    expected_artifact = _normalize_text(
        body.get("expected_artifact"),
        max_len=240,
    ) or _role_creation_default_artifact_name(stage_key, node_name)
    operator = str(body.get("operator") or "web-user")
    created_task = _create_role_creation_task_internal(
        cfg,
        session_summary=session_summary,
        task_refs=task_refs,
        stage_key=stage_key,
        node_name=node_name,
        node_goal=node_goal,
        expected_artifact=expected_artifact,
        operator=operator,
        priority=str(body.get("priority") or "").strip(),
    )
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        _append_message(
            conn,
            session_id=session_key,
            role="system",
            content="已新建后台任务：" + str(created_task.get("task_name") or "").strip(),
            attachments=[],
            message_type="system_task_update",
            meta={"created_task": created_task, "stage_key": stage_key},
        )
        conn.commit()
    finally:
        conn.close()
    append_training_center_audit(
        cfg.root,
        action="role_creation_task_created",
        operator=operator,
        target_id=session_key,
        detail=created_task,
    )
    updated = get_role_creation_session_detail(cfg.root, session_key)
    created_task_payload = dict(created_task)
    for key, value in _role_creation_current_task_ref_payload(
        updated,
        node_id=str(created_task.get("node_id") or "").strip(),
    ).items():
        if key not in created_task_payload or value not in ("", [], {}, None):
            created_task_payload[key] = value
    return {
        **updated,
        "created_task": created_task_payload,
    }


def archive_role_creation_task(cfg: Any, session_id: str, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_key = safe_token(str(session_id or ""), "", 160)
    node_key = safe_token(str(node_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    if not node_key:
        raise TrainingCenterError(400, "node_id required", "role_creation_node_id_required")
    operator = str(body.get("operator") or "web-user")
    close_reason = _normalize_text(body.get("close_reason") or body.get("reason"), max_len=500)
    if not close_reason:
        raise TrainingCenterError(400, "归档原因不能为空", "role_creation_archive_reason_required")
    detail = get_role_creation_session_detail(cfg.root, session_key)
    ref_row = next(
        (item for item in list(detail.get("task_refs") or []) if str(item.get("node_id") or "").strip() == node_key),
        {},
    )
    if not ref_row:
        raise TrainingCenterError(404, "任务引用不存在", "role_creation_task_ref_not_found")
    task_payload = _role_creation_current_task_ref_payload(detail, node_id=node_key)
    if str(task_payload.get("status") or "").strip().lower() == "running":
        raise TrainingCenterError(409, "运行中的任务不能直接归档", "role_creation_archive_running_task_blocked")
    now_text = _tc_now_text()
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE role_creation_task_refs
            SET relation_state='archived',close_reason=?,updated_at=?
            WHERE session_id=? AND node_id=?
            """,
            (close_reason, now_text, session_key, node_key),
        )
        _append_message(
            conn,
            session_id=session_key,
            role="system",
            content="已把后台任务收口到废案收纳：" + str(task_payload.get("task_name") or node_key).strip(),
            attachments=[],
            message_type="system_task_update",
            meta={"node_id": node_key, "close_reason": close_reason, "relation_state": "archived"},
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    append_training_center_audit(
        cfg.root,
        action="role_creation_task_archived",
        operator=operator,
        target_id=session_key,
        detail={"node_id": node_key, "close_reason": close_reason},
    )
    updated = get_role_creation_session_detail(cfg.root, session_key)
    return {
        **updated,
        "archived_task": _role_creation_current_task_ref_payload(updated, node_id=node_key),
    }


def delete_role_creation_session(cfg: Any, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_key = safe_token(str(session_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    operator = str(body.get("operator") or "web-user")
    detail = get_role_creation_session_detail(cfg.root, session_key)
    session_summary = dict(detail.get("session") or {})
    session_status = _normalize_session_status(session_summary.get("status"))
    delete_state = _role_creation_delete_state(cfg.root, session_summary)
    if not bool(delete_state.get("delete_available")):
        delete_block_reason = str(delete_state.get("delete_block_reason") or "").strip()
        if delete_block_reason == "message_processing_active":
            raise TrainingCenterError(
                409,
                "当前对话仍在分析中，暂不支持删除，请等待处理完成后再删除",
                "role_creation_delete_processing_blocked",
                {
                    "message_processing_status": str(session_summary.get("message_processing_status") or "").strip(),
                    "unhandled_user_message_count": int(session_summary.get("unhandled_user_message_count") or 0),
                },
            )
        if session_status == "creating" and delete_block_reason == "assignment_running_nodes":
            raise TrainingCenterError(
                409,
                str(delete_state.get("delete_block_reason_text") or "当前任务中心仍有运行中的任务，暂不支持清理删除"),
                "role_creation_delete_running_tasks_blocked",
                {
                    "assignment_ticket_id": str(session_summary.get("assignment_ticket_id") or "").strip(),
                    "created_agent_name": str(session_summary.get("created_agent_name") or "").strip(),
                    "assignment_running_node_count": int(delete_state.get("assignment_running_node_count") or 0),
                    "assignment_scheduler_state": str(delete_state.get("assignment_scheduler_state") or "").strip(),
                    "assignment_scheduler_state_text": str(delete_state.get("assignment_scheduler_state_text") or "").strip(),
                },
            )
        if session_status == "creating":
            raise TrainingCenterError(
                409,
                str(delete_state.get("delete_block_reason_text") or "当前角色正在创建中，暂不支持删除"),
                "role_creation_delete_creating_blocked",
                {
                    "assignment_ticket_id": str(session_summary.get("assignment_ticket_id") or "").strip(),
                    "created_agent_name": str(session_summary.get("created_agent_name") or "").strip(),
                },
            )
        raise TrainingCenterError(
            409,
            str(delete_state.get("delete_block_reason_text") or "当前状态不支持删除"),
            "role_creation_delete_blocked",
            {"status": session_status},
        )
    cleanup_result: dict[str, Any] = {}
    if session_status == "creating":
        cleanup_result = _cleanup_role_creation_session_assets(
            cfg,
            session_summary=session_summary,
            task_refs=list(detail.get("task_refs") or []),
        )
    deleted_payload = dict(session_summary)
    deleted_message_count = len(list(detail.get("messages") or []))
    deleted_task_ref_count = len(list(detail.get("task_refs") or []))
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM role_creation_messages WHERE session_id=?", (session_key,))
        conn.execute("DELETE FROM role_creation_task_refs WHERE session_id=?", (session_key,))
        conn.execute("DELETE FROM role_creation_sessions WHERE session_id=?", (session_key,))
        conn.commit()
    finally:
        conn.close()
    append_training_center_audit(
        cfg.root,
        action="role_creation_session_deleted",
        operator=operator,
        target_id=session_key,
        detail={
            "session_id": session_key,
            "session_title": str(session_summary.get("session_title") or "").strip(),
            "status": session_status,
            "assignment_ticket_id": str(session_summary.get("assignment_ticket_id") or "").strip(),
            "created_agent_id": str(session_summary.get("created_agent_id") or "").strip(),
            "deleted_message_count": deleted_message_count,
            "deleted_task_ref_count": deleted_task_ref_count,
            "cleanup_result": cleanup_result,
        },
    )
    return {
        "deleted_session": deleted_payload,
        "deleted_message_count": deleted_message_count,
        "deleted_task_ref_count": deleted_task_ref_count,
        "cleanup_result": cleanup_result,
    }


def _cleanup_role_creation_session_assets(
    cfg: Any,
    *,
    session_summary: dict[str, Any],
    task_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cleanup_result: dict[str, Any] = {
        "mode": "creating_cleanup",
        "assignment_ticket_id": str(session_summary.get("assignment_ticket_id") or "").strip(),
        "created_agent_id": str(session_summary.get("created_agent_id") or "").strip(),
        "created_agent_workspace_path": str(session_summary.get("created_agent_workspace_path") or "").strip(),
    }
    ticket_id = str(session_summary.get("assignment_ticket_id") or "").strip()
    if ticket_id:
        removed_node_ids: list[str] = []
        missing_node_ids: list[str] = []
        task_node_ids: list[str] = []
        seen_node_ids: set[str] = set()
        for item in list(task_refs or []):
            node_id = str(item.get("node_id") or "").strip()
            if not node_id or node_id in seen_node_ids:
                continue
            seen_node_ids.add(node_id)
            task_node_ids.append(node_id)
        for node_id in task_node_ids:
            try:
                assignment_service.delete_assignment_node(
                    cfg.root,
                    ticket_id_text=ticket_id,
                    node_id_text=node_id,
                    operator="training-center",
                    reason="cleanup role creation session nodes",
                    include_test_data=True,
                )
                removed_node_ids.append(node_id)
            except Exception as exc:
                code = str(getattr(exc, "code", "") or "").strip()
                if code in {"assignment_node_not_found", "assignment_graph_not_found"}:
                    missing_node_ids.append(node_id)
                    continue
                if code == "assignment_delete_running_node_blocked":
                    raise TrainingCenterError(
                        409,
                        "当前角色创建在任务中心主图中仍有运行中的任务，暂不支持清理删除",
                        "role_creation_cleanup_assignment_running",
                        {"ticket_id": ticket_id, "node_id": node_id},
                    ) from exc
                raise TrainingCenterError(
                    500,
                    f"清理关联任务节点失败: {exc}",
                    "role_creation_cleanup_assignment_remove_failed",
                    {"ticket_id": ticket_id, "node_id": node_id},
                ) from exc
        cleanup_result["assignment_cleanup"] = {
            "ticket_id": ticket_id,
            "removed_node_ids": removed_node_ids,
            "missing_node_ids": missing_node_ids,
            "removed_node_count": len(removed_node_ids),
            "requested_node_count": len(task_node_ids),
        }
    workspace_path_text = str(session_summary.get("created_agent_workspace_path") or "").strip()
    if workspace_path_text:
        workspace_path = Path(workspace_path_text).resolve(strict=False)
        search_root_text = str(getattr(cfg, "agent_search_root", "") or "").strip()
        if search_root_text:
            search_root = Path(search_root_text).resolve(strict=False)
            if not path_in_scope(workspace_path, search_root):
                raise TrainingCenterError(
                    409,
                    "角色工作区超出允许清理范围",
                    "role_creation_cleanup_workspace_out_of_scope",
                    {"workspace_path": workspace_path.as_posix()},
                )
        if workspace_path.exists():
            if not workspace_path.is_dir():
                raise TrainingCenterError(
                    409,
                    "角色工作区路径不是目录，不能执行清理",
                    "role_creation_cleanup_workspace_invalid",
                    {"workspace_path": workspace_path.as_posix()},
                )
            try:
                shutil.rmtree(workspace_path)
            except Exception as exc:
                raise TrainingCenterError(
                    500,
                    f"清理角色工作区失败: {exc}",
                    "role_creation_cleanup_workspace_remove_failed",
                    {"workspace_path": workspace_path.as_posix()},
                ) from exc
        cleanup_result["workspace_cleanup"] = {
            "workspace_path": workspace_path.as_posix(),
            "removed": not workspace_path.exists(),
        }
    agent_id = str(session_summary.get("created_agent_id") or "").strip()
    if agent_id:
        conn = connect_db(cfg.root)
        try:
            conn.execute("BEGIN")
            registry_removed = int(conn.execute("DELETE FROM agent_registry WHERE agent_id=?", (agent_id,)).rowcount or 0)
            review_removed = int(conn.execute("DELETE FROM agent_release_review WHERE agent_id=?", (agent_id,)).rowcount or 0)
            history_removed = int(conn.execute("DELETE FROM agent_release_history WHERE agent_id=?", (agent_id,)).rowcount or 0)
            conn.commit()
        finally:
            conn.close()
        cleanup_result["agent_registry_cleanup"] = {
            "agent_id": agent_id,
            "agent_registry_removed": registry_removed,
            "agent_release_review_removed": review_removed,
            "agent_release_history_removed": history_removed,
        }
    return cleanup_result


def complete_role_creation_session(cfg: Any, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_role_creation_tables(cfg.root)
    session_key = safe_token(str(session_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    confirmed = _parse_bool_flag(
        body.get("confirmed")
        if "confirmed" in body
        else body.get("acceptance_confirmed"),
        default=False,
    )
    if not confirmed:
        raise TrainingCenterError(409, "必须在用户明确确认后才能完成角色创建", "role_creation_confirmation_required")
    operator = str(body.get("operator") or "web-user")
    acceptance_note = _normalize_text(body.get("acceptance_note") or body.get("note"), max_len=500)
    detail = get_role_creation_session_detail(cfg.root, session_key)
    session_summary = dict(detail.get("session") or {})
    role_spec = dict(detail.get("role_spec") or {})
    if _normalize_session_status(session_summary.get("status")) != "creating":
        raise TrainingCenterError(409, "当前角色不在创建中，不能完成创建", "role_creation_not_started")
    if _role_creation_session_has_unhandled_messages(session_summary):
        raise TrainingCenterError(
            409,
            "当前还有未处理的对话消息，请等待分析完成后再确认完成",
            "role_creation_messages_unhandled",
            {
                "message_processing_status": str(session_summary.get("message_processing_status") or "").strip(),
                "unhandled_user_message_count": int(session_summary.get("unhandled_user_message_count") or 0),
            },
        )
    unresolved_tasks = []
    for stage in list(detail.get("stages") or []):
        for task in list(stage.get("active_tasks") or []):
            if str(task.get("status") or "").strip().lower() != "succeeded":
                unresolved_tasks.append(
                    {
                        "node_id": str(task.get("node_id") or "").strip(),
                        "task_name": str(task.get("task_name") or "").strip(),
                        "status": str(task.get("status") or "").strip().lower(),
                        "status_text": str(task.get("status_text") or "").strip(),
                    }
                )
    if unresolved_tasks:
        raise TrainingCenterError(
            409,
            "仍有未完成的后台任务，不能完成角色创建",
            "role_creation_tasks_incomplete",
            {"unresolved_tasks": unresolved_tasks[:12]},
        )
    now_text = _tc_now_text()
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE role_creation_sessions
            SET status='completed',current_stage_key='complete_creation',current_stage_index=6,
                role_spec_json=?,missing_fields_json=?,completed_at=?,updated_at=?
            WHERE session_id=?
            """,
            (
                _json_dumps(role_spec),
                _json_dumps([]),
                now_text,
                now_text,
                session_key,
            ),
        )
        _append_message(
            conn,
            session_id=session_key,
            role="system",
            content="用户已确认通过验收，角色创建完成。",
            attachments=[],
            message_type="system_result",
            meta={"stage_key": "complete_creation", "acceptance_note": acceptance_note},
            created_at=now_text,
        )
        _append_message(
            conn,
            session_id=session_key,
            role="assistant",
            content="角色创建已完成，后续可以直接进入训练闭环和版本治理。",
            attachments=[],
            message_type="chat",
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    _update_agent_runtime_status(
        cfg.root,
        agent_id=str(session_summary.get("created_agent_id") or "").strip(),
        runtime_status="idle",
    )
    _sync_workspace_profile(cfg.root, session_summary, role_spec)
    append_training_center_audit(
        cfg.root,
        action="role_creation_completed",
        operator=operator,
        target_id=session_key,
        detail={
            "created_agent_id": str(session_summary.get("created_agent_id") or "").strip(),
            "acceptance_note": acceptance_note,
        },
    )
    return get_role_creation_session_detail(cfg.root, session_key)

def _role_creation_session_processing_active(session_summary: dict[str, Any]) -> bool:
    return _normalize_role_creation_queue_state(
        (session_summary or {}).get("message_processing_status"),
        default="idle",
    ) in {"pending", "running"}


def _role_creation_session_has_unhandled_messages(session_summary: dict[str, Any]) -> bool:
    try:
        return int((session_summary or {}).get("unhandled_user_message_count") or 0) > 0
    except Exception:
        return False


def _role_creation_pending_batch_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in list(messages or []):
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        if _normalize_message_type(message.get("message_type")) != "chat":
            continue
        state = _normalize_role_creation_user_message_state(
            message.get("processing_state") or (message.get("meta") or {}).get("processing_state"),
            default="processed",
        )
        if state in {"pending", "failed"}:
            out.append(dict(message))
    return out


def _role_creation_batch_prompt_text(messages: list[dict[str, Any]]) -> str:
    rows = list(messages or [])
    if not rows:
        return ""
    if len(rows) == 1:
        only = dict(rows[0] or {})
        content = _normalize_text(only.get("content"), max_len=4000)
        if content:
            return content
        attachment_count = len(list(only.get("attachments") or []))
        if attachment_count > 0:
            return f"[本轮仅补充图片 {attachment_count} 张]"
        return ""
    parts: list[str] = []
    for index, message in enumerate(rows, start=1):
        item = dict(message or {})
        content = _normalize_text(item.get("content"), max_len=4000)
        attachment_count = len(list(item.get("attachments") or []))
        suffix = f" [附图 {attachment_count} 张]" if attachment_count > 0 else ""
        parts.append(f"{index}. {content or '[仅图片补充]'}{suffix}")
    return "本轮用户连续补充了多条消息，请合并处理：\n" + "\n".join(parts)


def _update_role_creation_user_message_processing_state(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    message_ids: list[str],
    processing_state: str,
    batch_id: str = "",
    error_text: str = "",
    started_at: str = "",
    processed_at: str = "",
    assistant_message_id: str = "",
) -> None:
    ids = [safe_token(message_id, "", 160) for message_id in list(message_ids or [])]
    ids = [message_id for message_id in ids if message_id]
    if not ids:
        return
    state_value = _normalize_role_creation_user_message_state(processing_state, default="processed")
    for message_id in ids:
        row = conn.execute(
            """
            SELECT message_id,meta_json
            FROM role_creation_messages
            WHERE session_id=? AND message_id=?
            LIMIT 1
            """,
            (session_id, message_id),
        ).fetchone()
        if row is None:
            continue
        meta = _json_loads_dict(row["meta_json"])
        meta["processing_state"] = state_value
        if batch_id:
            meta["processing_batch_id"] = batch_id
        elif state_value != "processing":
            meta.pop("processing_batch_id", None)
        if state_value == "pending":
            meta["processing_error"] = ""
            meta.pop("processing_started_at", None)
            meta.pop("processed_at", None)
            meta.pop("assistant_message_id", None)
        elif state_value == "processing":
            meta["processing_error"] = ""
            if started_at:
                meta["processing_started_at"] = started_at
            meta.pop("processed_at", None)
            meta.pop("assistant_message_id", None)
        elif state_value == "processed":
            meta["processing_error"] = ""
            if started_at:
                meta["processing_started_at"] = started_at
            if processed_at:
                meta["processed_at"] = processed_at
            if assistant_message_id:
                meta["assistant_message_id"] = assistant_message_id
        else:
            meta["processing_error"] = _normalize_text(error_text, max_len=2000)
            if started_at:
                meta["processing_started_at"] = started_at
            meta.pop("processed_at", None)
            meta.pop("assistant_message_id", None)
        conn.execute(
            "UPDATE role_creation_messages SET meta_json=? WHERE message_id=?",
            (_json_dumps(meta), message_id),
        )
