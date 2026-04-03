from pathlib import Path

from workflow_app.server.services.codex_failure_contract import (
    build_codex_failure,
    build_retry_action,
    infer_codex_failure_detail_code,
)


ROLE_CREATION_ANALYSIS_STEPS = (
    {
        "step_key": "extract_role_profile",
        "label": "抽取角色画像",
        "description": "识别角色名、目标、核心能力、边界和适用场景。",
    },
    {
        "step_key": "capability_modules",
        "label": "拆解能力模块",
        "description": "整理能力模块、默认交付策略、格式边界和优先场景。",
    },
    {
        "step_key": "knowledge_assets",
        "label": "整理知识资产",
        "description": "归拢方法文档、模板、示例、反例和验收清单。",
    },
    {
        "step_key": "seed_tasks",
        "label": "生成首批任务建议",
        "description": "形成首批能力对象、任务建议和优先顺序。",
    },
)


def _role_creation_trace_refs(root: Path, trace_ref: str) -> dict[str, str]:
    trace_text = str(trace_ref or "").strip()
    if not trace_text:
        return {}
    refs = {"trace_dir": trace_text}
    trace_dir = Path(trace_text)
    if not trace_dir.is_absolute():
        trace_dir = (Path(root).resolve(strict=False) / trace_text).resolve(strict=False)
    if not trace_dir.exists() or not trace_dir.is_dir():
        return refs
    runtime_root = Path(root).resolve(strict=False)
    for file_name, label in (
        ("prompt.txt", "prompt"),
        ("stdout.txt", "stdout"),
        ("stderr.txt", "stderr"),
        ("result.json", "result"),
    ):
        file_path = trace_dir / file_name
        if not file_path.exists() or not file_path.is_file():
            continue
        refs[label] = relative_to_root(runtime_root, file_path.resolve(strict=False))
    return refs


