def _sync_record_task_run_with_conn(conn: sqlite3.Connection, root: Path, task_id: str, *, update_json_index: bool) -> None:
    task_id_text = str(task_id or "").strip()
    if not task_id_text:
        return
    prefix = f"records/runs/{task_id_text}/"
    _mark_prefix_deleted(conn, prefix)
    conn.execute("DELETE FROM task_run_index WHERE task_id=?", (task_id_text,))
    conn.execute("DELETE FROM event_index WHERE task_id=?", (task_id_text,))
    run_path = _store.run_record_path(root, task_id_text)
    run = _store._load_json_dict(run_path)
    if not run:
        if update_json_index:
            _remove_json_index_item(_store.runs_index_path(root), "task_id", task_id_text)
        return
    stdout_path = _store.run_stdout_path(root, task_id_text)
    stderr_path = _store.run_stderr_path(root, task_id_text)
    trace_path = _store.run_trace_path(root, task_id_text)
    events_path = _store.run_events_path(root, task_id_text)
    summary_path = _store.run_summary_path(root, task_id_text)
    summary_text = ""
    if summary_path.exists():
        try:
            summary_text = summary_path.read_text(encoding="utf-8")
        except Exception:
            summary_text = ""
    conn.execute(
        """
        INSERT OR REPLACE INTO task_run_index (
            task_id,session_id,agent_name,status,created_at,updated_at,start_at,end_at,duration_ms,
            summary_preview,run_relpath,stdout_relpath,stderr_relpath,trace_relpath,events_relpath,summary_relpath
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            task_id_text,
            str(run.get("session_id") or ""),
            str(run.get("agent_name") or ""),
            str(run.get("status") or ""),
            str(run.get("created_at") or ""),
            str(run.get("updated_at") or ""),
            str(run.get("start_at") or ""),
            str(run.get("end_at") or ""),
            _safe_int(run.get("duration_ms")),
            _preview(run.get("summary") or summary_text),
            _artifact_relpath(root, run_path),
            _artifact_relpath(root, stdout_path),
            _artifact_relpath(root, stderr_path),
            _artifact_relpath(root, trace_path),
            _artifact_relpath(root, events_path),
            _artifact_relpath(root, summary_path),
        ),
    )
    _touch_source(conn, root, run_path, record_kind="record_json", entity_type="task_run", entity_id=task_id_text)
    for aux_path, entity_type in (
        (stdout_path, "task_run_stdout"),
        (stderr_path, "task_run_stderr"),
        (trace_path, "task_run_trace"),
        (events_path, "task_run_event"),
        (summary_path, "task_run_summary"),
    ):
        if aux_path.exists():
            _touch_source(conn, root, aux_path, record_kind="record_file", entity_type=entity_type, entity_id=task_id_text, parent_id=task_id_text)
    run_relpath = _artifact_relpath(root, run_path)
    for line_no, row in _read_jsonl_with_lines(events_path):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        conn.execute(
            """
            INSERT OR REPLACE INTO event_index (
                event_key,stream_type,ticket_id,node_id,run_id,task_id,session_id,analysis_id,workflow_id,
                event_type,level,created_at,message_preview,detail_preview,related_status,source_relpath,source_line_no,run_relpath
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"record_task_run_event:{task_id_text}:{line_no}",
                "record_task_run_event",
                "",
                "",
                task_id_text,
                task_id_text,
                str(run.get("session_id") or ""),
                "",
                "",
                str(row.get("event_type") or ""),
                str(payload.get("level") or ""),
                str(row.get("timestamp") or ""),
                _preview(payload.get("message") or payload.get("summary") or row.get("event_type") or ""),
                _preview(payload),
                str(payload.get("status") or ""),
                _artifact_relpath(root, events_path),
                line_no,
                run_relpath,
            ),
        )
    if update_json_index:
        _upsert_json_index_item(_store.runs_index_path(root), "task_id", _run_summary(run))


def sync_record_task_run(root: Path, task_id: str) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _sync_record_task_run_with_conn(conn, root, task_id, update_json_index=True)
            conn.commit()
        finally:
            conn.close()
        _write_records_manifest(root)


