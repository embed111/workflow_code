def _sync_session_bundle_with_conn(conn: sqlite3.Connection, root: Path, session_id: str, *, update_json_index: bool) -> None:
    session_id_text = str(session_id or "").strip()
    if not session_id_text:
        return
    prefix = f"records/sessions/{session_id_text}/"
    _mark_prefix_deleted(conn, prefix)
    conn.execute("DELETE FROM conversation_message_index WHERE session_id=?", (session_id_text,))
    conn.execute("DELETE FROM session_index WHERE session_id=?", (session_id_text,))
    session_path = _store.session_record_path(root, session_id_text)
    message_path = _store.session_messages_path(root, session_id_text)
    session = _store._load_json_dict(session_path)
    if not session:
        if update_json_index:
            _remove_json_index_item(_store.sessions_index_path(root), "session_id", session_id_text)
        return
    messages = _read_jsonl_with_lines(message_path)
    conn.execute(
        """
        INSERT OR REPLACE INTO session_index (
            session_id,status,agent_name,agents_version,is_test_data,created_at,updated_at,
            last_message_at,message_count,work_record_count,last_message_preview,session_relpath,messages_relpath
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            session_id_text,
            str(session.get("status") or ""),
            str(session.get("agent_name") or ""),
            str(session.get("agents_version") or ""),
            1 if _store._normalize_bool(session.get("is_test_data")) else 0,
            str(session.get("created_at") or ""),
            str(session.get("updated_at") or ""),
            str(session.get("last_message_at") or ""),
            _safe_int(session.get("message_count")),
            _safe_int(session.get("work_record_count")),
            _preview(session.get("last_message") or ""),
            _artifact_relpath(root, session_path),
            _artifact_relpath(root, message_path),
        ),
    )
    _touch_source(conn, root, session_path, record_kind="record_json", entity_type="session", entity_id=session_id_text)
    if message_path.exists():
        _touch_source(conn, root, message_path, record_kind="record_jsonl", entity_type="conversation_message", entity_id=session_id_text, parent_id=session_id_text)
    source_relpath = _artifact_relpath(root, message_path)
    for line_no, row in messages:
        conn.execute(
            """
            INSERT OR REPLACE INTO conversation_message_index (
                session_id,message_id,role,created_at,analysis_state,analysis_run_id,analysis_updated_at,
                content_preview,content_length,source_relpath,source_line_no
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id_text,
                _safe_int(row.get("message_id")),
                str(row.get("role") or ""),
                str(row.get("created_at") or ""),
                str(row.get("analysis_state") or ""),
                str(row.get("analysis_run_id") or ""),
                str(row.get("analysis_updated_at") or ""),
                _preview(row.get("content") or ""),
                len(str(row.get("content") or "")),
                source_relpath,
                line_no,
            ),
        )
    if update_json_index:
        _upsert_json_index_item(_store.sessions_index_path(root), "session_id", _session_summary(session))


def sync_session_bundle(root: Path, session_id: str) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _sync_session_bundle_with_conn(conn, root, session_id, update_json_index=True)
            conn.commit()
        finally:
            conn.close()
        _write_records_manifest(root)