def _role_creation_session_codex_failure(
    root: Path,
    *,
    session_summary: dict[str, Any],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    queue_status = str(session_summary.get("message_processing_status") or "").strip().lower()
    if queue_status != "failed":
        return {}
    trace_ref = str(session_summary.get("last_dialogue_trace_ref") or "").strip()
    detail_code = ""
    fallback_message = str(session_summary.get("message_processing_error") or "").strip()
    attempt_keys: list[str] = []
    failed_at = str(session_summary.get("message_processing_updated_at") or "").strip()
    for message in reversed(list(messages or [])):
        meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
        message_trace_ref = str(meta.get("trace_ref") or "").strip()
        if message_trace_ref and not trace_ref:
            trace_ref = message_trace_ref
        if message_trace_ref:
            attempt_keys.append(message_trace_ref)
        batch_id = str(meta.get("processing_batch_id") or message.get("processing_batch_id") or "").strip()
        if batch_id:
            attempt_keys.append(batch_id)
        dialogue_error = str(meta.get("dialogue_error") or "").strip().lower()
        if dialogue_error and not detail_code:
            detail_code = dialogue_error
        processing_error = str(meta.get("processing_error") or "").strip()
        if processing_error and not fallback_message:
            fallback_message = processing_error
        if str(message.get("created_at") or "").strip() and not failed_at:
            failed_at = str(message.get("created_at") or "").strip()
    if not detail_code:
        detail_code = infer_codex_failure_detail_code(
            fallback_message,
            fallback="role_creation_analysis_failed",
        )
    if not detail_code:
        return {}
    attempt_count = len({str(item or "").strip() for item in attempt_keys if str(item or "").strip()})
    return build_codex_failure(
        feature_key="role_creation_analysis",
        attempt_id=str(session_summary.get("message_processing_batch_id") or trace_ref or session_summary.get("session_id") or "").strip(),
        attempt_count=max(1, int(attempt_count or 0)),
        failure_detail_code=detail_code,
        failure_message=fallback_message,
        retry_action=build_retry_action(
            "retry_role_creation_analysis",
            payload={"session_id": str(session_summary.get("session_id") or "").strip()},
        ),
        trace_refs=_role_creation_trace_refs(root, trace_ref),
        failed_at=failed_at,
    )


def _role_creation_structured_specs(role_spec: dict[str, Any]) -> dict[str, Any]:
    spec = dict(role_spec or {})
    return {
        "role_profile_spec": dict(spec.get("role_profile_spec") or {}),
        "capability_package_spec": dict(spec.get("capability_package_spec") or {}),
        "knowledge_asset_plan": dict(spec.get("knowledge_asset_plan") or {}),
        "seed_delivery_plan": dict(spec.get("seed_delivery_plan") or {}),
    }


def _role_creation_analysis_progress(role_spec: dict[str, Any], session_summary: dict[str, Any]) -> dict[str, Any]:
    role_profile_spec = dict((role_spec or {}).get("role_profile_spec") or {})
    capability_package_spec = dict((role_spec or {}).get("capability_package_spec") or {})
    knowledge_asset_plan = dict((role_spec or {}).get("knowledge_asset_plan") or {})
    seed_delivery_plan = dict((role_spec or {}).get("seed_delivery_plan") or {})
    queue_status = _normalize_role_creation_queue_state(
        (session_summary or {}).get("message_processing_status"),
        default="idle",
    )
    completed_map = {
        "extract_role_profile": int(role_profile_spec.get("current_value_count") or 0) >= 1,
        "capability_modules": bool(list(capability_package_spec.get("capability_modules") or []))
        or bool((capability_package_spec.get("default_delivery_policy") or {}).get("summary"))
        or bool((capability_package_spec.get("format_strategy") or {}).get("summary"))
        or bool(list((capability_package_spec.get("format_strategy") or {}).get("allowed_formats") or [])),
        "knowledge_assets": bool(list(knowledge_asset_plan.get("assets") or [])),
        "seed_tasks": bool(list(seed_delivery_plan.get("capability_objects") or []))
        or bool(list(seed_delivery_plan.get("task_suggestions") or [])),
    }
    first_incomplete_key = ""
    completed_count = 0
    steps: list[dict[str, Any]] = []
    for step in ROLE_CREATION_ANALYSIS_STEPS:
        step_key = str(step["step_key"])
        is_completed = bool(completed_map.get(step_key))
        if is_completed:
            completed_count += 1
        elif not first_incomplete_key:
            first_incomplete_key = step_key
        steps.append(
            {
                "step_key": step_key,
                "label": str(step["label"]),
                "description": str(step["description"]),
                "state": "completed" if is_completed else "pending",
                "completed": is_completed,
            }
        )
    current_step_key = first_incomplete_key or str(ROLE_CREATION_ANALYSIS_STEPS[-1]["step_key"])
    current_step_label = next(
        (str(step.get("label") or "") for step in steps if str(step.get("step_key") or "") == current_step_key),
        "",
    )
    if queue_status in {"pending", "running", "failed"}:
        for step in steps:
            if str(step.get("step_key") or "") != current_step_key:
                continue
            step["state"] = "failed" if queue_status == "failed" else "current"
            break
    if queue_status == "failed":
        status_text = f"分析失败：{current_step_label or '等待重试'}"
    elif queue_status == "running":
        status_text = f"分析中：{current_step_label or '处理中'}"
    elif queue_status == "pending":
        status_text = f"待分析：{current_step_label or '等待分析'}"
    elif completed_count >= len(ROLE_CREATION_ANALYSIS_STEPS):
        status_text = "结构化草稿已完成"
    elif completed_count > 0:
        status_text = f"已完成 {completed_count}/{len(ROLE_CREATION_ANALYSIS_STEPS)} 个结构步骤"
    else:
        status_text = "等待分析"
    placeholder_text = ""
    if queue_status in {"pending", "running"}:
        placeholder_text = ("正在" if queue_status == "running" else "准备") + (current_step_label or "处理本轮消息") + "…"
    elif queue_status == "failed":
        placeholder_text = (current_step_label or "本轮分析") + "失败，请点击“重试本轮分析”。"
    return {
        "status": queue_status,
        "active": queue_status in {"pending", "running"},
        "failed": queue_status == "failed",
        "status_text": status_text,
        "current_step_key": current_step_key,
        "current_step_label": current_step_label,
        "completed_step_count": completed_count,
        "step_count": len(ROLE_CREATION_ANALYSIS_STEPS),
        "placeholder_text": placeholder_text,
        "steps": steps,
    }


def list_role_creation_sessions(root: Path) -> dict[str, Any]:
    _ensure_role_creation_tables(root)
    conn = connect_db(root)
    try:
        rows = conn.execute(
            "SELECT * FROM role_creation_sessions ORDER BY updated_at DESC,created_at DESC,session_id DESC"
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            summary = _session_row_to_summary(row)
            sync_payload = _role_creation_session_sync_payload(
                row=row,
                session_summary=summary,
                messages=_list_session_messages(conn, summary.get("session_id") or ""),
            )
            if sync_payload["needs_sync"] and summary.get("status") != "completed":
                conn.execute(
                    """
                    UPDATE role_creation_sessions
                    SET session_title=?,role_spec_json=?,missing_fields_json=?,updated_at=?
                    WHERE session_id=?
                    """,
                    (
                        sync_payload["session_title"],
                        _json_dumps(sync_payload["role_spec"]),
                        _json_dumps(sync_payload["missing_fields"]),
                        str(row["updated_at"] or ""),
                        summary.get("session_id") or "",
                    ),
                )
                summary["session_title"] = sync_payload["session_title"]
                summary["missing_fields"] = list(sync_payload["missing_fields"])
            summary["start_gate"] = dict((sync_payload["role_spec"] or {}).get("start_gate") or {})
            summary["analysis_progress"] = _role_creation_analysis_progress(sync_payload["role_spec"], summary)
            if summary["analysis_progress"].get("active") or summary["analysis_progress"].get("failed"):
                summary["message_processing_status_text"] = str(summary["analysis_progress"].get("status_text") or "").strip()
            summary.update(_role_creation_delete_state(root, summary))
            items.append(summary)
        conn.commit()
    finally:
        conn.close()
    return {"items": items, "total": len(items)}


def _role_creation_session_sync_payload(
    *,
    row: sqlite3.Row | dict[str, Any],
    session_summary: dict[str, Any],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    role_spec, missing_fields = _build_role_spec(messages)
    session_title = _role_creation_title_from_spec(role_spec, session_summary.get("session_title") or "")
    needs_sync = (
        _json_dumps(role_spec) != str(row["role_spec_json"] or "{}")
        or _json_dumps(missing_fields) != str(row["missing_fields_json"] or "[]")
        or session_title != session_summary.get("session_title")
    )
    return {
        "role_spec": role_spec,
        "missing_fields": list(missing_fields),
        "session_title": session_title,
        "needs_sync": needs_sync,
    }


def get_role_creation_session_detail(root: Path, session_id: str) -> dict[str, Any]:
    _ensure_role_creation_tables(root)
    session_key = safe_token(str(session_id or ""), "", 160)
    if not session_key:
        raise TrainingCenterError(400, "session_id required", "role_creation_session_id_required")
    conn = connect_db(root)
    try:
        row = _fetch_session_row(conn, session_key)
        session_summary = _session_row_to_summary(row)
        messages = _list_session_messages(conn, session_key)
        task_refs = _list_task_refs(conn, session_key)
    finally:
        conn.close()
    message_counts = _role_creation_user_message_counts(messages)
    queue_status = _normalize_role_creation_queue_state(
        session_summary.get("message_processing_status"),
        default="idle",
    )
    if message_counts["processing"] > 0 and queue_status != "failed":
        queue_status = "running"
    elif message_counts["unhandled"] > 0 and queue_status not in {"running", "failed"}:
        queue_status = "pending"
    elif message_counts["unhandled"] <= 0 and queue_status != "failed":
        queue_status = "idle"
    session_summary["user_message_count"] = int(message_counts["total"] or 0)
    session_summary["unhandled_user_message_count"] = int(message_counts["unhandled"] or 0)
    session_summary["message_processing_status"] = queue_status
    session_summary["message_processing_status_text"] = _role_creation_queue_state_text(queue_status)
    sync_payload = _role_creation_session_sync_payload(
        row=row,
        session_summary=session_summary,
        messages=messages,
    )
    role_spec = dict(sync_payload["role_spec"])
    missing_fields = list(sync_payload["missing_fields"])
    assignment_graph = {}
    assignment_focus_node_ids = [
        str(item.get("node_id") or "").strip()
        for item in list(task_refs or [])
        if str(item.get("node_id") or "").strip()
    ]
    if session_summary.get("assignment_ticket_id"):
        try:
            assignment_graph = assignment_service.get_assignment_graph(
                root,
                session_summary["assignment_ticket_id"],
                active_loaded=400,
                active_batch_size=200,
                history_loaded=400,
                history_batch_size=50,
                include_test_data=True,
                focus_node_ids=assignment_focus_node_ids,
            )
        except Exception:
            assignment_graph = {}
    session_summary.update(
        _role_creation_delete_state(
            root,
            session_summary,
            task_refs=task_refs,
            assignment_graph=assignment_graph,
        )
    )
    stages, stage_meta = _project_stages(session_summary, task_refs=task_refs, assignment_graph=assignment_graph)
    current_stage_key = str(stage_meta.get("current_stage_key") or session_summary.get("current_stage_key") or "workspace_init")
    current_stage_index = int(stage_meta.get("current_stage_index") or session_summary.get("current_stage_index") or 1)
    if sync_payload["needs_sync"] and session_summary.get("status") != "completed":
        conn = connect_db(root)
        try:
            conn.execute(
                """
                UPDATE role_creation_sessions
                SET session_title=?,role_spec_json=?,missing_fields_json=?,updated_at=?
                WHERE session_id=?
                """,
                (
                    sync_payload["session_title"],
                    _json_dumps(role_spec),
                    _json_dumps(missing_fields),
                    str(row["updated_at"] or ""),
                    session_key,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        session_summary["session_title"] = sync_payload["session_title"]
        session_summary["missing_fields"] = list(missing_fields)
    created_agent = _current_agent_runtime_payload(root, session_summary.get("created_agent_id") or "")
    dialogue_agent = {
        "agent_name": str(session_summary.get("dialogue_agent_name") or "").strip(),
        "workspace_path": str(session_summary.get("dialogue_agent_workspace_path") or "").strip(),
        "provider": str(session_summary.get("dialogue_provider") or "").strip(),
        "trace_ref": str(session_summary.get("last_dialogue_trace_ref") or "").strip(),
    }
    structured_specs = _role_creation_structured_specs(role_spec)
    start_gate = dict(role_spec.get("start_gate") or {})
    analysis_progress = _role_creation_analysis_progress(role_spec, session_summary)
    if analysis_progress.get("active") or analysis_progress.get("failed"):
        session_summary["message_processing_status_text"] = str(analysis_progress.get("status_text") or "").strip()
    session_summary["analysis_progress"] = analysis_progress
    session_summary["start_gate"] = start_gate
    codex_failure = _role_creation_session_codex_failure(
        root,
        session_summary=session_summary,
        messages=messages,
    )
    return {
        "session": {
            **session_summary,
            "current_stage_key": current_stage_key,
            "current_stage_index": current_stage_index,
            "current_stage_title": str(stage_meta.get("current_stage_title") or ""),
            "codex_failure": codex_failure,
        },
        "messages": messages,
        "role_spec": role_spec,
        "structured_specs": structured_specs,
        "start_gate": start_gate,
        "analysis_progress": analysis_progress,
        "recent_changes": list(role_spec.get("recent_changes") or []),
        "pending_questions": list(role_spec.get("pending_questions") or []),
        "profile": _role_profile_payload(role_spec, missing_fields, session_summary),
        "stages": stages,
        "stage_meta": stage_meta,
        "task_refs": task_refs,
        "assignment_graph": assignment_graph,
        "created_agent": created_agent,
        "dialogue_agent": dialogue_agent,
        "codex_failure": codex_failure,
    }


def _role_creation_delete_state(
    root: Path,
    session_summary: dict[str, Any],
    *,
    task_refs: list[dict[str, Any]] | None = None,
    assignment_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = _normalize_session_status((session_summary or {}).get("status"))
    out = {
        "delete_available": False,
        "delete_mode": "",
        "delete_label": "",
        "delete_block_reason": "",
        "delete_block_reason_text": "",
        "assignment_running_node_count": 0,
        "assignment_scheduler_state": "",
        "assignment_scheduler_state_text": "",
    }
    if _role_creation_session_processing_active(session_summary):
        out.update(
            {
                "delete_mode": "blocked",
                "delete_block_reason": "message_processing_active",
                "delete_block_reason_text": "当前对话仍在分析中，暂不支持删除",
            }
        )
        return out
    if status == "draft":
        out.update({"delete_available": True, "delete_mode": "draft", "delete_label": "删除草稿"})
        return out
    if status == "completed":
        out.update({"delete_available": True, "delete_mode": "record", "delete_label": "删除记录"})
        return out
    if status != "creating":
        out.update(
            {
                "delete_mode": "blocked",
                "delete_block_reason": "session_status_invalid",
                "delete_block_reason_text": "当前状态不支持删除",
            }
        )
        return out
    out.update({"delete_mode": "cleanup", "delete_label": "清理删除"})
    ticket_id = str((session_summary or {}).get("assignment_ticket_id") or "").strip()
    if not ticket_id:
        out["delete_available"] = True
        return out
    task_ref_rows = [dict(item) for item in list(task_refs or [])]
    if not task_ref_rows:
        session_id = str((session_summary or {}).get("session_id") or "").strip()
        if session_id:
            conn = connect_db(root)
            try:
                task_ref_rows = _list_task_refs(conn, session_id)
            finally:
                conn.close()
    try:
        graph_payload = assignment_graph if isinstance(assignment_graph, dict) and assignment_graph else assignment_service.get_assignment_graph(
            root,
            ticket_id,
            active_loaded=0,
            active_batch_size=24,
            history_loaded=0,
            history_batch_size=12,
            include_test_data=True,
            focus_node_ids=[
                str(item.get("node_id") or "").strip()
                for item in list(task_ref_rows or [])
                if str(item.get("node_id") or "").strip()
            ],
        )
    except Exception as exc:
        code = str(getattr(exc, "code", "") or "").strip()
        if code == "assignment_graph_not_found":
            out["delete_available"] = True
            return out
        out.update(
            {
                "delete_block_reason": "assignment_state_unavailable",
                "delete_block_reason_text": "关联任务图状态读取失败，暂不支持清理删除",
            }
        )
        return out
    graph_overview = dict((graph_payload or {}).get("graph") or {})
    scheduler = dict(graph_overview.get("scheduler") or {})
    node_catalog = {
        str(item.get("node_id") or "").strip(): dict(item)
        for item in list((graph_payload or {}).get("node_catalog") or [])
        if str(item.get("node_id") or "").strip()
    }
    running_node_count = 0
    seen_node_ids: set[str] = set()
    for item in task_ref_rows:
        node_id = str(item.get("node_id") or "").strip()
        if not node_id or node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        if str((node_catalog.get(node_id) or {}).get("status") or "").strip().lower() == "running":
            running_node_count += 1
    out["assignment_running_node_count"] = running_node_count
    out["assignment_scheduler_state"] = str(
        graph_overview.get("scheduler_state") or scheduler.get("state") or ""
    ).strip().lower()
    out["assignment_scheduler_state_text"] = str(
        scheduler.get("state_text") or graph_overview.get("scheduler_state_text") or ""
    ).strip()
    if running_node_count > 0:
        out.update(
            {
                "delete_block_reason": "assignment_running_nodes",
                "delete_block_reason_text": f"当前角色创建在任务中心主图中仍有 {running_node_count} 个运行中的任务，暂不支持清理删除",
            }
        )
        return out
    out["delete_available"] = True
    return out


def _raise_role_creation_assignment_error(exc: BaseException, default_code: str) -> None:
    if isinstance(exc, TrainingCenterError):
        raise exc
    status_code = int(getattr(exc, "status_code", 500) or 500)
    code = str(getattr(exc, "code", default_code) or default_code).strip() or default_code
    extra = dict(getattr(exc, "extra", {}) or {})
    raise TrainingCenterError(status_code, str(exc), code, extra)


def _load_session_context(
    conn: sqlite3.Connection,
    session_id: str,
) -> tuple[sqlite3.Row, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[str]]:
    row = _fetch_session_row(conn, session_id)
    session_summary = _session_row_to_summary(row)
    messages = _list_session_messages(conn, session_id)
    task_refs = _list_task_refs(conn, session_id)
    role_spec, missing_fields = _build_role_spec(messages)
    return row, session_summary, messages, task_refs, role_spec, missing_fields


def _update_session_role_spec(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    session_summary: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str], str]:
    if session_summary is None or messages is None:
        _row, session_summary, messages, _task_refs, _role_spec_unused, _missing_fields_unused = _load_session_context(
            conn,
            session_id,
        )
    role_spec, missing_fields = _build_role_spec(list(messages or []))
    session_title = _role_creation_title_from_spec(role_spec, (session_summary or {}).get("session_title") or "")
    status = _normalize_session_status((session_summary or {}).get("status"))
    current_stage_key = _normalize_stage_key(
        (session_summary or {}).get("current_stage_key") or "workspace_init",
    )
    current_stage_index = int((session_summary or {}).get("current_stage_index") or 1)
    if status == "draft":
        current_stage_key = "workspace_init"
        current_stage_index = 1
    conn.execute(
        """
        UPDATE role_creation_sessions
        SET session_title=?,role_spec_json=?,missing_fields_json=?,current_stage_key=?,current_stage_index=?,updated_at=?
        WHERE session_id=?
        """,
        (
            session_title,
            _json_dumps(role_spec),
            _json_dumps(missing_fields),
            current_stage_key,
            current_stage_index,
            _tc_now_text(),
            session_id,
        ),
    )
    if isinstance(session_summary, dict):
        session_summary["session_title"] = session_title
        session_summary["current_stage_key"] = current_stage_key
        session_summary["current_stage_index"] = current_stage_index
    return role_spec, missing_fields, session_title


def _role_creation_stage_update_text(stage_key: str) -> str:
    stage = dict(ROLE_CREATION_STAGE_BY_KEY.get(stage_key) or {})
    title = str(stage.get("title") or stage_key)
    return f"当前阶段切换为：{title}"


def _role_creation_default_artifact_name(stage_key: str, task_name: str) -> str:
    title = _normalize_text(task_name, max_len=60)
    normalized = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1f]+', "-", title).strip().strip(".")
    if normalized:
        return f"{normalized}.html"
    mapping = {
        "persona_collection": "画像资料整理.html",
        "capability_generation": "能力样例草案.html",
        "review_and_alignment": "回看材料包.html",
    }
    return mapping.get(stage_key, "任务产物.html")


def _role_creation_current_task_ref_payload(
    detail: dict[str, Any],
    *,
    node_id: str,
) -> dict[str, Any]:
    task_refs = list(detail.get("task_refs") or [])
    stages = list(detail.get("stages") or [])
    ref_row = next(
        (item for item in task_refs if str(item.get("node_id") or "").strip() == str(node_id or "").strip()),
        {},
    )
    task_row = {}
    for stage in stages:
        for item in list(stage.get("active_tasks") or []) + list(stage.get("archived_tasks") or []):
            if str(item.get("node_id") or "").strip() == str(node_id or "").strip():
                task_row = dict(item)
                break
        if task_row:
            break
    payload = dict(task_row)
    payload.setdefault("ref_id", str(ref_row.get("ref_id") or "").strip())
    payload.setdefault("relation_state", str(ref_row.get("relation_state") or "active").strip().lower() or "active")
    payload.setdefault("close_reason", str(ref_row.get("close_reason") or "").strip())
    return payload


def _create_role_creation_task_internal(
    cfg: Any,
    *,
    session_summary: dict[str, Any],
    task_refs: list[dict[str, Any]],
    stage_key: str,
    node_name: str,
    node_goal: str,
    expected_artifact: str,
    operator: str,
    priority: str = "",
) -> dict[str, Any]:
    stage_key = _normalize_stage_key(stage_key)
    ticket_id = str(session_summary.get("assignment_ticket_id") or "").strip()
    if not ticket_id:
        raise TrainingCenterError(409, "当前角色还未进入创建流程", "role_creation_not_started")
    assigned_agent_id = str(session_summary.get("created_agent_id") or "").strip()
    assigned_agent_name = str(session_summary.get("created_agent_name") or assigned_agent_id or "").strip()
    if not assigned_agent_id:
        raise TrainingCenterError(409, "当前角色执行主体未初始化", "role_creation_agent_not_initialized")
    stage_index = int((ROLE_CREATION_STAGE_BY_KEY.get(stage_key) or {}).get("index") or 0)
    requested_priority = _normalize_text(priority, max_len=4).upper()
    if requested_priority not in {"P0", "P1", "P2", "P3"}:
        requested_priority = "P0" if stage_key == "persona_collection" else "P1"
    upstream_node_ids = _stage_anchor_task_ids(task_refs, stage_key=stage_key)
    node_payload = {
        "node_name": _normalize_text(node_name, max_len=200),
        "assigned_agent_id": assigned_agent_id,
        "node_goal": _normalize_text(node_goal, max_len=4000),
        "expected_artifact": _normalize_text(expected_artifact, max_len=240),
        "priority": requested_priority,
        "upstream_node_ids": upstream_node_ids,
        "operator": operator,
        "allow_creating_agent": True,
    }
    if not node_payload["node_name"]:
        raise TrainingCenterError(400, "任务名称不能为空", "role_creation_task_name_required")
    if not node_payload["node_goal"]:
        raise TrainingCenterError(400, "任务目标不能为空", "role_creation_task_goal_required")
    try:
        created = assignment_service.create_assignment_node(
            cfg,
            ticket_id,
            node_payload,
            include_test_data=True,
        )
    except Exception as exc:
        _raise_role_creation_assignment_error(exc, "role_creation_task_create_failed")
    node = dict(created.get("node") or {})
    now_text = _tc_now_text()
    conn = connect_db(cfg.root)
    try:
        conn.execute(
            """
            INSERT INTO role_creation_task_refs (
                ref_id,session_id,ticket_id,node_id,stage_key,stage_index,relation_state,close_reason,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id,node_id) DO UPDATE SET
                ticket_id=excluded.ticket_id,
                stage_key=excluded.stage_key,
                stage_index=excluded.stage_index,
                relation_state='active',
                close_reason='',
                updated_at=excluded.updated_at
            """,
            (
                _role_creation_task_ref_id(),
                str(session_summary.get("session_id") or "").strip(),
                ticket_id,
                str(node.get("node_id") or "").strip(),
                stage_key,
                stage_index,
                "active",
                "",
                now_text,
                now_text,
            ),
        )
        conn.execute(
            """
            UPDATE role_creation_sessions
            SET current_stage_key=?,current_stage_index=?,updated_at=?
            WHERE session_id=?
            """,
            (
                stage_key,
                stage_index,
                now_text,
                str(session_summary.get("session_id") or "").strip(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "ticket_id": ticket_id,
        "stage_key": stage_key,
        "stage_index": stage_index,
        "task_id": str(node.get("node_id") or "").strip(),
        "node_id": str(node.get("node_id") or "").strip(),
        "task_name": str(node.get("node_name") or node_payload["node_name"]).strip(),
        "status": str(node.get("status") or "pending").strip().lower() or "pending",
        "status_text": str(node.get("status_text") or "待开始").strip() or "待开始",
        "assigned_agent_id": assigned_agent_id,
        "assigned_agent_name": assigned_agent_name,
    }


def _maybe_create_delegate_tasks(
    cfg: Any,
    *,
    session_summary: dict[str, Any],
    task_refs: list[dict[str, Any]],
    role_spec: dict[str, Any],
    message_text: str,
    operator: str,
) -> list[dict[str, Any]]:
    if _normalize_session_status(session_summary.get("status")) != "creating":
        return []
    delegate_requests = _delegate_requests_from_text(message_text)
    if not delegate_requests:
        return []
    role_name = _role_creation_title_from_spec(role_spec, session_summary.get("session_title") or "")
    created_tasks: list[dict[str, Any]] = []
    known_refs = list(task_refs)
    for clause in delegate_requests[:3]:
        stage_key = _infer_task_stage_key(clause, str(session_summary.get("current_stage_key") or "persona_collection"))
        task_name = _delegate_task_title(clause, role_name)
        expected_artifact = _role_creation_default_artifact_name(stage_key, task_name)
        task = _create_role_creation_task_internal(
            cfg,
            session_summary=session_summary,
            task_refs=known_refs,
            stage_key=stage_key,
            node_name=task_name,
            node_goal=clause,
            expected_artifact=expected_artifact,
            operator=operator,
        )
        created_tasks.append(task)
        known_refs.append(
            {
                "session_id": str(session_summary.get("session_id") or "").strip(),
                "ticket_id": str(task.get("ticket_id") or "").strip(),
                "node_id": str(task.get("node_id") or "").strip(),
                "stage_key": stage_key,
                "stage_index": int(task.get("stage_index") or 0),
                "relation_state": "active",
                "close_reason": "",
            }
        )
        session_summary["current_stage_key"] = stage_key
        session_summary["current_stage_index"] = int(task.get("stage_index") or 0)
    return created_tasks