def _sync_policy_patch_task_with_conn(conn: sqlite3.Connection, root: Path, patch_task_id: str, *, update_json_index: bool) -> None:
    patch_task_id_text = str(patch_task_id or "").strip()
    if not patch_task_id_text:
        return
    path = _store.policy_patch_task_path(root, patch_task_id_text)
    relpath = _artifact_relpath(root, path)
    conn.execute("DELETE FROM audit_index WHERE audit_type='policy_patch_task' AND source_relpath=?", (relpath,))
    if not path.exists():
        if update_json_index:
            _remove_json_index_item(_store.policy_patch_index_path(root), "patch_task_id", patch_task_id_text)
        return
    record = _store._load_json_dict(path)
    if not record:
        return
    conn.execute(
        """
        INSERT OR REPLACE INTO audit_index (
            audit_key,audit_type,session_id,analysis_id,ticket_id,node_id,action,status,operator,created_at,
            reason_preview,manual_fallback,ref_relpath,source_relpath,source_line_no
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            f"policy_patch_task:{patch_task_id_text}",
            "policy_patch_task",
            str(record.get("source_session_id") or ""),
            "",
            "",
            "",
            "policy_patch_task",
            str(record.get("status") or ""),
            str(record.get("agent_name") or ""),
            str(record.get("created_at") or ""),
            _preview(record.get("summary") or record.get("status") or ""),
            0,
            relpath,
            relpath,
            0,
        ),
    )
    _touch_source(conn, root, path, record_kind="record_json", entity_type="policy_patch_task", entity_id=patch_task_id_text)
    if update_json_index:
        _upsert_json_index_item(_store.policy_patch_index_path(root), "patch_task_id", _policy_patch_summary(record))


def sync_policy_patch_task(root: Path, patch_task_id: str) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _sync_policy_patch_task_with_conn(conn, root, patch_task_id, update_json_index=True)
            conn.commit()
        finally:
            conn.close()
        _write_records_manifest(root)


def _sync_message_delete_audit_with_conn(conn: sqlite3.Connection, root: Path) -> None:
    path = _store.message_delete_audit_path(root)
    relpath = _artifact_relpath(root, path)
    conn.execute("DELETE FROM audit_index WHERE audit_type='message_delete'")
    if not path.exists():
        return
    _touch_source(conn, root, path, record_kind="record_jsonl", entity_type="message_delete_audit", entity_id="message-delete")
    for line_no, row in _read_jsonl_with_lines(path):
        _upsert_message_delete_audit_row(
            conn,
            root,
            row,
            source_relpath=relpath,
            source_line_no=line_no,
        )


def _sync_policy_confirmation_audit_with_conn(conn: sqlite3.Connection, root: Path) -> None:
    path = _store.policy_confirmation_audit_path(root)
    relpath = _artifact_relpath(root, path)
    conn.execute("DELETE FROM audit_index WHERE audit_type='policy_confirmation'")
    if not path.exists():
        return
    _touch_source(conn, root, path, record_kind="record_jsonl", entity_type="policy_confirmation_audit", entity_id="policy-confirmation")
    for line_no, row in _read_jsonl_with_lines(path):
        _upsert_policy_confirmation_audit_row(
            conn,
            root,
            row,
            source_relpath=relpath,
            source_line_no=line_no,
        )


def _message_delete_audit_key(row: dict[str, Any], *, line_no: int = 0) -> str:
    audit_id = _safe_int(row.get("audit_id"))
    if audit_id > 0:
        return f"message_delete:{audit_id}"
    return f"message_delete:{line_no}"


def _policy_confirmation_audit_key(row: dict[str, Any], *, line_no: int = 0) -> str:
    audit_id = _safe_int(row.get("audit_id"))
    if audit_id > 0:
        return f"policy_confirmation:{audit_id}"
    return f"policy_confirmation:{line_no}"


def _system_workflow_event_key(row: dict[str, Any], *, line_no: int = 0) -> str:
    event_id = str(row.get("event_id") or "").strip()
    if event_id:
        return f"system_workflow_event:{event_id}"
    return f"system_workflow_event:{line_no}"


def _reconcile_run_key(row: dict[str, Any], *, line_no: int = 0) -> str:
    run_id = str(row.get("run_id") or "").strip()
    if run_id:
        return f"reconcile_run:{run_id}"
    return f"reconcile_run:{line_no}"


def _upsert_message_delete_audit_row(
    conn: sqlite3.Connection,
    root: Path,
    row: dict[str, Any],
    *,
    source_relpath: str,
    source_line_no: int = 0,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO audit_index (
            audit_key,audit_type,session_id,analysis_id,ticket_id,node_id,action,status,operator,created_at,
            reason_preview,manual_fallback,ref_relpath,source_relpath,source_line_no
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _message_delete_audit_key(row, line_no=source_line_no),
            "message_delete",
            str(row.get("session_id") or ""),
            "",
            "",
            "",
            str(row.get("action") or "delete"),
            "",
            str(row.get("operator") or ""),
            str(row.get("created_at") or row.get("audit_ts") or ""),
            _preview(row.get("reason") or row.get("reason_text") or ""),
            0,
            _ref_relpath(root, str(row.get("ref") or "")),
            source_relpath,
            source_line_no,
        ),
    )


def _upsert_policy_confirmation_audit_row(
    conn: sqlite3.Connection,
    root: Path,
    row: dict[str, Any],
    *,
    source_relpath: str,
    source_line_no: int = 0,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO audit_index (
            audit_key,audit_type,session_id,analysis_id,ticket_id,node_id,action,status,operator,created_at,
            reason_preview,manual_fallback,ref_relpath,source_relpath,source_line_no
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _policy_confirmation_audit_key(row, line_no=source_line_no),
            "policy_confirmation",
            str(row.get("session_id") or ""),
            "",
            "",
            "",
            str(row.get("action") or ""),
            str(row.get("status") or ""),
            str(row.get("operator") or ""),
            str(row.get("created_at") or row.get("audit_ts") or ""),
            _preview(row.get("reason") or row.get("reason_text") or row.get("detail") or ""),
            1 if _store._normalize_bool(row.get("manual_fallback")) else 0,
            _ref_relpath(root, str(row.get("ref") or "")),
            source_relpath,
            source_line_no,
        ),
    )


def _upsert_system_workflow_event_row(
    conn: sqlite3.Connection,
    root: Path,
    row: dict[str, Any],
    *,
    source_relpath: str,
    source_line_no: int = 0,
) -> None:
    event_type = str(row.get("event_type") or row.get("action") or "").strip()
    level = str(row.get("level") or row.get("stage") or "").strip()
    created_at = str(row.get("created_at") or row.get("timestamp") or "").strip()
    conn.execute(
        """
        INSERT OR REPLACE INTO event_index (
            event_key,stream_type,ticket_id,node_id,run_id,task_id,session_id,analysis_id,workflow_id,
            event_type,level,created_at,message_preview,detail_preview,related_status,source_relpath,source_line_no,run_relpath
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _system_workflow_event_key(row, line_no=source_line_no),
            "system_workflow_event",
            str(row.get("ticket_id") or ""),
            str(row.get("node_id") or ""),
            str(row.get("run_id") or ""),
            str(row.get("task_id") or ""),
            str(row.get("session_id") or ""),
            str(row.get("analysis_id") or ""),
            str(row.get("workflow_id") or ""),
            event_type,
            level,
            created_at,
            _preview(row.get("message") or row.get("action") or row.get("status") or event_type),
            _preview(row),
            str(row.get("status") or ""),
            source_relpath,
            source_line_no,
            "",
        ),
    )