def _sync_analysis_bundle_with_conn(conn: sqlite3.Connection, root: Path, analysis_id: str, *, update_json_index: bool) -> None:
    analysis_id_text = str(analysis_id or "").strip()
    if not analysis_id_text:
        return
    prefix = f"records/analysis/{analysis_id_text}/"
    _mark_prefix_deleted(conn, prefix)
    conn.execute("DELETE FROM analysis_run_index WHERE analysis_id=?", (analysis_id_text,))
    conn.execute("DELETE FROM analysis_index WHERE analysis_id=?", (analysis_id_text,))
    conn.execute("DELETE FROM event_index WHERE analysis_id=?", (analysis_id_text,))
    analysis_path = _store.analysis_record_path(root, analysis_id_text)
    workflow_path = _store.workflow_record_path(root, analysis_id_text)
    training_path = _store.training_record_path(root, analysis_id_text)
    events_path = _store.analysis_workflow_events_path(root, analysis_id_text)
    analysis = _store._load_json_dict(analysis_path)
    workflow = _store._load_json_dict(workflow_path)
    training = _store._load_json_dict(training_path)
    if not analysis:
        if update_json_index:
            _remove_json_index_item(_store.analysis_index_path(root), "analysis_id", analysis_id_text)
        return
    conn.execute(
        """
        INSERT OR REPLACE INTO analysis_index (
            analysis_id,session_id,status,decision,workflow_id,workflow_status,training_id,training_status,
            created_at,updated_at,decision_reason_preview,analysis_summary_preview,analysis_recommendation_preview,
            latest_analysis_run_id,train_result_summary,analysis_relpath,workflow_relpath,training_relpath,workflow_events_relpath
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            analysis_id_text,
            str(analysis.get("session_id") or ""),
            str(analysis.get("status") or ""),
            str(analysis.get("decision") or ""),
            str(workflow.get("workflow_id") or ""),
            str(workflow.get("status") or workflow.get("workflow_status") or ""),
            str(training.get("training_id") or ""),
            str(training.get("status") or ""),
            str(analysis.get("created_at") or ""),
            str(analysis.get("updated_at") or ""),
            _preview(analysis.get("decision_reason") or ""),
            _preview(workflow.get("analysis_summary") or ""),
            _preview(workflow.get("analysis_recommendation") or ""),
            str(workflow.get("latest_analysis_run_id") or ""),
            _preview(training.get("result_summary") or ""),
            _artifact_relpath(root, analysis_path),
            _artifact_relpath(root, workflow_path),
            _artifact_relpath(root, training_path),
            _artifact_relpath(root, events_path),
        ),
    )
    _touch_source(conn, root, analysis_path, record_kind="record_json", entity_type="analysis", entity_id=analysis_id_text)
    if workflow:
        _touch_source(conn, root, workflow_path, record_kind="record_json", entity_type="analysis_workflow", entity_id=analysis_id_text, parent_id=analysis_id_text)
    if training:
        _touch_source(conn, root, training_path, record_kind="record_json", entity_type="training_task", entity_id=analysis_id_text, parent_id=analysis_id_text)
    workflow_id = str(workflow.get("workflow_id") or "")
    session_id = str(analysis.get("session_id") or "")
    for run_path in sorted(_store.analysis_runs_root(root, analysis_id_text).glob("*.json"), key=lambda item: item.name.lower()):
        run = _store._load_json_dict(run_path)
        if not run:
            continue
        run_id = str(run.get("analysis_run_id") or run_path.stem or "")
        conn.execute(
            """
            INSERT OR REPLACE INTO analysis_run_index (
                analysis_run_id,analysis_id,workflow_id,session_id,status,created_at,updated_at,
                plan_item_count,context_message_count,target_message_count,no_value_reason,error_text_preview,analysis_run_relpath
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                analysis_id_text,
                str(run.get("workflow_id") or workflow_id),
                str(run.get("session_id") or session_id),
                str(run.get("status") or ""),
                str(run.get("created_at") or ""),
                str(run.get("updated_at") or ""),
                len(list(run.get("plan_items") or [])),
                len(_store._parse_json_list(run.get("context_message_ids_json"))),
                len(_store._parse_json_list(run.get("target_message_ids_json"))),
                str(run.get("no_value_reason") or ""),
                _preview(run.get("error_text") or ""),
                _artifact_relpath(root, run_path),
            ),
        )
        _touch_source(conn, root, run_path, record_kind="record_json", entity_type="analysis_run", entity_id=run_id, parent_id=analysis_id_text)
    if events_path.exists():
        _touch_source(conn, root, events_path, record_kind="record_jsonl", entity_type="analysis_event", entity_id=analysis_id_text, parent_id=analysis_id_text)
    for line_no, row in _read_jsonl_with_lines(events_path):
        conn.execute(
            """
            INSERT OR REPLACE INTO event_index (
                event_key,stream_type,ticket_id,node_id,run_id,task_id,session_id,analysis_id,workflow_id,
                event_type,level,created_at,message_preview,detail_preview,related_status,source_relpath,source_line_no,run_relpath
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"analysis_workflow_event:{analysis_id_text}:{line_no}",
                "analysis_workflow_event",
                "",
                "",
                "",
                "",
                session_id,
                analysis_id_text,
                workflow_id,
                str(row.get("event_type") or row.get("type") or ""),
                str(row.get("level") or ""),
                str(row.get("created_at") or row.get("timestamp") or ""),
                _preview(row.get("message") or row.get("summary") or row.get("event_type") or ""),
                _preview(row.get("detail") or row.get("payload") or ""),
                str(row.get("status") or ""),
                _artifact_relpath(root, events_path),
                line_no,
                "",
            ),
        )
    if update_json_index:
        _upsert_json_index_item(_store.analysis_index_path(root), "analysis_id", _analysis_summary(analysis, workflow, training))


def sync_analysis_bundle(root: Path, analysis_id: str) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _sync_analysis_bundle_with_conn(conn, root, analysis_id, update_json_index=True)
            conn.commit()
        finally:
            conn.close()
        _write_records_manifest(root)


