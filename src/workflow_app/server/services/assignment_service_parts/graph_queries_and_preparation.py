

def create_assignment_graph(cfg: Any, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_assignment_support_tables(cfg.root)
    operator = _default_assignment_operator(body.get("operator"))
    now_text = iso_ts(now_local())
    explicit_nodes = body.get("nodes")
    explicit_edges = body.get("edges")
    raw_nodes = explicit_nodes if isinstance(explicit_nodes, list) else []
    raw_edges = explicit_edges if isinstance(explicit_edges, list) else []
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        graph_payload = _normalize_graph_header(conn, body)
        external_request_id = str(graph_payload["external_request_id"] or "").strip()
        if external_request_id:
            existed = conn.execute(
                """
                SELECT ticket_id
                FROM assignment_graphs
                WHERE source_workflow=? AND external_request_id=?
                LIMIT 1
                """,
                (str(graph_payload["source_workflow"]), external_request_id),
            ).fetchone()
            if existed is not None:
                ticket_id = str(existed["ticket_id"] or "").strip()
                snapshot = _current_assignment_snapshot(conn, ticket_id)
                conn.commit()
                return {
                    "ticket_id": ticket_id,
                    "created": False,
                    "graph_overview": _graph_overview_payload(
                        snapshot["graph_row"],
                        metrics_summary=snapshot["metrics_summary"],
                        scheduler_state_payload=snapshot["scheduler"],
                    ),
                }
        ticket_id = assignment_ticket_id()
        node_payloads = [
            _normalize_node_payload(conn, cfg, raw if isinstance(raw, dict) else {}, node_id="")
            for raw in raw_nodes
        ]
        requested_node_ids = {str(node["node_id"]) for node in node_payloads}
        if len(requested_node_ids) != len(node_payloads):
            raise AssignmentCenterError(400, "node_id duplicated", "node_id_duplicated")
        collected_edges = _collect_edges_from_request(
            node_payloads=node_payloads,
            explicit_edges=[raw for raw in raw_edges if isinstance(raw, dict)],
        )
        _assert_no_cycles(requested_node_ids, collected_edges)
        _validate_node_ids_exist(
            all_node_ids=requested_node_ids,
            upstream_node_ids=[from_id for from_id, _to_id in collected_edges],
            downstream_node_ids=[to_id for _from_id, to_id in collected_edges],
        )
        conn.execute(
            """
            INSERT INTO assignment_graphs (
                ticket_id,graph_name,source_workflow,summary,review_mode,
                global_concurrency_limit,is_test_data,external_request_id,scheduler_state,pause_note,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ticket_id,
                str(graph_payload["graph_name"]),
                str(graph_payload["source_workflow"]),
                str(graph_payload["summary"]),
                str(graph_payload["review_mode"]),
                int(graph_payload["global_concurrency_limit"]),
                1 if graph_payload.get("is_test_data") else 0,
                external_request_id,
                "idle",
                "",
                now_text,
                now_text,
            ),
        )
        _insert_graph_nodes(conn, ticket_id=ticket_id, node_payloads=node_payloads, created_at=now_text)
        _insert_edges(conn, ticket_id=ticket_id, edges=collected_edges, created_at=now_text)
        _recompute_graph_statuses(conn, ticket_id)
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id="",
            action="create_graph",
            operator=operator,
            reason="create assignment graph",
            target_status="idle",
            detail={
                "graph_name": graph_payload["graph_name"],
                "source_workflow": graph_payload["source_workflow"],
                "node_count": len(node_payloads),
                "edge_count": len(collected_edges),
                "review_mode": graph_payload["review_mode"],
                "global_concurrency_limit": graph_payload["global_concurrency_limit"],
                "is_test_data": bool(graph_payload.get("is_test_data")),
                "external_request_id": external_request_id,
                "workspace_root": str(_assignment_workspace_root(cfg.root)),
            },
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(cfg.root, snapshot)
    return {
        "ticket_id": ticket_id,
        "created": True,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "created_node_ids": [str(node["node_id"]) for node in node_payloads],
        "created_edge_count": len(collected_edges),
        "audit_id": audit_id,
    }


def get_assignment_overview(root: Path, ticket_id_text: str, *, include_test_data: bool = True) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        _refresh_pause_state(conn, ticket_id, iso_ts(now_local()))
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    return {
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "priority_rules": {
            "ui_levels": ["P0", "P1", "P2", "P3"],
            "backend_levels": [0, 1, 2, 3],
            "highest_first": True,
            "tie_breaker": "created_at_asc",
        },
    }


def get_assignment_graph(
    root: Path,
    ticket_id_text: str,
    *,
    history_loaded: Any = 0,
    history_batch_size: Any = 12,
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    extra_loaded = _normalize_history_loaded(history_loaded)
    batch_size = _normalize_positive_int(
        history_batch_size,
        field="history_batch_size",
        default=12,
        minimum=1,
        maximum=50,
    )
    base_recent = 12
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        _refresh_pause_state(conn, ticket_id, iso_ts(now_local()))
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    nodes = list(snapshot["serialized_nodes"])
    completed_nodes = [
        node
        for node in nodes
        if str(node.get("status") or "").strip().lower() in {"succeeded", "failed"}
    ]
    completed_nodes.sort(
        key=lambda item: (
            str(item.get("completed_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("node_id") or ""),
        ),
        reverse=True,
    )
    non_completed_nodes = [
        node
        for node in nodes
        if str(node.get("status") or "").strip().lower() not in {"succeeded", "failed"}
    ]
    visible_completed = completed_nodes[: min(len(completed_nodes), base_recent + extra_loaded)]
    visible_ids = {
        str(node.get("node_id") or "").strip()
        for node in non_completed_nodes + visible_completed
        if str(node.get("node_id") or "").strip()
    }
    visible_edges = [
        edge
        for edge in snapshot["edges"]
        if str(edge.get("from_node_id") or "").strip() in visible_ids
        and str(edge.get("to_node_id") or "").strip() in visible_ids
    ]
    remaining = max(0, len(completed_nodes) - len(visible_completed))
    visible_nodes = non_completed_nodes + visible_completed
    visible_nodes.sort(
        key=lambda item: (
            0
            if str(item.get("status") or "").strip().lower() in {"running", "succeeded", "failed"}
            else 1,
            int(item.get("priority") or 0),
            str(item.get("completed_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("node_id") or ""),
        )
    )
    return {
        "ticket_id": ticket_id,
        "graph": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "nodes": visible_nodes,
        "edges": visible_edges,
        "node_catalog": [
            {
                "node_id": str(node.get("node_id") or "").strip(),
                "node_name": str(node.get("node_name") or "").strip(),
                "status": str(node.get("status") or "").strip().lower(),
                "priority": int(node.get("priority") or 0),
                "priority_label": assignment_priority_label(node.get("priority")),
            }
            for node in nodes
        ],
        "metrics_summary": snapshot["metrics_summary"],
        "priority_rules": {
            "ui_levels": ["P0", "P1", "P2", "P3"],
            "backend_levels": [0, 1, 2, 3],
            "highest_first": True,
            "tie_breaker": "created_at_asc",
        },
        "history": {
            "base_recent_count": min(base_recent, len(completed_nodes)),
            "loaded_extra_count": max(0, len(visible_completed) - min(base_recent, len(completed_nodes))),
            "next_history_loaded": extra_loaded + batch_size,
            "remaining_completed_count": remaining,
            "has_more": remaining > 0,
            "batch_size": batch_size,
        },
    }


def get_assignment_scheduler_state(root: Path, ticket_id_text: str, *, include_test_data: bool = True) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        graph_row = _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        _refresh_pause_state(conn, ticket_id, iso_ts(now_local()))
        graph_row = _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        system_limit, settings_updated_at = _get_global_concurrency_limit(conn)
        counts = _running_counts(conn, ticket_id=ticket_id)
        conn.commit()
    finally:
        conn.close()
    graph_limit = int(graph_row["global_concurrency_limit"] or 0)
    return {
        "ticket_id": ticket_id,
        "state": str(graph_row["scheduler_state"] or "").strip().lower(),
        "state_text": _scheduler_state_text(graph_row["scheduler_state"]),
        "running_agent_count": int(counts["running_agent_count"]),
        "system_running_agent_count": int(counts["system_running_agent_count"]),
        "graph_running_node_count": int(counts["graph_running_node_count"]),
        "system_running_node_count": int(counts["system_running_node_count"]),
        "global_concurrency_limit": int(system_limit),
        "graph_concurrency_limit": graph_limit,
        "effective_concurrency_limit": _graph_effective_limit(
            graph_limit=graph_limit,
            system_limit=system_limit,
        ),
        "pause_note": str(graph_row["pause_note"] or "").strip(),
        "settings_updated_at": settings_updated_at,
    }


def get_assignment_status_detail(
    root: Path,
    ticket_id_text: str,
    *,
    node_id_text: str = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        _refresh_pause_state(conn, ticket_id, iso_ts(now_local()))
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        if not snapshot["nodes"]:
            selected_node = {}
        else:
            selected_node = snapshot["node_map_by_id"].get(node_id) or (snapshot["nodes"][0] if snapshot["nodes"] else {})
        run_rows = (
            _load_assignment_runs(
                conn,
                ticket_id=ticket_id,
                node_id=str((selected_node or {}).get("node_id") or "").strip(),
                limit=5,
            )
            if selected_node
            else []
        )
        audit_rows = conn.execute(
            """
            SELECT audit_id,action,operator,reason,target_status,ref,created_at,detail_json
            FROM assignment_audit_log
            WHERE ticket_id=?
              AND (?='' OR node_id=? OR COALESCE(node_id,'')='')
            ORDER BY created_at DESC, audit_id DESC
            LIMIT 12
            """,
            (ticket_id, node_id, node_id),
        ).fetchall()
        conn.commit()
    finally:
        conn.close()
    selected_serialized = (
        _serialize_node(
            selected_node,
            node_map_by_id=snapshot["node_map_by_id"],
            upstream_map=snapshot["upstream_map"],
            downstream_map=snapshot["downstream_map"],
        )
        if selected_node
        else {}
    )
    selected_status = str(selected_serialized.get("status") or "").strip().lower()
    available_actions: list[str] = []
    if selected_status == "running":
        available_actions.extend(["mark-success", "mark-failed"])
    if selected_status == "failed":
        available_actions.extend(["rerun", "override-status"])
    if selected_status:
        available_actions.append("deliver-artifact")
    if list(selected_serialized.get("artifact_paths") or []):
        available_actions.append("view-artifact")
    if selected_status and selected_status != "running":
        available_actions.append("delete")
    audit_refs = []
    for row in audit_rows:
        detail = _json_load(row["detail_json"], {})
        if not isinstance(detail, dict):
            detail = {}
        audit_refs.append(
            {
                "audit_id": str(row["audit_id"] or "").strip(),
                "action": str(row["action"] or "").strip(),
                "operator": str(row["operator"] or "").strip(),
                "reason": str(row["reason"] or "").strip(),
                "target_status": str(row["target_status"] or "").strip(),
                "ref": str(row["ref"] or "").strip(),
                "created_at": str(row["created_at"] or "").strip(),
                "detail": detail,
            }
        )
    run_summaries = [_assignment_run_summary(root, row, include_content=index == 0) for index, row in enumerate(run_rows)]
    latest_run = run_summaries[0] if run_summaries else {}
    return {
        "ticket_id": ticket_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "selected_node": selected_serialized,
        "blocking_reasons": list(selected_serialized.get("blocking_reasons") or []),
        "available_actions": available_actions,
        "audit_refs": audit_refs,
        "execution_chain": {
            "poll_mode": assignment_execution_refresh_mode(),
            "poll_interval_ms": DEFAULT_ASSIGNMENT_EXECUTION_POLL_INTERVAL_MS,
            "latest_run": latest_run,
            "recent_runs": run_summaries,
        },
    }


def _deliver_assignment_artifact_locked(
    root: Path,
    conn: sqlite3.Connection,
    *,
    ticket_id: str,
    node_id: str,
    operator_text: str,
    artifact_label: str,
    delivery_note: str,
    artifact_body: str,
    now_text: str,
) -> tuple[list[str], str]:
    snapshot_before = _current_assignment_snapshot(conn, ticket_id)
    selected_node = snapshot_before["node_map_by_id"].get(node_id) or {}
    if not selected_node:
        raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found")
    artifact_file_paths = _node_artifact_file_paths(root, selected_node)
    artifact_paths: list[str] = []
    payload = artifact_body or _artifact_delivery_markdown(
        selected_node,
        delivered_at=now_text,
        operator=operator_text,
        artifact_label=artifact_label,
        delivery_note=delivery_note,
    )
    for path in artifact_file_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        artifact_paths.append(path.as_posix())
    artifact_structure_paths = _write_artifact_structure_files(
        root,
        node=selected_node,
        artifact_file_paths=artifact_file_paths,
        delivered_at=now_text,
        operator=operator_text,
    )
    conn.execute(
        """
        UPDATE assignment_nodes
        SET artifact_delivery_status='delivered',
            artifact_delivered_at=?,
            artifact_paths_json=?,
            updated_at=?
        WHERE ticket_id=? AND node_id=?
        """,
        (
            now_text,
            json.dumps(artifact_paths, ensure_ascii=False),
            now_text,
            ticket_id,
            node_id,
        ),
    )
    audit_id = _write_assignment_audit(
        conn,
        ticket_id=ticket_id,
        node_id=node_id,
        action="deliver_artifact",
        operator=operator_text,
        reason=delivery_note or "deliver assignment artifact",
        target_status="delivered",
        detail={
            "artifact_label": artifact_label,
            "delivery_mode": str(selected_node.get("delivery_mode") or "none").strip().lower(),
            "delivery_receiver_agent_id": str(selected_node.get("delivery_receiver_agent_id") or "").strip(),
            "artifact_paths": artifact_paths,
            "artifact_structure_paths": artifact_structure_paths,
        },
        created_at=now_text,
    )
    return artifact_paths, audit_id


def deliver_assignment_artifact(
    root: Path,
    *,
    ticket_id_text: str,
    node_id_text: str,
    operator: str,
    artifact_label: Any = "",
    delivery_note: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    operator_text = _default_assignment_operator(operator)
    label_text = _normalize_text(artifact_label, field="artifact_label", required=False, max_len=200)
    note_text = _normalize_text(delivery_note, field="delivery_note", required=False, max_len=4000)
    now_text = iso_ts(now_local())
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_ticket_node_row_visible(conn, ticket_id, node_id, include_test_data=include_test_data)
        snapshot_before = _current_assignment_snapshot(conn, ticket_id)
        selected_node = snapshot_before["node_map_by_id"].get(node_id) or {}
        if not selected_node:
            raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found")
        artifact_name = label_text or (
            str(selected_node.get("expected_artifact") or "").strip()
            or str(selected_node.get("node_name") or "").strip()
            or str(selected_node.get("node_id") or "").strip()
            or "任务产物"
        )
        payload = _artifact_delivery_markdown(
            selected_node,
            delivered_at=now_text,
            operator=operator_text,
            artifact_label=artifact_name,
            delivery_note=note_text,
        )
        artifact_paths, audit_id = _deliver_assignment_artifact_locked(
            root,
            conn,
            ticket_id=ticket_id,
            node_id=node_id,
            operator_text=operator_text,
            artifact_label=artifact_name,
            delivery_note=note_text,
            artifact_body=payload,
            now_text=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(root, snapshot)
    delivered_node = next(
        (node for node in snapshot["serialized_nodes"] if str(node.get("node_id") or "").strip() == node_id),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": delivered_node,
        "artifact_paths": artifact_paths,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }


def read_assignment_artifact_preview(
    root: Path,
    *,
    ticket_id_text: str,
    node_id_text: str,
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    selected_node = snapshot["node_map_by_id"].get(node_id) or {}
    if not selected_node:
        raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found")
    artifact_paths = list(selected_node.get("artifact_paths") or [])
    if not artifact_paths:
        raise AssignmentCenterError(404, "artifact not delivered", "artifact_not_delivered")
    artifact_root = _assignment_artifact_root(root)
    path = Path(str(artifact_paths[0])).resolve(strict=False)
    if not path_in_scope(path, artifact_root):
        raise AssignmentCenterError(400, "artifact path out of root", "artifact_path_out_of_root")
    if not path.exists() or not path.is_file():
        raise AssignmentCenterError(404, "artifact file missing", "artifact_file_missing")
    return {
        "ticket_id": ticket_id,
        "node_id": node_id,
        "path": path.as_posix(),
        "content": path.read_text(encoding="utf-8"),
        "content_type": "text/plain; charset=utf-8",
    }


def create_assignment_node(
    cfg: Any,
    ticket_id_text: str,
    body: dict[str, Any],
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    _ensure_assignment_support_tables(cfg.root)
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator = _default_assignment_operator(body.get("operator"))
    now_text = iso_ts(now_local())
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        node_payload = _normalize_node_payload(conn, cfg, body, node_id="")
        existing_nodes = _load_nodes(conn, ticket_id)
        existing_node_ids = {str(node["node_id"]) for node in existing_nodes}
        if str(node_payload["node_id"]) in existing_node_ids:
            raise AssignmentCenterError(409, "node_id duplicated", "node_id_duplicated")
        _validate_node_ids_exist(
            all_node_ids=existing_node_ids,
            upstream_node_ids=list(node_payload["upstream_node_ids"]),
            downstream_node_ids=list(node_payload["downstream_node_ids"]),
        )
        existing_edges = [
            (
                str(edge.get("from_node_id") or "").strip(),
                str(edge.get("to_node_id") or "").strip(),
            )
            for edge in _load_edges(conn, ticket_id)
        ]
        new_edges = _collect_edges_from_request(node_payloads=[node_payload], explicit_edges=[])
        _assert_no_cycles(existing_node_ids | {str(node_payload["node_id"])}, existing_edges + new_edges)
        _insert_graph_nodes(conn, ticket_id=ticket_id, node_payloads=[node_payload], created_at=now_text)
        _insert_edges(conn, ticket_id=ticket_id, edges=new_edges, created_at=now_text)
        _recompute_graph_statuses(conn, ticket_id)
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id=str(node_payload["node_id"]),
            action="create_node",
            operator=operator,
            reason="create assignment node",
            target_status="pending",
            detail={
                "node_name": node_payload["node_name"],
                "assigned_agent_id": node_payload["assigned_agent_id"],
                "priority": int(node_payload["priority"]),
                "priority_label": assignment_priority_label(node_payload["priority"]),
                "upstream_node_ids": list(node_payload["upstream_node_ids"]),
                "downstream_node_ids": list(node_payload["downstream_node_ids"]),
                "expected_artifact": node_payload["expected_artifact"],
                "delivery_mode": node_payload["delivery_mode"],
                "delivery_receiver_agent_id": node_payload["delivery_receiver_agent_id"],
                "workspace_root": str(_assignment_workspace_root(cfg.root)),
            },
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(cfg.root, snapshot)
    created_node = next(
        (
            node
            for node in snapshot["serialized_nodes"]
            if str(node.get("node_id") or "").strip() == str(node_payload["node_id"])
        ),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": created_node,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "audit_id": audit_id,
    }


def create_assignment_nodes_batch(
    cfg: Any,
    ticket_id_text: str,
    body: dict[str, Any],
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    _ensure_assignment_support_tables(cfg.root)
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator = _default_assignment_operator((body or {}).get("operator"))
    raw_nodes = (body or {}).get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise AssignmentCenterError(400, "nodes required", "assignment_nodes_required")
    now_text = iso_ts(now_local())
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        node_payloads = [
            _normalize_node_payload(conn, cfg, raw if isinstance(raw, dict) else {}, node_id="")
            for raw in raw_nodes
        ]
        existing_nodes = _load_nodes(conn, ticket_id)
        existing_node_ids = {str(node["node_id"]) for node in existing_nodes}
        requested_node_ids = [str(node["node_id"]) for node in node_payloads]
        if len(set(requested_node_ids)) != len(requested_node_ids):
            raise AssignmentCenterError(409, "node_id duplicated", "node_id_duplicated")
        duplicated_node_ids = sorted(node_id for node_id in requested_node_ids if node_id in existing_node_ids)
        if duplicated_node_ids:
            raise AssignmentCenterError(
                409,
                "node_id duplicated",
                "node_id_duplicated",
                {"node_ids": duplicated_node_ids},
            )
        existing_edges = [
            (
                str(edge.get("from_node_id") or "").strip(),
                str(edge.get("to_node_id") or "").strip(),
            )
            for edge in _load_edges(conn, ticket_id)
        ]
        new_edges = _collect_edges_from_request(node_payloads=node_payloads, explicit_edges=[])
        all_node_ids = existing_node_ids | set(requested_node_ids)
        _validate_node_ids_exist(
            all_node_ids=all_node_ids,
            upstream_node_ids=[from_id for from_id, _to_id in new_edges],
            downstream_node_ids=[to_id for _from_id, to_id in new_edges],
        )
        _assert_no_cycles(all_node_ids, existing_edges + new_edges)
        _insert_graph_nodes(conn, ticket_id=ticket_id, node_payloads=node_payloads, created_at=now_text)
        _insert_edges(conn, ticket_id=ticket_id, edges=new_edges, created_at=now_text)
        _recompute_graph_statuses(conn, ticket_id)
        audit_ids: list[str] = []
        for node_payload in node_payloads:
            audit_ids.append(
                _write_assignment_audit(
                    conn,
                    ticket_id=ticket_id,
                    node_id=str(node_payload["node_id"]),
                    action="create_node",
                    operator=operator,
                    reason="create assignment node",
                    target_status="pending",
                    detail={
                        "node_name": node_payload["node_name"],
                        "assigned_agent_id": node_payload["assigned_agent_id"],
                        "priority": int(node_payload["priority"]),
                        "priority_label": assignment_priority_label(node_payload["priority"]),
                        "upstream_node_ids": list(node_payload["upstream_node_ids"]),
                        "downstream_node_ids": list(node_payload["downstream_node_ids"]),
                        "expected_artifact": node_payload["expected_artifact"],
                        "delivery_mode": node_payload["delivery_mode"],
                        "delivery_receiver_agent_id": node_payload["delivery_receiver_agent_id"],
                        "workspace_root": str(_assignment_workspace_root(cfg.root)),
                        "created_via": "batch",
                    },
                    created_at=now_text,
                )
            )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(cfg.root, snapshot)
    created_node_map = {
        str(node.get("node_id") or "").strip(): dict(node)
        for node in list(snapshot.get("serialized_nodes") or [])
        if str(node.get("node_id") or "").strip()
    }
    created_nodes = [
        created_node_map.get(node_id, {})
        for node_id in requested_node_ids
        if created_node_map.get(node_id, {})
    ]
    return {
        "ticket_id": ticket_id,
        "nodes": created_nodes,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "audit_ids": audit_ids,
    }


def _prepare_assignment_execution_run(
    conn: sqlite3.Connection,
    *,
    root: Path,
    ticket_id: str,
    node_id: str,
    now_text: str,
) -> dict[str, Any]:
    snapshot = _current_assignment_snapshot(conn, ticket_id)
    graph_row = snapshot["graph_row"]
    serialized_node = next(
        (
            node
            for node in snapshot["serialized_nodes"]
            if str(node.get("node_id") or "").strip() == node_id
        ),
        {},
    )
    if not serialized_node:
        raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found", {"node_id": node_id})
    upstream_nodes = [
        snapshot["node_map_by_id"].get(str(item.get("node_id") or "").strip()) or {}
        for item in list(serialized_node.get("upstream_nodes") or [])
    ]
    workspace_path = _resolve_assignment_workspace_path(
        conn,
        root,
        agent_id=str(serialized_node.get("assigned_agent_id") or "").strip(),
    )
    settings = _assignment_execution_settings_from_conn(conn)
    provider = _normalize_execution_provider(settings.get("execution_provider"))
    prompt_text = _build_assignment_execution_prompt(
        graph_row=graph_row,
        node=serialized_node,
        upstream_nodes=upstream_nodes,
        workspace_path=workspace_path,
    )
    command, command_summary = _build_assignment_execution_command(
        provider=provider,
        codex_command_path=str(settings.get("codex_command_path") or ""),
        command_template=str(settings.get("command_template") or ""),
        workspace_path=workspace_path,
    )
    run_id = assignment_run_id()
    files = _assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    _write_assignment_run_text(files["prompt"], prompt_text)
    _write_assignment_run_text(files["stdout"], "")
    _write_assignment_run_text(files["stderr"], "")
    _write_assignment_run_text(files["events"], "")
    _append_assignment_run_event(
        files["events"],
        event_type="dispatch",
        message="调度器已创建真实执行批次。",
        created_at=now_text,
        detail={"command_summary": command_summary},
    )
    prompt_ref = _path_for_ui(root, files["prompt"])
    stdout_ref = _path_for_ui(root, files["stdout"])
    stderr_ref = _path_for_ui(root, files["stderr"])
    result_ref = _path_for_ui(root, files["result"])
    _insert_assignment_execution_run(
        conn,
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider=provider,
        workspace_path=workspace_path,
        command_summary=command_summary,
        prompt_ref=prompt_ref,
        stdout_ref=stdout_ref,
        stderr_ref=stderr_ref,
        result_ref=result_ref,
        latest_event="已创建运行批次，等待 provider 启动。",
        started_at=now_text,
        created_at=now_text,
    )
    return {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "node_id": node_id,
        "provider": provider,
        "workspace_path": workspace_path,
        "prompt_text": prompt_text,
        "command": command,
        "command_summary": command_summary,
        "files": files,
        "node": serialized_node,
    }