def _upsert_reconcile_run_row(
    conn: sqlite3.Connection,
    root: Path,
    row: dict[str, Any],
    *,
    source_relpath: str,
    source_line_no: int = 0,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO event_index (
            event_key,stream_type,ticket_id,node_id,run_id,task_id,session_id,analysis_id,workflow_id,
            event_type,level,created_at,message_preview,detail_preview,related_status,source_relpath,source_line_no,run_relpath
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _reconcile_run_key(row, line_no=source_line_no),
            "reconcile_run",
            "",
            "",
            str(row.get("run_id") or ""),
            "",
            "",
            "",
            "",
            str(row.get("reason") or "reconcile"),
            "",
            str(row.get("run_at") or row.get("created_at") or ""),
            _preview(row.get("notes") or row.get("reason") or ""),
            _preview(row),
            str(row.get("status") or ""),
            source_relpath,
            source_line_no,
            _artifact_relpath(root, str(row.get("ref") or "")),
        ),
    )


def _upsert_ingress_request_row(
    conn: sqlite3.Connection,
    root: Path,
    row: dict[str, Any],
    *,
    source_relpath: str = "",
) -> None:
    request_id = str(row.get("request_id") or "").strip()
    if not request_id:
        return
    conn.execute(
        """
        INSERT OR REPLACE INTO ingress_request_index (
            request_id,session_id,route,created_at,event_logged,source_relpath
        ) VALUES (?,?,?,?,?,?)
        """,
        (
            request_id,
            str(row.get("session_id") or ""),
            str(row.get("route") or ""),
            str(row.get("created_at") or ""),
            1 if _store._normalize_bool(row.get("event_logged")) else 0,
            source_relpath,
        ),
    )


