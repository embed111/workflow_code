

def delete_assignment_node(
    root: Path,
    *,
    ticket_id_text: str,
    node_id_text: str,
    operator: str,
    reason: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    operator_text = _default_assignment_operator(operator)
    reason_text = _normalize_text(reason, field="reason", required=False, max_len=1000)
    now_text = iso_ts(now_local())
    deleted_node_serialized: dict[str, Any] = {}
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_ticket_node_row_visible(conn, ticket_id, node_id, include_test_data=include_test_data)
        snapshot_before = _current_assignment_snapshot(conn, ticket_id)
        deleted_node_serialized = next(
            (
                node
                for node in list(snapshot_before.get("serialized_nodes") or [])
                if str(node.get("node_id") or "").strip() == node_id
            ),
            {},
        )
        current_status = str(deleted_node_serialized.get("status") or "").strip().lower()
        if current_status == "running":
            raise AssignmentCenterError(
                409,
                "running node cannot be deleted",
                "assignment_delete_running_node_blocked",
                {"node_id": node_id},
            )
        bridge_plan = _plan_bridge_edges_after_delete(
            node_id=node_id,
            nodes=list(snapshot_before.get("nodes") or []),
            edges=list(snapshot_before.get("edges") or []),
        )
        removed_edge_count = int(
            conn.execute(
                """
                DELETE FROM assignment_edges
                WHERE ticket_id=? AND (from_node_id=? OR to_node_id=?)
                """,
                (ticket_id, node_id, node_id),
            ).rowcount
            or 0
        )
        conn.execute(
            "DELETE FROM assignment_nodes WHERE ticket_id=? AND node_id=?",
            (ticket_id, node_id),
        )
        bridge_edges = [
            (
                str(item.get("from_node_id") or "").strip(),
                str(item.get("to_node_id") or "").strip(),
            )
            for item in list(bridge_plan.get("bridge_added") or [])
            if str(item.get("from_node_id") or "").strip()
            and str(item.get("to_node_id") or "").strip()
        ]
        if bridge_edges:
            _insert_edges(conn, ticket_id=ticket_id, edges=bridge_edges, created_at=now_text)
        _recompute_graph_statuses(conn, ticket_id)
        remaining_nodes = _load_nodes(conn, ticket_id)
        if not remaining_nodes:
            conn.execute(
                """
                UPDATE assignment_graphs
                SET scheduler_state='idle',pause_note='',updated_at=?
                WHERE ticket_id=?
                """,
                (now_text, ticket_id),
            )
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id=node_id,
            action="delete_node",
            operator=operator_text,
            reason=reason_text or "delete assignment node",
            target_status="deleted",
            detail={
                "removed_edge_count": removed_edge_count,
                "deleted_node": {
                    "node_id": str(deleted_node_serialized.get("node_id") or "").strip(),
                    "node_name": str(deleted_node_serialized.get("node_name") or "").strip(),
                    "status": current_status,
                },
                "bridge_summary": bridge_plan,
            },
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _persist_assignment_workspace_node(
        root,
        node=deleted_node_serialized,
        record_state="deleted",
        audit_id=audit_id,
        extra={
            "delete_action": "delete_node",
            "deleted_at": now_text,
            "delete_reason": reason_text or "delete assignment node",
            "bridge_summary": bridge_plan,
        },
    )
    _sync_assignment_workspace_snapshot(root, snapshot)
    return {
        "ticket_id": ticket_id,
        "deleted_node_id": node_id,
        "removed_edge_count": removed_edge_count,
        "bridge_summary": bridge_plan,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }


def _ensure_ticket_node_row(conn: sqlite3.Connection, ticket_id: str, node_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            node_id,ticket_id,node_name,assigned_agent_id,status,priority,
            completed_at,success_reason,result_ref,failure_reason,created_at,updated_at
        FROM assignment_nodes
        WHERE ticket_id=? AND node_id=?
        LIMIT 1
        """,
        (ticket_id, node_id),
    ).fetchone()
    if row is None:
        raise AssignmentCenterError(
            404,
            "assignment node not found",
            "assignment_node_not_found",
            {"ticket_id": ticket_id, "node_id": node_id},
        )
    return row


def _ensure_ticket_node_row_visible(
    conn: sqlite3.Connection,
    ticket_id: str,
    node_id: str,
    *,
    include_test_data: bool,
) -> sqlite3.Row:
    _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
    return _ensure_ticket_node_row(conn, ticket_id, node_id)


def mark_assignment_node_success(
    root: Path,
    *,
    ticket_id_text: str,
    node_id_text: str,
    success_reason: Any,
    result_ref: Any = "",
    operator: str,
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    success_text = _normalize_text(success_reason, field="success_reason", required=True, max_len=1000)
    result_ref_text = _normalize_text(result_ref, field="result_ref", required=False, max_len=500)
    operator_text = _default_assignment_operator(operator)
    now_text = iso_ts(now_local())
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_ticket_node_row_visible(conn, ticket_id, node_id, include_test_data=include_test_data)
        snapshot_before = _current_assignment_snapshot(conn, ticket_id)
        selected_node = snapshot_before["node_map_by_id"].get(node_id) or _row_dict(row)
        current_status = str(row["status"] or "").strip().lower()
        if current_status != "running":
            raise AssignmentCenterError(
                409,
                "mark-success only allowed when node is running",
                "mark_success_status_invalid",
                {"current_status": current_status},
            )
        if str(selected_node.get("artifact_delivery_status") or "").strip().lower() != "delivered":
            raise AssignmentCenterError(
                409,
                "artifact delivery required before success",
                "artifact_delivery_required",
                {"artifact_delivery_status": str(selected_node.get("artifact_delivery_status") or "pending")},
            )
        cancelled_run_ids = _cancel_active_assignment_runs(
            conn,
            ticket_id=ticket_id,
            node_id=node_id,
            reason="任务被人工标记成功，已终止当前真实执行批次。",
            now_text=now_text,
        )
        conn.execute(
            """
            UPDATE assignment_nodes
            SET status='succeeded',
                completed_at=?,
                success_reason=?,
                result_ref=?,
                failure_reason='',
                updated_at=?
            WHERE ticket_id=? AND node_id=?
            """,
            (now_text, success_text, result_ref_text, now_text, ticket_id, node_id),
        )
        _recompute_graph_statuses(conn, ticket_id)
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id=node_id,
            action="mark_success",
            operator=operator_text,
            reason=success_text,
            target_status="succeeded",
            detail={"result_ref": result_ref_text, "cancelled_run_ids": cancelled_run_ids},
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(root, snapshot)
    selected_node = next(
        (node for node in snapshot["serialized_nodes"] if str(node.get("node_id") or "").strip() == node_id),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": selected_node,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }


def mark_assignment_node_failed(
    root: Path,
    *,
    ticket_id_text: str,
    node_id_text: str,
    failure_reason: Any,
    operator: str,
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    failure_text = _normalize_text(failure_reason, field="failure_reason", required=True, max_len=1000)
    operator_text = _default_assignment_operator(operator)
    now_text = iso_ts(now_local())
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_ticket_node_row_visible(conn, ticket_id, node_id, include_test_data=include_test_data)
        current_status = str(row["status"] or "").strip().lower()
        if current_status != "running":
            raise AssignmentCenterError(
                409,
                "mark-failed only allowed when node is running",
                "mark_failed_status_invalid",
                {"current_status": current_status},
            )
        cancelled_run_ids = _cancel_active_assignment_runs(
            conn,
            ticket_id=ticket_id,
            node_id=node_id,
            reason="任务被人工标记失败，已终止当前真实执行批次。",
            now_text=now_text,
        )
        conn.execute(
            """
            UPDATE assignment_nodes
            SET status='failed',
                completed_at=?,
                success_reason='',
                result_ref='',
                failure_reason=?,
                updated_at=?
            WHERE ticket_id=? AND node_id=?
            """,
            (now_text, failure_text, now_text, ticket_id, node_id),
        )
        _recompute_graph_statuses(conn, ticket_id)
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id=node_id,
            action="mark_failed",
            operator=operator_text,
            reason=failure_text,
            target_status="failed",
            detail={"cancelled_run_ids": cancelled_run_ids},
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(root, snapshot)
    selected_node = next(
        (node for node in snapshot["serialized_nodes"] if str(node.get("node_id") or "").strip() == node_id),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": selected_node,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }


def rerun_assignment_node(
    root: Path,
    *,
    ticket_id_text: str,
    node_id_text: str,
    operator: str,
    reason: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    operator_text = _default_assignment_operator(operator)
    reason_text = _normalize_text(reason, field="reason", required=False, max_len=500)
    now_text = iso_ts(now_local())
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_ticket_node_row_visible(conn, ticket_id, node_id, include_test_data=include_test_data)
        current_status = str(row["status"] or "").strip().lower()
        if current_status != "failed":
            raise AssignmentCenterError(
                409,
                "rerun only allowed for failed node",
                "rerun_status_invalid",
                {"current_status": current_status},
            )
        conn.execute(
            """
            UPDATE assignment_nodes
            SET status='pending',
                completed_at='',
                success_reason='',
                result_ref='',
                failure_reason='',
                artifact_delivery_status='pending',
                artifact_delivered_at='',
                artifact_paths_json='[]',
                updated_at=?
            WHERE ticket_id=? AND node_id=?
            """,
            (now_text, ticket_id, node_id),
        )
        _recompute_graph_statuses(conn, ticket_id)
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id=node_id,
            action="rerun",
            operator=operator_text,
            reason=reason_text or "rerun failed node",
            target_status="pending",
            detail={},
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(root, snapshot)
    selected_node = next(
        (node for node in snapshot["serialized_nodes"] if str(node.get("node_id") or "").strip() == node_id),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": selected_node,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }


def override_assignment_node_status(
    root: Path,
    *,
    ticket_id_text: str,
    node_id_text: str,
    target_status: Any,
    operator: str,
    reason: Any,
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    next_status = _normalize_status(target_status, field="target_status")
    operator_text = _default_assignment_operator(operator)
    reason_text = _normalize_text(reason, field="reason", required=True, max_len=1000)
    now_text = iso_ts(now_local())
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_ticket_node_row_visible(conn, ticket_id, node_id, include_test_data=include_test_data)
        snapshot_before = _current_assignment_snapshot(conn, ticket_id)
        selected_node = snapshot_before["node_map_by_id"].get(node_id) or _row_dict(row)
        current_status = str(selected_node.get("status") or row["status"] or "").strip().lower()
        if current_status != "failed":
            raise AssignmentCenterError(
                409,
                "override-status only allowed when node is failed",
                "override_status_only_for_failed",
                {"current_status": current_status},
            )
        blocking_reasons = _node_blocking_reasons(
            node_id,
            node_map_by_id=snapshot_before["node_map_by_id"],
            upstream_map=snapshot_before["upstream_map"],
        )
        if next_status == "running":
            if blocking_reasons:
                raise AssignmentCenterError(
                    409,
                    "override to running blocked by upstream",
                    "override_running_blocked_by_upstream",
                    {"blocking_reasons": blocking_reasons},
                )
            graph_row = snapshot_before["graph_row"]
            scheduler_state = str(graph_row["scheduler_state"] or "").strip().lower()
            if scheduler_state != "running":
                raise AssignmentCenterError(
                    409,
                    "scheduler not running",
                    "scheduler_not_running",
                    {"scheduler_state": scheduler_state},
                )
            system_limit, _updated_at = _get_global_concurrency_limit(conn)
            counts = _running_counts(conn, ticket_id=ticket_id)
            graph_limit = int(graph_row["global_concurrency_limit"] or 0)
            effective_limit = _graph_effective_limit(graph_limit=graph_limit, system_limit=system_limit)
            already_running = current_status == "running"
            graph_running = int(counts["graph_running_node_count"]) - (1 if already_running else 0)
            system_running = int(counts["system_running_node_count"]) - (1 if already_running else 0)
            if graph_running >= effective_limit or system_running >= system_limit:
                raise AssignmentCenterError(
                    409,
                    "concurrency limit reached",
                    "concurrency_limit_reached",
                )
            other = conn.execute(
                """
                SELECT node_id
                FROM assignment_nodes
                WHERE status='running'
                  AND assigned_agent_id=?
                  AND node_id<>?
                LIMIT 1
                """,
                (str(selected_node.get("assigned_agent_id") or ""), node_id),
            ).fetchone()
            if other is not None:
                raise AssignmentCenterError(
                    409,
                    "assigned agent already has running node",
                    "assigned_agent_busy",
                    {"running_node_id": str(other["node_id"] or "").strip()},
                )
        if next_status == "ready" and blocking_reasons:
            raise AssignmentCenterError(
                409,
                "override to ready blocked by upstream",
                "override_ready_blocked_by_upstream",
                {"blocking_reasons": blocking_reasons},
            )
        if next_status == "succeeded" and str(selected_node.get("artifact_delivery_status") or "").strip().lower() != "delivered":
            raise AssignmentCenterError(
                409,
                "artifact delivery required before success",
                "artifact_delivery_required",
                {"artifact_delivery_status": str(selected_node.get("artifact_delivery_status") or "pending")},
            )
        completed_at = ""
        success_reason = ""
        result_ref = ""
        failure_reason = ""
        if next_status == "succeeded":
            completed_at = now_text
            success_reason = "override: " + reason_text
        elif next_status == "failed":
            completed_at = now_text
            failure_reason = "override: " + reason_text
        conn.execute(
            """
            UPDATE assignment_nodes
            SET status=?,
                completed_at=?,
                success_reason=?,
                result_ref=?,
                failure_reason=?,
                updated_at=?
            WHERE ticket_id=? AND node_id=?
            """,
            (
                next_status,
                completed_at,
                success_reason,
                result_ref,
                failure_reason,
                now_text,
                ticket_id,
                node_id,
            ),
        )
        sticky = {node_id} if next_status in {"pending", "ready", "blocked"} else set()
        _recompute_graph_statuses(conn, ticket_id, sticky_node_ids=sticky)
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id=node_id,
            action="override_status",
            operator=operator_text,
            reason=reason_text,
            target_status=next_status,
            detail={"from_status": current_status},
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(root, snapshot)
    updated_node = next(
        (node for node in snapshot["serialized_nodes"] if str(node.get("node_id") or "").strip() == node_id),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": updated_node,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }
