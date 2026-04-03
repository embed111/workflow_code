from __future__ import annotations


ASSIGNMENT_GLOBAL_GRAPH_TICKET_SETTING_KEY = "workflow_ui_global_graph_ticket_id"


def _assignment_is_workflow_ui_global_graph_record(task_record: dict[str, Any]) -> bool:
    if not isinstance(task_record, dict) or not task_record:
        return False
    if bool(task_record.get("is_test_data")):
        return False
    if str(task_record.get("record_state") or "active").strip().lower() == "deleted":
        return False
    return str(task_record.get("source_workflow") or "").strip() == ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW


def _assignment_is_workflow_ui_global_graph_payload(graph_payload: dict[str, Any]) -> bool:
    if not isinstance(graph_payload, dict) or not graph_payload:
        return False
    if bool(graph_payload.get("is_test_data")):
        return False
    return str(graph_payload.get("source_workflow") or "").strip() == ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW


def _assignment_workflow_ui_global_graph_candidates(root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for ticket_id in _assignment_list_ticket_ids(root):
        try:
            task_record = _assignment_load_task_record(root, ticket_id)
        except AssignmentCenterError:
            continue
        if not _assignment_is_workflow_ui_global_graph_record(task_record):
            continue
        active_nodes = _assignment_active_node_records(
            _assignment_load_node_records(root, ticket_id, include_deleted=True)
        )
        metrics_summary = _graph_metrics(active_nodes)
        candidates.append(
            {
                "ticket_id": str(task_record.get("ticket_id") or "").strip(),
                "task_record": dict(task_record),
                "active_node_count": len(active_nodes),
                "executed_count": int(metrics_summary.get("executed_count") or 0),
                "unexecuted_count": int(metrics_summary.get("unexecuted_count") or 0),
            }
        )
    return candidates


def _assignment_workflow_ui_global_graph_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    task_record = dict(candidate.get("task_record") or {})
    external_request_id = str(task_record.get("external_request_id") or "").strip()
    graph_name = str(task_record.get("graph_name") or "").strip()
    return (
        0 if external_request_id == ASSIGNMENT_GLOBAL_GRAPH_REQUEST_ID else 1,
        0 if graph_name == ASSIGNMENT_GLOBAL_GRAPH_NAME else 1,
        -int(candidate.get("active_node_count") or 0),
        -int(candidate.get("executed_count") or 0),
        -int(candidate.get("unexecuted_count") or 0),
        str(task_record.get("updated_at") or ""),
        str(task_record.get("created_at") or ""),
        str(task_record.get("ticket_id") or ""),
    )


def _assignment_bound_workflow_ui_global_graph_ticket(root: Path) -> str:
    _ensure_assignment_support_tables(root)
    now_text = iso_ts(now_local())
    conn = connect_db(root)
    try:
        ticket_id, _updated_at = _get_assignment_setting_text(
            conn,
            key=ASSIGNMENT_GLOBAL_GRAPH_TICKET_SETTING_KEY,
            default_value="",
            now_text=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    return safe_token(ticket_id, "", 160)


def _assignment_set_bound_workflow_ui_global_graph_ticket(root: Path, ticket_id: str) -> str:
    _ensure_assignment_support_tables(root)
    now_text = iso_ts(now_local())
    ticket_text = safe_token(str(ticket_id or ""), "", 160)
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _set_assignment_setting_text(
            conn,
            key=ASSIGNMENT_GLOBAL_GRAPH_TICKET_SETTING_KEY,
            value=ticket_text,
            now_text=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    return ticket_text


def _assignment_normalize_workflow_ui_global_graph_header(root: Path, ticket_id: str) -> None:
    ticket_text = safe_token(str(ticket_id or ""), "", 160)
    if not ticket_text:
        return
    try:
        task_record = _assignment_load_task_record(root, ticket_text)
    except AssignmentCenterError:
        return
    if not _assignment_is_workflow_ui_global_graph_record(task_record):
        return
    changed = False
    now_text = iso_ts(now_local())
    if str(task_record.get("graph_name") or "").strip() != ASSIGNMENT_GLOBAL_GRAPH_NAME:
        task_record["graph_name"] = ASSIGNMENT_GLOBAL_GRAPH_NAME
        changed = True
    if str(task_record.get("source_workflow") or "").strip() != ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW:
        task_record["source_workflow"] = ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW
        changed = True
    if str(task_record.get("summary") or "").strip() != ASSIGNMENT_GLOBAL_GRAPH_SUMMARY:
        task_record["summary"] = ASSIGNMENT_GLOBAL_GRAPH_SUMMARY
        changed = True
    if str(task_record.get("external_request_id") or "").strip() != ASSIGNMENT_GLOBAL_GRAPH_REQUEST_ID:
        task_record["external_request_id"] = ASSIGNMENT_GLOBAL_GRAPH_REQUEST_ID
        changed = True
    if changed:
        task_record["updated_at"] = now_text
        _assignment_write_task_record(root, task_record)
        sync_assignment_task_bundle_index(root, ticket_text)


def _assignment_ensure_workflow_ui_global_graph_ticket(root: Path) -> str:
    bound_ticket_id = _assignment_bound_workflow_ui_global_graph_ticket(root)
    candidates = _assignment_workflow_ui_global_graph_candidates(root)
    if bound_ticket_id:
        for candidate in candidates:
            if str(candidate.get("ticket_id") or "").strip() == bound_ticket_id:
                _assignment_normalize_workflow_ui_global_graph_header(root, bound_ticket_id)
                return bound_ticket_id
    if not candidates:
        if bound_ticket_id:
            _assignment_set_bound_workflow_ui_global_graph_ticket(root, "")
        return ""
    candidates.sort(key=_assignment_workflow_ui_global_graph_sort_key)
    canonical_ticket_id = safe_token(str(candidates[0].get("ticket_id") or ""), "", 160)
    if not canonical_ticket_id:
        return ""
    _assignment_set_bound_workflow_ui_global_graph_ticket(root, canonical_ticket_id)
    _assignment_normalize_workflow_ui_global_graph_header(root, canonical_ticket_id)
    return canonical_ticket_id


def _assignment_resolve_graph_ticket_id(root: Path, ticket_id: str) -> str:
    requested_ticket_id = safe_token(str(ticket_id or ""), "", 160)
    if not requested_ticket_id:
        return ""
    canonical_ticket_id = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    if not canonical_ticket_id or requested_ticket_id == canonical_ticket_id:
        return requested_ticket_id
    try:
        task_record = _assignment_load_task_record(root, requested_ticket_id)
    except AssignmentCenterError:
        return requested_ticket_id
    if (
        not bool(task_record.get("is_test_data"))
        and str(task_record.get("source_workflow") or "").strip() == ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW
    ):
        return canonical_ticket_id
    return requested_ticket_id


def _assignment_is_hidden_workflow_ui_graph_ticket(
    root: Path,
    ticket_id: str,
    *,
    ticket_record: dict[str, Any] | None = None,
    canonical_ticket_id: str = "",
) -> bool:
    current_ticket_id = safe_token(str(ticket_id or ""), "", 160)
    if not current_ticket_id:
        return False
    task_record = dict(ticket_record or {})
    if not task_record:
        try:
            task_record = _assignment_load_task_record(root, current_ticket_id)
        except AssignmentCenterError:
            return False
    if not _assignment_is_workflow_ui_global_graph_record(task_record):
        return False
    canonical = safe_token(str(canonical_ticket_id or ""), "", 160) or _assignment_ensure_workflow_ui_global_graph_ticket(root)
    return bool(canonical and current_ticket_id != canonical)


def _assignment_bind_workflow_ui_global_graph_ticket(root: Path, ticket_id: str) -> str:
    ticket_text = _assignment_set_bound_workflow_ui_global_graph_ticket(root, ticket_id)
    if ticket_text:
        _assignment_normalize_workflow_ui_global_graph_header(root, ticket_text)
    return ticket_text