def _sync_system_workflow_events_with_conn(conn: sqlite3.Connection, root: Path) -> None:
    path = _store.workflow_events_path(root)
    relpath = _artifact_relpath(root, path)
    conn.execute("DELETE FROM event_index WHERE stream_type='system_workflow_event'")
    if not path.exists():
        return
    _touch_source(conn, root, path, record_kind="record_jsonl", entity_type="system_workflow_event", entity_id="workflow-events")
    for line_no, row in _read_jsonl_with_lines(path):
        _upsert_system_workflow_event_row(
            conn,
            root,
            row,
            source_relpath=relpath,
            source_line_no=line_no,
        )


def _sync_reconcile_runs_with_conn(conn: sqlite3.Connection, root: Path) -> None:
    path = _store.reconcile_runs_path(root)
    relpath = _artifact_relpath(root, path)
    conn.execute("DELETE FROM event_index WHERE stream_type='reconcile_run'")
    if not path.exists():
        return
    _touch_source(conn, root, path, record_kind="record_jsonl", entity_type="reconcile_run", entity_id="reconcile-runs")
    for line_no, row in _read_jsonl_with_lines(path):
        _upsert_reconcile_run_row(
            conn,
            root,
            row,
            source_relpath=relpath,
            source_line_no=line_no,
        )


def _sync_ingress_requests_with_conn(conn: sqlite3.Connection, root: Path) -> None:
    path = _store.ingress_requests_path(root)
    relpath = _artifact_relpath(root, path)
    conn.execute("DELETE FROM ingress_request_index")
    if not path.exists():
        return
    _touch_source(conn, root, path, record_kind="record_json", entity_type="ingress_request", entity_id="ingress-requests")
    current = _store._load_json_dict(path)
    items = current.get("items") if isinstance(current.get("items"), dict) else {}
    for request_id, row in items.items():
        payload = dict(row or {})
        payload["request_id"] = str(payload.get("request_id") or request_id or "").strip()
        _upsert_ingress_request_row(conn, root, payload, source_relpath=relpath)


def sync_audit_and_system_indexes(root: Path) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _sync_message_delete_audit_with_conn(conn, root)
            _sync_policy_confirmation_audit_with_conn(conn, root)
            _sync_system_workflow_events_with_conn(conn, root)
            _sync_reconcile_runs_with_conn(conn, root)
            _sync_ingress_requests_with_conn(conn, root)
            conn.commit()
        finally:
            conn.close()
        _write_records_manifest(root)


def append_message_delete_audit_index(root: Path, row: dict[str, Any]) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _upsert_message_delete_audit_row(
                conn,
                root,
                dict(row or {}),
                source_relpath=_artifact_relpath(root, _store.message_delete_audit_path(root)),
            )
            _touch_source(
                conn,
                root,
                _store.message_delete_audit_path(root),
                record_kind="record_jsonl",
                entity_type="message_delete_audit",
                entity_id="message-delete",
            )
            conn.commit()
        finally:
            conn.close()


def append_policy_confirmation_audit_index(root: Path, row: dict[str, Any]) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _upsert_policy_confirmation_audit_row(
                conn,
                root,
                dict(row or {}),
                source_relpath=_artifact_relpath(root, _store.policy_confirmation_audit_path(root)),
            )
            _touch_source(
                conn,
                root,
                _store.policy_confirmation_audit_path(root),
                record_kind="record_jsonl",
                entity_type="policy_confirmation_audit",
                entity_id="policy-confirmation",
            )
            conn.commit()
        finally:
            conn.close()


