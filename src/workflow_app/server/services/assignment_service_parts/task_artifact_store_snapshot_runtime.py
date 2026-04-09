from __future__ import annotations


def _assignment_refresh_pause_state_from_files(
    task_record: dict[str, Any],
    node_records: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    current = dict(task_record)
    state = str(current.get("scheduler_state") or "idle").strip().lower() or "idle"
    if state != "pause_pending":
        return current, False
    running_count = sum(
        1
        for node in list(node_records or [])
        if str(node.get("record_state") or "active").strip().lower() != "deleted"
        and str(node.get("status") or "").strip().lower() == "running"
    )
    if running_count > 0:
        return current, False
    current["scheduler_state"] = "paused"
    current["updated_at"] = iso_ts(now_local())
    return current, True


def _assignment_recompute_task_state(
    root: Path,
    *,
    task_record: dict[str, Any],
    node_records: list[dict[str, Any]],
    sticky_node_ids: set[str] | None = None,
    reconcile_running: bool = True,
    live_keys: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    current_task = dict(task_record)
    current_nodes = [dict(item) for item in list(node_records or [])]
    changed = False
    if reconcile_running:
        current_task, current_nodes, stale_changed = _assignment_reconcile_stale_task_state_internal(
            root,
            task_record=current_task,
            node_records=current_nodes,
            live_keys=live_keys,
        )
        changed = changed or stale_changed
    active_nodes = _assignment_active_node_records(current_nodes)
    active_edges = _assignment_active_edges(current_task, active_nodes)
    current_nodes, edge_sync_changed = _assignment_apply_edges_to_nodes(current_nodes, active_edges)
    changed = changed or edge_sync_changed
    sticky = {
        str(item or "").strip()
        for item in list(sticky_node_ids or set())
        if str(item or "").strip()
    }
    upstream_map, _downstream_map = _edge_maps(active_edges)
    status_map = {
        str(node.get("node_id") or "").strip(): str(node.get("status") or "").strip().lower()
        for node in _assignment_active_node_records(current_nodes)
    }
    now_text = iso_ts(now_local())
    recomputed_nodes: list[dict[str, Any]] = []
    for row in current_nodes:
        current = dict(row)
        if str(current.get("record_state") or "active").strip().lower() == "deleted":
            recomputed_nodes.append(current)
            continue
        node_id = str(current.get("node_id") or "").strip()
        if node_id in sticky:
            recomputed_nodes.append(current)
            continue
        current_status = str(current.get("status") or "").strip().lower()
        next_status = _derive_node_status(
            node_id,
            current_status=current_status,
            node_status_map=status_map,
            upstream_map=upstream_map,
        )
        if next_status != current_status:
            current["status"] = next_status
            current["status_text"] = _node_status_text(next_status)
            current["updated_at"] = now_text
            if next_status in {"pending", "ready", "blocked"}:
                current["completed_at"] = ""
                if current_status not in {"failed", "succeeded"}:
                    current["success_reason"] = ""
                    current["result_ref"] = ""
                    current["failure_reason"] = ""
            changed = True
            status_map[node_id] = next_status
        recomputed_nodes.append(current)
    current_nodes = recomputed_nodes
    refreshed_task, pause_changed = _assignment_refresh_pause_state_from_files(current_task, current_nodes)
    current_task = refreshed_task
    changed = changed or pause_changed
    next_edges = _assignment_active_edges(current_task, _assignment_active_node_records(current_nodes))
    if json.dumps(current_task.get("edges") or [], ensure_ascii=False, sort_keys=True) != json.dumps(
        next_edges,
        ensure_ascii=False,
        sort_keys=True,
    ):
        current_task["edges"] = list(next_edges)
        changed = True
    if changed:
        current_task["updated_at"] = now_text
    return current_task, current_nodes, changed


def _assignment_store_snapshot(root: Path, *, task_record: dict[str, Any], node_records: list[dict[str, Any]]) -> None:
    ticket_id = str(task_record.get("ticket_id") or "").strip()
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    _assignment_write_json(_assignment_graph_record_path(root, ticket_id), task_record)
    for node_record in list(node_records or []):
        node_id = str(node_record.get("node_id") or "").strip()
        if not node_id:
            continue
        _assignment_write_json(_assignment_node_record_path(root, ticket_id, node_id), node_record)
    _assignment_refresh_structure_guides(root, ticket_id)
    _assignment_publish_runtime_event(
        ticket_id=ticket_id,
        kind="snapshot",
        status=str(task_record.get("record_state") or "active").strip().lower(),
        scheduler_state=str(task_record.get("scheduler_state") or "").strip().lower(),
        event_type="snapshot_updated",
    )


def _assignment_scheduler_payload(
    task_record: dict[str, Any],
    nodes: list[dict[str, Any]],
    *,
    system_limit: int,
    settings_updated_at: str,
    system_counts: dict[str, int],
) -> dict[str, Any]:
    graph_running_node_count = sum(
        1
        for item in list(nodes or [])
        if str(item.get("status") or "").strip().lower() == "running"
    )
    running_agents = {
        str(item.get("assigned_agent_id") or "").strip()
        for item in list(nodes or [])
        if str(item.get("status") or "").strip().lower() == "running"
        and str(item.get("assigned_agent_id") or "").strip()
    }
    graph_limit = int(task_record.get("global_concurrency_limit") or 0)
    return {
        "state": str(task_record.get("scheduler_state") or "idle").strip().lower() or "idle",
        "state_text": _scheduler_state_text(task_record.get("scheduler_state") or "idle"),
        "running_agent_count": len(running_agents),
        "system_running_agent_count": int(system_counts.get("system_running_agent_count") or 0),
        "graph_running_node_count": int(graph_running_node_count),
        "system_running_node_count": int(system_counts.get("system_running_node_count") or 0),
        "global_concurrency_limit": int(system_limit),
        "graph_concurrency_limit": graph_limit,
        "effective_concurrency_limit": _graph_effective_limit(
            graph_limit=graph_limit,
            system_limit=system_limit,
        ),
        "pause_note": str(task_record.get("pause_note") or "").strip(),
        "settings_updated_at": str(settings_updated_at or ""),
    }


def _assignment_system_running_counts(root: Path, *, include_test_data: bool) -> dict[str, int]:
    try:
        metrics = get_assignment_runtime_metrics(root, include_test_data=include_test_data)
    except Exception:
        metrics = {}
    return {
        "system_running_node_count": int(
            metrics.get("running_task_count")
            or metrics.get("active_execution_count")
            or 0
        ),
        "system_running_agent_count": int(metrics.get("running_agent_count") or 0),
    }


def _assignment_snapshot_from_files(
    root: Path,
    ticket_id: str,
    *,
    include_test_data: bool = True,
    reconcile_running: bool = True,
    sticky_node_ids: set[str] | None = None,
    include_scheduler: bool = True,
    include_serialized_nodes: bool = True,
    persist_changes: bool = True,
) -> dict[str, Any]:
    ticket_id = _assignment_resolve_graph_ticket_id(root, ticket_id)
    task_record = _assignment_load_task_record(root, ticket_id)
    if not _assignment_task_visible(task_record, include_test_data=include_test_data):
        raise AssignmentCenterError(
            404,
            "assignment graph not found",
            "assignment_graph_not_found",
            {"ticket_id": ticket_id},
        )
    node_records = _assignment_load_node_records(root, ticket_id, include_deleted=True)
    task_record, node_records, changed = _assignment_recompute_task_state(
        root,
        task_record=task_record,
        node_records=node_records,
        sticky_node_ids=sticky_node_ids,
        reconcile_running=reconcile_running,
    )
    if changed and persist_changes:
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    active_nodes = _assignment_active_node_records(node_records)
    edges = _assignment_active_edges(task_record, active_nodes)
    node_map_by_id = _node_map(active_nodes)
    upstream_map, downstream_map = _edge_maps(edges)
    scheduler_payload = {}
    if include_scheduler:
        settings = get_assignment_concurrency_settings(root)
        system_counts = _assignment_system_running_counts(root, include_test_data=include_test_data)
        scheduler_payload = _assignment_scheduler_payload(
            task_record,
            active_nodes,
            system_limit=int(settings.get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
            settings_updated_at=str(settings.get("updated_at") or ""),
            system_counts=system_counts,
        )
    serialized_nodes: list[dict[str, Any]] = []
    if include_serialized_nodes:
        serialized_nodes = [
            _serialize_node(
                node,
                node_map_by_id=node_map_by_id,
                upstream_map=upstream_map,
                downstream_map=downstream_map,
            )
            for node in active_nodes
        ]
    is_test_data = bool(task_record.get("is_test_data"))
    for node in serialized_nodes:
        node["is_test_data"] = is_test_data
    return {
        "graph_row": task_record,
        "nodes": active_nodes,
        "all_nodes": node_records,
        "edges": edges,
        "node_map_by_id": node_map_by_id,
        "upstream_map": upstream_map,
        "downstream_map": downstream_map,
        "metrics_summary": _graph_metrics(active_nodes),
        "scheduler": scheduler_payload,
        "serialized_nodes": serialized_nodes,
    }