def append_system_workflow_event_index(root: Path, row: dict[str, Any]) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _upsert_system_workflow_event_row(
                conn,
                root,
                dict(row or {}),
                source_relpath=_artifact_relpath(root, _store.workflow_events_path(root)),
            )
            _touch_source(
                conn,
                root,
                _store.workflow_events_path(root),
                record_kind="record_jsonl",
                entity_type="system_workflow_event",
                entity_id="workflow-events",
            )
            conn.commit()
        finally:
            conn.close()


def append_reconcile_run_index(root: Path, row: dict[str, Any]) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _upsert_reconcile_run_row(
                conn,
                root,
                dict(row or {}),
                source_relpath=_artifact_relpath(root, _store.reconcile_runs_path(root)),
            )
            _touch_source(
                conn,
                root,
                _store.reconcile_runs_path(root),
                record_kind="record_jsonl",
                entity_type="reconcile_run",
                entity_id="reconcile-runs",
            )
            conn.commit()
        finally:
            conn.close()


def upsert_ingress_request_index(root: Path, row: dict[str, Any]) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _upsert_ingress_request_row(conn, root, dict(row or {}))
            conn.commit()
        finally:
            conn.close()


def mark_ingress_request_logged_index(root: Path, request_id: str) -> None:
    request_id_text = str(request_id or "").strip()
    if not request_id_text:
        return
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            conn.execute(
                "UPDATE ingress_request_index SET event_logged=1 WHERE request_id=?",
                (request_id_text,),
            )
            conn.commit()
        finally:
            conn.close()


def _sync_assignment_task_bundle_with_conn(conn: sqlite3.Connection, root: Path, ticket_id: str) -> None:
    ticket_id_text = str(ticket_id or "").strip()
    if not ticket_id_text:
        return
    prefix = f"tasks/{ticket_id_text}/"
    _mark_prefix_deleted(conn, prefix)
    conn.execute("DELETE FROM task_node_index WHERE ticket_id=?", (ticket_id_text,))
    conn.execute("DELETE FROM task_index WHERE ticket_id=?", (ticket_id_text,))
    conn.execute("DELETE FROM assignment_run_index WHERE ticket_id=?", (ticket_id_text,))
    conn.execute("DELETE FROM audit_index WHERE ticket_id=?", (ticket_id_text,))
    conn.execute("DELETE FROM event_index WHERE ticket_id=?", (ticket_id_text,))
    task_dir = _store.artifact_root(root) / "tasks" / ticket_id_text
    task_path = task_dir / "task.json"
    graph = _store._load_json_dict(task_path)
    if not graph:
        return
    nodes_root = task_dir / "nodes"
    node_rows: list[dict[str, Any]] = []
    for node_path in sorted(nodes_root.glob("*.json"), key=lambda item: item.name.lower()):
        node = _store._load_json_dict(node_path)
        if not node:
            continue
        node_rows.append(node)
        node_id = str(node.get("node_id") or node_path.stem or "")
        artifact_base = task_dir / "artifacts" / node_id
        conn.execute(
            """
            INSERT OR REPLACE INTO task_node_index (
                ticket_id,node_id,status,assigned_agent_id,delivery_mode,artifact_delivery_status,priority,created_at,updated_at,completed_at,
                node_name,assigned_agent_name,expected_artifact_preview,success_reason_preview,failure_reason_preview,result_ref_relpath,
                upstream_count,downstream_count,artifact_count,node_relpath,artifact_output_dir_relpath,artifact_delivery_dir_relpath
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ticket_id_text,
                node_id,
                str(node.get("status") or ""),
                str(node.get("assigned_agent_id") or ""),
                str(node.get("delivery_mode") or ""),
                str(node.get("artifact_delivery_status") or ""),
                _safe_int(node.get("priority")),
                str(node.get("created_at") or ""),
                str(node.get("updated_at") or ""),
                str(node.get("completed_at") or ""),
                str(node.get("node_name") or ""),
                str(node.get("assigned_agent_name") or ""),
                _preview(node.get("expected_artifact") or ""),
                _preview(node.get("success_reason") or ""),
                _preview(node.get("failure_reason") or ""),
                _ref_relpath(root, str(node.get("result_ref") or "")),
                len(list(node.get("upstream_node_ids") or [])),
                len(list(node.get("downstream_node_ids") or [])),
                len(list(node.get("artifact_paths") or [])),
                _artifact_relpath(root, node_path),
                _artifact_relpath(root, artifact_base / "output"),
                _artifact_relpath(root, artifact_base / "delivery"),
            ),
        )
        _touch_source(conn, root, node_path, record_kind="task_json", entity_type="task_node", entity_id=node_id, parent_id=ticket_id_text)
    status_counter = {"running": 0, "success": 0, "failed": 0, "blocked": 0}
    for node in node_rows:
        status_text = str(node.get("status") or "").strip().lower()
        if status_text in status_counter:
            status_counter[status_text] += 1
    conn.execute(
        """
        INSERT OR REPLACE INTO task_index (
            ticket_id,scheduler_state,graph_name,source_workflow,summary_preview,is_test_data,created_at,updated_at,
            node_count,running_node_count,success_node_count,failed_node_count,blocked_node_count,task_relpath,task_structure_relpath
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticket_id_text,
            str(graph.get("scheduler_state") or ""),
            str(graph.get("graph_name") or ""),
            str(graph.get("source_workflow") or ""),
            _preview(graph.get("summary") or ""),
            1 if _store._normalize_bool(graph.get("is_test_data")) else 0,
            str(graph.get("created_at") or ""),
            str(graph.get("updated_at") or ""),
            len(node_rows),
            status_counter["running"],
            status_counter["success"],
            status_counter["failed"],
            status_counter["blocked"],
            _artifact_relpath(root, task_path),
            _artifact_relpath(root, task_dir / "TASK_STRUCTURE.md"),
        ),
    )
    _touch_source(conn, root, task_path, record_kind="task_json", entity_type="task", entity_id=ticket_id_text)
    for run_dir in sorted((task_dir / "runs").glob("*/"), key=lambda item: item.name.lower()):
        run_path = run_dir / "run.json"
        run = _store._load_json_dict(run_path)
        if not run:
            continue
        run_id = str(run.get("run_id") or run_dir.name or "")
        result_path = run_dir / "result.json"
        result_md_path = run_dir / "result.md"
        events_path = run_dir / "events.log"
        result_payload = _store._load_json_dict(result_path)
        result_summary = _preview(
            result_payload.get("result_summary")
            or result_payload.get("summary")
            or result_payload.get("artifact_markdown")
            or ""
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO assignment_run_index (
                run_id,ticket_id,node_id,provider,workspace_path,status,command_summary,result_summary,
                latest_event,latest_event_at,exit_code,started_at,finished_at,created_at,updated_at,
                run_relpath,prompt_relpath,stdout_relpath,stderr_relpath,result_json_relpath,result_md_relpath,events_relpath
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                ticket_id_text,
                str(run.get("node_id") or ""),
                str(run.get("provider") or ""),
                str(run.get("workspace_path") or ""),
                str(run.get("status") or ""),
                str(run.get("command_summary") or ""),
                result_summary,
                str(run.get("latest_event") or ""),
                str(run.get("latest_event_at") or ""),
                _safe_int(run.get("exit_code")),
                str(run.get("started_at") or ""),
                str(run.get("finished_at") or ""),
                str(run.get("created_at") or ""),
                str(run.get("updated_at") or ""),
                _artifact_relpath(root, run_path),
                _artifact_relpath(root, run_dir / "prompt.txt"),
                _artifact_relpath(root, run_dir / "stdout.txt"),
                _artifact_relpath(root, run_dir / "stderr.txt"),
                _artifact_relpath(root, result_path),
                _artifact_relpath(root, result_md_path),
                _artifact_relpath(root, events_path),
            ),
        )
        _touch_source(conn, root, run_path, record_kind="task_json", entity_type="assignment_run", entity_id=run_id, parent_id=ticket_id_text)
        for aux_path, entity_type in (
            (result_path, "assignment_run_result"),
            (result_md_path, "assignment_run_result_md"),
            (events_path, "assignment_run_event"),
        ):
            if aux_path.exists():
                _touch_source(conn, root, aux_path, record_kind="task_file", entity_type=entity_type, entity_id=run_id, parent_id=ticket_id_text)
        run_relpath = _artifact_relpath(root, run_path)
        for line_no, row in _read_jsonl_with_lines(events_path):
            conn.execute(
                """
                INSERT OR REPLACE INTO event_index (
                    event_key,stream_type,ticket_id,node_id,run_id,task_id,session_id,analysis_id,workflow_id,
                    event_type,level,created_at,message_preview,detail_preview,related_status,source_relpath,source_line_no,run_relpath
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"assignment_run_event:{run_id}:{line_no}",
                    "assignment_run_event",
                    ticket_id_text,
                    str(run.get("node_id") or ""),
                    run_id,
                    "",
                    "",
                    "",
                    "",
                    str(row.get("event_type") or ""),
                    "",
                    str(row.get("created_at") or ""),
                    _preview(row.get("message") or row.get("event_type") or ""),
                    _preview(row.get("detail") or ""),
                    str(run.get("status") or ""),
                    _artifact_relpath(root, events_path),
                    line_no,
                    run_relpath,
                ),
            )
    audit_path = task_dir / "audit" / "audit.jsonl"
    if audit_path.exists():
        _touch_source(conn, root, audit_path, record_kind="task_jsonl", entity_type="task_audit", entity_id=ticket_id_text, parent_id=ticket_id_text)
    for line_no, row in _read_jsonl_with_lines(audit_path):
        conn.execute(
            """
            INSERT OR REPLACE INTO audit_index (
                audit_key,audit_type,session_id,analysis_id,ticket_id,node_id,action,status,operator,created_at,
                reason_preview,manual_fallback,ref_relpath,source_relpath,source_line_no
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"task_audit:{ticket_id_text}:{line_no}",
                "task_audit",
                "",
                "",
                ticket_id_text,
                str(row.get("node_id") or ""),
                str(row.get("action") or ""),
                str(row.get("target_status") or ""),
                str(row.get("operator") or ""),
                str(row.get("created_at") or ""),
                _preview(row.get("reason") or ""),
                0,
                _ref_relpath(root, str(row.get("ref") or "")),
                _artifact_relpath(root, audit_path),
                line_no,
            ),
        )


def sync_assignment_task_bundle(root: Path, ticket_id: str) -> None:
    with _store._STORE_LOCK:
        ensure_sqlite_index(root)
        conn = _connect(root)
        try:
            _sync_assignment_task_bundle_with_conn(conn, root, ticket_id)
            conn.commit()
        finally:
            conn.close()


def _has_indexable_sources(root: Path) -> bool:
    artifact_root = _store.artifact_root(root)
    checks = (
        next((artifact_root / "tasks").glob("*/task.json"), None),
        next(_store.sessions_root(root).glob("*/session.json"), None),
        next(_store.analysis_root(root).glob("*/analysis.json"), None),
        next(_store.runs_root(root).glob("*/run.json"), None),
        next(_store.policy_patch_tasks_root(root).glob("*.json"), None),
    )
    if any(item is not None for item in checks):
        return True
    for path in (
        _store.message_delete_audit_path(root),
        _store.policy_confirmation_audit_path(root),
        _store.workflow_events_path(root),
        _store.reconcile_runs_path(root),
        _store.ingress_requests_path(root),
    ):
        if path.exists() and path.is_file():
            return True
    return False


def ensure_sqlite_index(root: Path) -> None:
    db_path = sqlite_index_path(root)
    existed = db_path.exists()
    conn = _connect(root)
    try:
        _ensure_schema(conn)
        artifact_marker = _store.artifact_root(root).as_posix()
        current_marker = _read_meta(conn, "artifact_root")
        counts = {
            "task": _safe_int(conn.execute("SELECT COUNT(1) AS cnt FROM task_index").fetchone()["cnt"]),
            "session": _safe_int(conn.execute("SELECT COUNT(1) AS cnt FROM session_index").fetchone()["cnt"]),
            "analysis": _safe_int(conn.execute("SELECT COUNT(1) AS cnt FROM analysis_index").fetchone()["cnt"]),
            "task_run": _safe_int(conn.execute("SELECT COUNT(1) AS cnt FROM task_run_index").fetchone()["cnt"]),
            "audit": _safe_int(conn.execute("SELECT COUNT(1) AS cnt FROM audit_index").fetchone()["cnt"]),
            "event": _safe_int(conn.execute("SELECT COUNT(1) AS cnt FROM event_index").fetchone()["cnt"]),
            "ingress": _safe_int(conn.execute("SELECT COUNT(1) AS cnt FROM ingress_request_index").fetchone()["cnt"]),
        }
        rebuild_needed = (not existed) or (current_marker and current_marker != artifact_marker)
        if not rebuild_needed and not any(int(value or 0) > 0 for value in counts.values()):
            rebuild_needed = _has_indexable_sources(root)
        _set_meta(conn, "artifact_root", artifact_marker)
        conn.commit()
    finally:
        conn.close()
    if rebuild_needed:
        rebuild_record_indexes(root)


def rebuild_record_indexes(root: Path) -> None:
    with _store._STORE_LOCK:
        conn = _connect(root)
        try:
            _ensure_schema(conn)
            _clear_index_tables(conn)
            _set_meta(conn, "artifact_root", _store.artifact_root(root).as_posix())
            _set_meta(conn, "last_full_rebuild_at", _store._now_ts())
            for task_path in sorted((_store.artifact_root(root) / "tasks").glob("*/task.json"), key=lambda item: item.as_posix().lower()):
                _sync_assignment_task_bundle_with_conn(conn, root, task_path.parent.name)
            for session_path in sorted(_store.sessions_root(root).glob("*/session.json"), key=lambda item: item.as_posix().lower()):
                _sync_session_bundle_with_conn(conn, root, session_path.parent.name, update_json_index=False)
            for analysis_path in sorted(_store.analysis_root(root).glob("*/analysis.json"), key=lambda item: item.as_posix().lower()):
                _sync_analysis_bundle_with_conn(conn, root, analysis_path.parent.name, update_json_index=False)
            for run_path in sorted(_store.runs_root(root).glob("*/run.json"), key=lambda item: item.as_posix().lower()):
                _sync_record_task_run_with_conn(conn, root, run_path.parent.name, update_json_index=False)
            for patch_path in sorted(_store.policy_patch_tasks_root(root).glob("*.json"), key=lambda item: item.as_posix().lower()):
                _sync_policy_patch_task_with_conn(conn, root, patch_path.stem, update_json_index=False)
            _sync_message_delete_audit_with_conn(conn, root)
            _sync_policy_confirmation_audit_with_conn(conn, root)
            _sync_system_workflow_events_with_conn(conn, root)
            _sync_reconcile_runs_with_conn(conn, root)
            _sync_ingress_requests_with_conn(conn, root)
            conn.commit()
            write_structure_file(root)
            _write_records_manifest(root)
            sessions = [dict(row) for row in conn.execute("SELECT session_id,status,agent_name,is_test_data,created_at,updated_at,last_message_at,message_count,work_record_count,last_message_preview FROM session_index ORDER BY last_message_at DESC, session_id DESC").fetchall()]
            analyses = [dict(row) for row in conn.execute("SELECT analysis_id,session_id,status,decision,updated_at,workflow_id,workflow_status,training_id,training_status FROM analysis_index ORDER BY updated_at DESC, analysis_id DESC").fetchall()]
            runs = [dict(row) for row in conn.execute("SELECT task_id,session_id,agent_name,status,created_at,updated_at FROM task_run_index ORDER BY created_at DESC, task_id DESC").fetchall()]
            patches = [dict(row) for row in conn.execute("SELECT substr(audit_key, length('policy_patch_task:') + 1) AS patch_task_id,status,session_id AS source_session_id,operator AS agent_name,created_at,created_at AS updated_at,'' AS completed_at,0 AS confirmation_audit_id,'' AS agents_version FROM audit_index WHERE audit_type='policy_patch_task' ORDER BY created_at DESC, audit_key DESC").fetchall()]
            _write_json_index(_store.sessions_index_path(root), sessions)
            _write_json_index(_store.analysis_index_path(root), analyses)
            _write_json_index(_store.runs_index_path(root), runs)
            _write_json_index(_store.policy_patch_index_path(root), patches)
        finally:
            conn.close()


