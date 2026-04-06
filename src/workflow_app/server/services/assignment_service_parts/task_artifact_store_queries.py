from __future__ import annotations

from workflow_app.server.services.codex_failure_contract import (
    build_codex_failure,
    build_retry_action,
    infer_codex_failure_detail_code,
)


def _assignment_task_visible(task_record: dict[str, Any], *, include_test_data: bool) -> bool:
    if str(task_record.get("record_state") or "active").strip().lower() == "deleted":
        return False
    if include_test_data:
        return True
    return not bool(task_record.get("is_test_data"))


def _assignment_active_node_records(node_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(node_records or [])
        if str(item.get("record_state") or "active").strip().lower() != "deleted"
    ]


def _assignment_active_edges(task_record: dict[str, Any], node_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = list(task_record.get("edges") or [])
    if not edges:
        edges = _assignment_edges_from_node_records(node_records)
    active_node_ids = {
        str(item.get("node_id") or "").strip()
        for item in list(node_records or [])
        if str(item.get("record_state") or "active").strip().lower() != "deleted"
    }
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for edge in list(edges or []):
        from_id = str(edge.get("from_node_id") or "").strip()
        to_id = str(edge.get("to_node_id") or "").strip()
        if not from_id or not to_id:
            continue
        if from_id not in active_node_ids or to_id not in active_node_ids:
            continue
        if str(edge.get("record_state") or "active").strip().lower() == "deleted":
            continue
        pair = (from_id, to_id)
        if pair in seen:
            continue
        seen.add(pair)
        out.append(
            {
                "from_node_id": from_id,
                "to_node_id": to_id,
                "edge_kind": str(edge.get("edge_kind") or "depends_on").strip() or "depends_on",
                "created_at": str(edge.get("created_at") or "").strip(),
                "record_state": "active",
            }
        )
    out.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("from_node_id") or ""),
            str(item.get("to_node_id") or ""),
        )
    )
    return out


def _assignment_edge_pairs(edges: list[dict[str, Any]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for edge in list(edges or []):
        from_id = str(edge.get("from_node_id") or "").strip()
        to_id = str(edge.get("to_node_id") or "").strip()
        if from_id and to_id:
            pairs.append((from_id, to_id))
    return pairs


def _assignment_apply_edges_to_nodes(
    node_records: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    upstream_map, downstream_map = _edge_maps(edges)
    changed = False
    updated: list[dict[str, Any]] = []
    for row in list(node_records or []):
        current = dict(row)
        if str(current.get("record_state") or "active").strip().lower() == "deleted":
            updated.append(current)
            continue
        node_id = str(current.get("node_id") or "").strip()
        next_upstream = list(upstream_map.get(node_id) or [])
        next_downstream = list(downstream_map.get(node_id) or [])
        prev_upstream = [
            str(item or "").strip()
            for item in list(current.get("upstream_node_ids") or [])
            if str(item or "").strip()
        ]
        prev_downstream = [
            str(item or "").strip()
            for item in list(current.get("downstream_node_ids") or [])
            if str(item or "").strip()
        ]
        if prev_upstream != next_upstream:
            current["upstream_node_ids"] = next_upstream
            changed = True
        if prev_downstream != next_downstream:
            current["downstream_node_ids"] = next_downstream
            changed = True
        updated.append(current)
    return updated, changed


def _assignment_live_run_keys_from_files(root: Path, *, ticket_id: str = "") -> set[tuple[str, str]]:
    ticket_filter = _assignment_resolve_graph_ticket_id(root, ticket_id)
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    now_dt = now_local()
    live_keys: set[tuple[str, str]] = set()
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for current_ticket_id in _assignment_list_ticket_ids_lightweight(root):
        if ticket_filter and current_ticket_id != ticket_filter:
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            current_ticket_id,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        for run in _assignment_load_run_records(root, ticket_id=current_ticket_id):
            status = str(run.get("status") or "").strip().lower()
            if status not in {"starting", "running"}:
                continue
            if not _assignment_run_row_is_live(
                run,
                active_run_ids=active_run_ids,
                now_dt=now_dt,
                grace_seconds=DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS,
            ):
                continue
            node_id = str(run.get("node_id") or "").strip()
            if node_id:
                live_keys.add((current_ticket_id, node_id))
    return live_keys


def _assignment_list_ticket_ids_lightweight(root: Path) -> list[str]:
    tasks_root = _assignment_tasks_root(root)
    if not tasks_root.exists() or not tasks_root.is_dir():
        return []
    return [
        str(path.name or "").strip()
        for path in sorted(tasks_root.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir() and str(path.name or "").strip()
    ]


def _assignment_load_task_record_lightweight(root: Path, ticket_id: str) -> dict[str, Any]:
    task_record = _assignment_read_json(_assignment_graph_record_path(root, ticket_id))
    if task_record:
        return task_record
    try:
        return _assignment_load_task_record(root, ticket_id)
    except AssignmentCenterError:
        return {}


def _assignment_load_active_node_records_lightweight(root: Path, ticket_id: str) -> list[dict[str, Any]]:
    nodes_root = _assignment_ticket_workspace_dir(root, ticket_id) / "nodes"
    if nodes_root.exists() and nodes_root.is_dir():
        rows: list[dict[str, Any]] = []
        for path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            payload = _assignment_read_json(path)
            if not payload:
                continue
            if str(payload.get("record_state") or "active").strip().lower() == "deleted":
                continue
            rows.append(payload)
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("node_id") or "")))
        return rows
    try:
        return _assignment_active_node_records(_assignment_load_node_records(root, ticket_id, include_deleted=True))
    except AssignmentCenterError:
        return []


def _assignment_live_node_ids_for_ticket(root: Path, *, ticket_id: str) -> set[str]:
    ticket_text = safe_token(str(ticket_id or ""), "", 160)
    if not ticket_text:
        return set()
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    now_dt = now_local()
    live_node_ids: set[str] = set()
    for run in _assignment_load_run_records(root, ticket_id=ticket_text):
        status = str(run.get("status") or "").strip().lower()
        if status not in {"starting", "running"}:
            continue
        if not _assignment_run_row_is_live(
            run,
            active_run_ids=active_run_ids,
            now_dt=now_dt,
            grace_seconds=DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS,
        ):
            continue
        node_id = str(run.get("node_id") or "").strip()
        if node_id:
            live_node_ids.add(node_id)
    return live_node_ids


def _assignment_project_live_run_status_for_nodes(
    root: Path,
    *,
    ticket_id: str,
    node_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    live_node_ids = _assignment_live_node_ids_for_ticket(root, ticket_id=ticket_id)
    updated: list[dict[str, Any]] = []
    for row in list(node_records or []):
        current = dict(row)
        if str(current.get("record_state") or "active").strip().lower() == "deleted":
            updated.append(current)
            continue
        node_id = str(current.get("node_id") or "").strip()
        status = str(current.get("status") or "").strip().lower()
        if status == "running" and node_id and node_id not in live_node_ids:
            current["status"] = "failed"
            current["status_text"] = _node_status_text("failed")
        updated.append(current)
    return updated


def _assignment_try_recover_terminal_run_from_files(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    run_record: dict[str, Any],
) -> bool:
    run_id = str(run_record.get("run_id") or "").strip()
    if not run_id:
        return False
    refs = _assignment_run_file_paths(root, ticket_id, run_id)
    result_payload = _assignment_read_json(refs["result"])
    events = _assignment_read_jsonl(refs["events"])
    final_event = next(
        (
            item
            for item in reversed(list(events or []))
            if str((item or {}).get("event_type") or "").strip().lower() == "final_result"
        ),
        {},
    )
    has_result_payload = bool(result_payload)
    has_final_event = bool(final_event)
    if not has_result_payload and not has_final_event:
        return False
    stdout_text = _read_assignment_run_text(refs["stdout"].as_posix())
    stderr_text = _read_assignment_run_text(refs["stderr"].as_posix())
    detail = dict(final_event.get("detail") or {}) if isinstance(final_event, dict) else {}
    try:
        exit_code = int(detail.get("exit_code") or run_record.get("exit_code") or 0)
    except Exception:
        exit_code = 0
    failure_message = ""
    if exit_code != 0:
        failure_message = (
            str(final_event.get("message") or "").strip()
            or _short_assignment_text(stderr_text, 500)
            or f"assignment execution failed with exit={exit_code}"
        )
    _finalize_assignment_execution_run(
        root,
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        exit_code=exit_code,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        result_payload=result_payload if isinstance(result_payload, dict) else {},
        failure_message=failure_message,
    )
    return True


def _assignment_try_recover_terminal_node_from_files(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
) -> bool:
    recovered = False
    for run in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        status = str(run.get("status") or "").strip().lower()
        if status not in {"starting", "running"}:
            continue
        if _assignment_try_recover_terminal_run_from_files(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            run_record=run,
        ):
            recovered = True
    return recovered


def _assignment_reconcile_stale_task_state_internal(
    root: Path,
    *,
    task_record: dict[str, Any],
    node_records: list[dict[str, Any]],
    live_keys: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    if bool(task_record.get("is_test_data")):
        return dict(task_record), [dict(item) for item in list(node_records or [])], False
    ticket_id = str(task_record.get("ticket_id") or "").strip()
    if not ticket_id:
        return dict(task_record), [dict(item) for item in list(node_records or [])], False
    if live_keys is None:
        live_keys = _assignment_live_run_keys_from_files(root, ticket_id=ticket_id)
    now_text = iso_ts(now_local())
    changed = False
    updated_nodes: list[dict[str, Any]] = []
    for node in list(node_records or []):
        current = dict(node)
        if str(current.get("record_state") or "active").strip().lower() == "deleted":
            updated_nodes.append(current)
            continue
        node_id = str(current.get("node_id") or "").strip()
        status = str(current.get("status") or "").strip().lower()
        if (ticket_id, node_id) in live_keys and status in {"pending", "ready", "blocked"}:
            current["status"] = "running"
            current["status_text"] = _node_status_text("running")
            current["updated_at"] = now_text
            changed = True
        elif status == "running" and (ticket_id, node_id) not in live_keys:
            if _assignment_try_recover_terminal_node_from_files(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
            ):
                refreshed_task = _assignment_read_json(_assignment_graph_record_path(root, ticket_id))
                refreshed_nodes = _assignment_load_node_records(root, ticket_id, include_deleted=True)
                return (
                    dict(refreshed_task or task_record),
                    [dict(item) for item in list(refreshed_nodes or node_records)],
                    True,
                )
            current["status"] = "failed"
            current["status_text"] = _node_status_text("failed")
            current["completed_at"] = now_text
            current["success_reason"] = ""
            current["result_ref"] = ""
            current["failure_reason"] = str(
                current.get("failure_reason") or "运行句柄缺失或 workflow 已重启，请手动重跑。"
            ).strip()
            current["updated_at"] = now_text
            changed = True
            for run in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
                run_status = str(run.get("status") or "").strip().lower()
                if run_status not in {"starting", "running"}:
                    continue
                run["status"] = "cancelled"
                run["latest_event"] = "检测到运行句柄缺失，已自动结束当前批次。"
                run["latest_event_at"] = now_text
                run["finished_at"] = now_text
                run["updated_at"] = now_text
                _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run)
            _assignment_write_audit_entry(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
                action="recover_stale_running",
                operator="assignment-system",
                reason="recover stale running node without live execution",
                target_status="failed",
                detail={},
                created_at=now_text,
            )
            try:
                schedule_result = _assignment_queue_self_iteration_schedule(
                    root,
                    task_record=task_record,
                    node_record=current,
                    result_summary=str(current.get("failure_reason") or "").strip() or "运行句柄缺失或 workflow 已重启，请手动重跑。",
                    success=False,
                )
                if bool(schedule_result.get("queued")):
                    _assignment_write_audit_entry(
                        root,
                        ticket_id=ticket_id,
                        node_id=node_id,
                        action="schedule_self_iteration",
                        operator="assignment-system",
                        reason="queued next self-iteration schedule after stale run recovery",
                        target_status="failed",
                        detail=schedule_result,
                        created_at=now_text,
                    )
            except Exception:
                pass
        updated_nodes.append(current)
    return dict(task_record), updated_nodes, changed


def _assignment_reconcile_stale_task_state(
    root: Path,
    *,
    task_record: dict[str, Any],
    node_records: list[dict[str, Any]],
    live_keys: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    next_task, next_nodes, _changed = _assignment_reconcile_stale_task_state_internal(
        root,
        task_record=task_record,
        node_records=node_records,
        live_keys=live_keys,
    )
    return next_task, next_nodes


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
    if changed:
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


def _assignment_find_ticket_by_source_request(
    root: Path,
    *,
    source_workflow: str,
    external_request_id: str,
) -> str:
    source_text = str(source_workflow or "").strip()
    request_text = str(external_request_id or "").strip()
    if not source_text or not request_text:
        return ""
    if (
        source_text == ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW
        and request_text == ASSIGNMENT_GLOBAL_GRAPH_REQUEST_ID
    ):
        return _assignment_ensure_workflow_ui_global_graph_ticket(root)
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for ticket_id in _assignment_list_ticket_ids(root):
        try:
            task_record = _assignment_load_task_record(root, ticket_id)
        except AssignmentCenterError:
            continue
        if str(task_record.get("record_state") or "active").strip().lower() == "deleted":
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            ticket_id,
            ticket_record=task_record,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        if str(task_record.get("source_workflow") or "").strip() != source_text:
            continue
        if str(task_record.get("external_request_id") or "").strip() != request_text:
            continue
        return ticket_id
    return ""


def _assignment_load_runs(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id)
    return rows[: max(1, int(limit))]


def _assignment_selected_node_codex_failure(
    *,
    ticket_id: str,
    selected_node: dict[str, Any],
    latest_run: dict[str, Any],
    run_count: int,
) -> dict[str, Any]:
    current_run = latest_run if isinstance(latest_run, dict) else {}
    stored = current_run.get("codex_failure") if isinstance(current_run.get("codex_failure"), dict) else {}
    if stored:
        return stored
    failure_text = str(selected_node.get("failure_reason") or "").strip()
    if not failure_text:
        return {}
    return build_codex_failure(
        feature_key="assignment_node_execution",
        attempt_id=str(current_run.get("run_id") or selected_node.get("node_id") or "").strip(),
        attempt_count=max(1, int(run_count or 0)),
        failure_detail_code=infer_codex_failure_detail_code(
            failure_text,
            fallback="assignment_execution_failed",
        ),
        failure_message=failure_text,
        retry_action=build_retry_action(
            "rerun_assignment_node",
            payload={
                "ticket_id": str(ticket_id or "").strip(),
                "node_id": str(selected_node.get("node_id") or "").strip(),
                "run_id": str(current_run.get("run_id") or "").strip(),
            },
        ),
        trace_refs={
            "prompt": str(current_run.get("prompt_ref") or "").strip(),
            "stdout": str(current_run.get("stdout_ref") or "").strip(),
            "stderr": str(current_run.get("stderr_ref") or "").strip(),
            "result": str(current_run.get("result_ref") or "").strip(),
        },
        failed_at=str(
            current_run.get("finished_at")
            or current_run.get("updated_at")
            or selected_node.get("completed_at")
            or ""
        ).strip(),
    )


def _assignment_run_summary(root: Path, row: dict[str, Any], *, include_content: bool) -> dict[str, Any]:
    run_id = str(row.get("run_id") or "").strip()
    ticket_id = str(row.get("ticket_id") or "").strip()
    refs = _assignment_run_file_paths(root, ticket_id, run_id) if run_id and ticket_id else {}
    events_path = refs.get("events")
    prompt_path = refs.get("prompt")
    stdout_path = refs.get("stdout")
    stderr_path = refs.get("stderr")
    result_path = refs.get("result")
    prompt_ref = str(row.get("prompt_ref") or (prompt_path.as_posix() if isinstance(prompt_path, Path) else "")).strip()
    stdout_ref = str(row.get("stdout_ref") or (stdout_path.as_posix() if isinstance(stdout_path, Path) else "")).strip()
    stderr_ref = str(row.get("stderr_ref") or (stderr_path.as_posix() if isinstance(stderr_path, Path) else "")).strip()
    result_ref = str(row.get("result_ref") or (result_path.as_posix() if isinstance(result_path, Path) else "")).strip()
    events = _tail_assignment_run_events(events_path) if isinstance(events_path, Path) else []
    codex_failure = row.get("codex_failure") if isinstance(row.get("codex_failure"), dict) else {}
    return {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "node_id": str(row.get("node_id") or "").strip(),
        "provider": str(row.get("provider") or "").strip(),
        "workspace_path": str(row.get("workspace_path") or "").strip(),
        "status": _normalize_run_status(row.get("status") or "starting"),
        "status_text": _node_status_text(
            "running" if str(row.get("status") or "").strip().lower() == "running" else row.get("status") or ""
        ),
        "command_summary": str(row.get("command_summary") or "").strip(),
        "prompt_ref": prompt_ref,
        "stdout_ref": stdout_ref,
        "stderr_ref": stderr_ref,
        "result_ref": result_ref,
        "latest_event": str(row.get("latest_event") or "").strip(),
        "latest_event_at": str(row.get("latest_event_at") or "").strip(),
        "exit_code": int(row.get("exit_code") or 0),
        "started_at": str(row.get("started_at") or "").strip(),
        "finished_at": str(row.get("finished_at") or "").strip(),
        "created_at": str(row.get("created_at") or "").strip(),
        "updated_at": str(row.get("updated_at") or "").strip(),
        "event_count": len(events),
        "events": events,
        "codex_failure": codex_failure,
        "prompt_text": (
            _read_assignment_run_text(prompt_ref, preview_chars=_assignment_run_preview_chars(prompt_ref))
            if include_content
            else ""
        ),
        "stdout_text": (
            _read_assignment_run_text(stdout_ref, preview_chars=_assignment_run_preview_chars(stdout_ref))
            if include_content
            else ""
        ),
        "stderr_text": (
            _read_assignment_run_text(stderr_ref, preview_chars=_assignment_run_preview_chars(stderr_ref))
            if include_content
            else ""
        ),
        "result_text": (
            _read_assignment_run_text(result_ref, preview_chars=_assignment_run_preview_chars(result_ref))
            if include_content
            else ""
        ),
    }


def _assignment_normalize_cancelled_run_summary(
    run_summary: dict[str, Any],
    *,
    selected_node: dict[str, Any],
    audit_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    current = dict(run_summary or {})
    if str(current.get("status") or "").strip().lower() != "cancelled":
        return current
    latest_event = str(current.get("latest_event") or "").strip()
    if "人工结束" not in latest_event:
        return current
    failure_reason = str(selected_node.get("failure_reason") or "").strip()
    has_stale_recovery_audit = any(
        str(item.get("action") or "").strip().lower() == "recover_stale_running"
        for item in list(audit_refs or [])
    )
    stale_failure = "运行句柄缺失" in failure_reason or "workflow 已重启" in failure_reason
    if not has_stale_recovery_audit and not stale_failure:
        return current
    current["latest_event"] = "检测到运行句柄缺失或 workflow 已重启，已自动结束当前批次，后台结果不再回写节点状态。"
    return current


def _assignment_management_actions(
    node: dict[str, Any],
    *,
    blocking_reasons: list[dict[str, Any]],
) -> list[str]:
    if not isinstance(node, dict) or not node:
        return []
    status = str(node.get("status") or "").strip().lower()
    actions: list[str] = []
    if status == "running":
        actions.extend(["mark-success", "mark-failed"])
    else:
        actions.append("override-status")
        if status == "failed":
            actions.append("rerun")
        actions.append("delete")
    actions.append("deliver-artifact")
    if list(node.get("artifact_paths") or []):
        actions.append("view-artifact")
    if status == "blocked" and not blocking_reasons and "override-status" not in actions:
        actions.append("override-status")
    seen: set[str] = set()
    ordered: list[str] = []
    for action in actions:
        key = str(action or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _assignment_status_detail_payload(
    root: Path,
    *,
    ticket_id: str,
    node_id: str = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
        include_scheduler=False,
        include_serialized_nodes=False,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    selected_node = snapshot["node_map_by_id"].get(node_id) or (snapshot["nodes"][0] if snapshot["nodes"] else {})
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
    blocking_reasons = list(selected_serialized.get("blocking_reasons") or [])
    management_actions = _assignment_management_actions(selected_serialized, blocking_reasons=blocking_reasons)
    if isinstance(selected_serialized, dict) and selected_serialized:
        selected_serialized["management_actions"] = list(management_actions)
    run_rows = (
        _assignment_load_runs(
            root,
            ticket_id=ticket_id,
            node_id=str(selected_serialized.get("node_id") or "").strip(),
            limit=5,
        )
        if selected_serialized
        else []
    )
    run_summaries = [
        _assignment_run_summary(root, row, include_content=index == 0)
        for index, row in enumerate(run_rows)
    ]
    audit_refs = []
    for row in _assignment_load_audit_records(
        root,
        ticket_id=ticket_id,
        node_id=str(selected_serialized.get("node_id") or "").strip(),
        limit=12,
    ):
        audit_refs.append(
            {
                "audit_id": str(row.get("audit_id") or "").strip(),
                "action": str(row.get("action") or "").strip(),
                "operator": str(row.get("operator") or "").strip(),
                "reason": str(row.get("reason") or "").strip(),
                "target_status": str(row.get("target_status") or "").strip(),
                "ref": str(row.get("ref") or "").strip(),
                "created_at": str(row.get("created_at") or "").strip(),
                "detail": dict(row.get("detail") or {}),
            }
        )
    run_summaries = [
        _assignment_normalize_cancelled_run_summary(
            run_summary,
            selected_node=selected_serialized,
            audit_refs=audit_refs,
        )
        for run_summary in run_summaries
    ]
    node_codex_failure = _assignment_selected_node_codex_failure(
        ticket_id=ticket_id,
        selected_node=selected_serialized,
        latest_run=run_summaries[0] if run_summaries else {},
        run_count=len(run_summaries),
    )
    if isinstance(selected_serialized, dict) and selected_serialized:
        selected_serialized["codex_failure"] = node_codex_failure
    return {
        "ticket_id": ticket_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "selected_node": selected_serialized,
        "blocking_reasons": blocking_reasons,
        "available_actions": management_actions,
        "audit_refs": audit_refs,
        "codex_failure": node_codex_failure,
        "execution_chain": {
            "poll_mode": assignment_execution_refresh_mode(),
            "poll_interval_ms": DEFAULT_ASSIGNMENT_EXECUTION_POLL_INTERVAL_MS,
            "latest_run": run_summaries[0] if run_summaries else {},
            "recent_runs": run_summaries,
        },
    }


def _assignment_node_status_text(row: dict[str, Any]) -> str:
    return str(row.get("status") or "").strip().lower()


def _assignment_active_node_group(row: dict[str, Any]) -> int:
    status = _assignment_node_status_text(row)
    if status == "running":
        return 0
    if status == "ready":
        return 1
    if status == "pending":
        return 2
    if status == "blocked":
        return 3
    return 4


def _assignment_sort_active_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    items.sort(
        key=lambda row: (
            str(row.get("updated_at") or ""),
            str(row.get("created_at") or ""),
            str(row.get("node_id") or ""),
        ),
        reverse=True,
    )
    items.sort(
        key=lambda row: (
            _assignment_active_node_group(row),
            int(row.get("priority") or 0),
        )
    )
    return items


def _assignment_sort_completed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    items.sort(
        key=lambda row: (
            str(row.get("completed_at") or ""),
            str(row.get("created_at") or ""),
            str(row.get("node_id") or ""),
        ),
        reverse=True,
    )
    return items


def _assignment_build_node_catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": str(row.get("node_id") or "").strip(),
            "node_name": str(row.get("node_name") or "").strip(),
            "status": _assignment_node_status_text(row),
            "priority": int(row.get("priority") or 0),
            "priority_label": assignment_priority_label(row.get("priority")),
        }
        for row in list(rows or [])
        if str(row.get("node_id") or "").strip()
    ]


def list_assignments(
    root: Path,
    *,
    include_test_data: bool = True,
    source_workflow: Any = "",
    external_request_id: Any = "",
    offset: Any = 0,
    limit: Any = 0,
) -> dict[str, Any]:
    source_filter = str(source_workflow or "").strip()
    request_filter = str(external_request_id or "").strip()
    page_offset = _normalize_history_loaded(offset)
    try:
        page_limit = int(limit or 0)
    except Exception:
        page_limit = 0
    if page_limit > 0:
        page_limit = max(1, min(200, page_limit))
    else:
        page_limit = 0
    items: list[dict[str, Any]] = []
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for ticket_id in _assignment_list_ticket_ids_lightweight(root):
        graph_row = _assignment_load_task_record_lightweight(root, ticket_id)
        if not graph_row:
            continue
        if not _assignment_task_visible(graph_row, include_test_data=include_test_data):
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            ticket_id,
            ticket_record=graph_row,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        if source_filter and str(graph_row.get("source_workflow") or "").strip() != source_filter:
            continue
        if request_filter and str(graph_row.get("external_request_id") or "").strip() != request_filter:
            continue
        node_records = _assignment_project_live_run_status_for_nodes(
            root,
            ticket_id=ticket_id,
            node_records=_assignment_load_active_node_records_lightweight(root, ticket_id),
        )
        metrics_summary = _graph_metrics(node_records)
        items.append(
            {
                "ticket_id": str(graph_row.get("ticket_id") or "").strip(),
                "graph_name": str(graph_row.get("graph_name") or "").strip(),
                "source_workflow": str(graph_row.get("source_workflow") or "").strip(),
                "summary": str(graph_row.get("summary") or "").strip(),
                "review_mode": str(graph_row.get("review_mode") or "").strip(),
                "global_concurrency_limit": int(graph_row.get("global_concurrency_limit") or 0),
                "is_test_data": bool(graph_row.get("is_test_data")),
                "external_request_id": str(graph_row.get("external_request_id") or "").strip(),
                "scheduler_state": str(graph_row.get("scheduler_state") or "idle").strip().lower(),
                "scheduler_state_text": _scheduler_state_text(graph_row.get("scheduler_state") or "idle"),
                "pause_note": str(graph_row.get("pause_note") or "").strip(),
                "created_at": str(graph_row.get("created_at") or "").strip(),
                "updated_at": str(graph_row.get("updated_at") or "").strip(),
                "metrics_summary": {
                    "total_nodes": int(metrics_summary.get("total_nodes") or 0),
                    "pending_nodes": int((metrics_summary.get("status_counts") or {}).get("pending") or 0),
                    "ready_nodes": int((metrics_summary.get("status_counts") or {}).get("ready") or 0),
                    "running_nodes": int((metrics_summary.get("status_counts") or {}).get("running") or 0),
                    "failed_nodes": int((metrics_summary.get("status_counts") or {}).get("failed") or 0),
                    "blocked_nodes": int((metrics_summary.get("status_counts") or {}).get("blocked") or 0),
                    "executed_count": int(metrics_summary.get("executed_count") or 0),
                    "unexecuted_count": int(metrics_summary.get("unexecuted_count") or 0),
                },
            }
        )
    items.sort(
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("ticket_id") or ""),
        ),
        reverse=True,
    )
    items.sort(
        key=lambda item: (
            0 if int((item.get("metrics_summary") or {}).get("running_nodes") or 0) > 0 else
            1 if int((item.get("metrics_summary") or {}).get("unexecuted_count") or 0) > 0 else
            2,
            -int((item.get("metrics_summary") or {}).get("running_nodes") or 0),
            -int((item.get("metrics_summary") or {}).get("unexecuted_count") or 0),
        )
    )
    total_items = len(items)
    if page_offset > 0 or page_limit > 0:
        end = page_offset + page_limit if page_limit > 0 else None
        items = items[page_offset:end]
    settings = get_assignment_concurrency_settings(root)
    return {
        "items": items,
        "pagination": {
            "offset": page_offset,
            "limit": page_limit,
            "returned": len(items),
            "total_items": total_items,
            "has_more": (page_offset + len(items)) < total_items,
        },
        "settings": {
            "global_concurrency_limit": int(settings.get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
            "updated_at": str(settings.get("updated_at") or ""),
        },
    }


def get_assignment_overview(root: Path, ticket_id_text: str, *, include_test_data: bool = True) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
        include_serialized_nodes=False,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
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
    active_loaded: Any = 0,
    active_batch_size: Any = 24,
    history_loaded: Any = 0,
    history_batch_size: Any = 12,
    include_test_data: bool = True,
    focus_node_ids: Any = None,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    extra_active_loaded = _normalize_history_loaded(active_loaded)
    active_batch = _normalize_positive_int(
        active_batch_size,
        field="active_batch_size",
        default=24,
        minimum=1,
        maximum=200,
    )
    extra_loaded = _normalize_history_loaded(history_loaded)
    batch_size = _normalize_positive_int(
        history_batch_size,
        field="history_batch_size",
        default=12,
        minimum=1,
        maximum=50,
    )
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
        include_serialized_nodes=False,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    focus_node_id_set = {
        safe_token(str(item or ""), "", 160)
        for item in list(focus_node_ids or [])
        if safe_token(str(item or ""), "", 160)
    }
    raw_nodes = [
        dict(row)
        for row in list(snapshot["nodes"] or [])
        if not focus_node_id_set or str((row or {}).get("node_id") or "").strip() in focus_node_id_set
    ]
    completed_rows = _assignment_sort_completed_rows(
        [
            row
            for row in raw_nodes
            if _assignment_node_status_text(row) in {"succeeded", "failed"}
        ]
    )
    active_rows = _assignment_sort_active_rows(
        [
            row
            for row in raw_nodes
            if _assignment_node_status_text(row) not in {"succeeded", "failed"}
        ]
    )
    base_active = active_batch
    base_recent = 12
    visible_active = active_rows[: min(len(active_rows), base_active + extra_active_loaded)]
    visible_completed = completed_rows[: min(len(completed_rows), base_recent + extra_loaded)]
    visible_ids = {
        str(row.get("node_id") or "").strip()
        for row in visible_active + visible_completed
        if str(row.get("node_id") or "").strip()
    }
    visible_edges = [
        edge
        for edge in list(snapshot["edges"] or [])
        if str(edge.get("from_node_id") or "").strip() in visible_ids
        and str(edge.get("to_node_id") or "").strip() in visible_ids
    ]
    remaining_active = max(0, len(active_rows) - len(visible_active))
    remaining_completed = max(0, len(completed_rows) - len(visible_completed))
    visible_nodes = [
        _serialize_node(
            row,
            node_map_by_id=snapshot["node_map_by_id"],
            upstream_map=snapshot["upstream_map"],
            downstream_map=snapshot["downstream_map"],
        )
        for row in visible_active + visible_completed
    ]
    is_test_data = bool(snapshot["graph_row"].get("is_test_data"))
    for node in visible_nodes:
        node["is_test_data"] = is_test_data
    ordered_catalog_rows = active_rows + completed_rows
    return {
        "ticket_id": ticket_id,
        "graph": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "nodes": visible_nodes,
        "edges": visible_edges,
        "node_catalog": _assignment_build_node_catalog(ordered_catalog_rows),
        "metrics_summary": snapshot["metrics_summary"],
        "priority_rules": {
            "ui_levels": ["P0", "P1", "P2", "P3"],
            "backend_levels": [0, 1, 2, 3],
            "highest_first": True,
            "tie_breaker": "created_at_asc",
        },
        "active": {
            "base_visible_count": min(base_active, len(active_rows)),
            "loaded_extra_count": max(0, len(visible_active) - min(base_active, len(active_rows))),
            "next_active_loaded": extra_active_loaded + active_batch,
            "remaining_count": remaining_active,
            "has_more": remaining_active > 0,
            "batch_size": active_batch,
            "visible_count": len(visible_active),
            "total_count": len(active_rows),
        },
        "history": {
            "base_recent_count": min(base_recent, len(completed_rows)),
            "loaded_extra_count": max(0, len(visible_completed) - min(base_recent, len(completed_rows))),
            "next_history_loaded": extra_loaded + batch_size,
            "remaining_completed_count": remaining_completed,
            "has_more": remaining_completed > 0,
            "batch_size": batch_size,
        },
    }


def get_assignment_scheduler_state(root: Path, ticket_id_text: str, *, include_test_data: bool = True) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
        include_serialized_nodes=False,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    scheduler = snapshot["scheduler"]
    return {
        "ticket_id": ticket_id,
        "state": str(scheduler.get("state") or "").strip().lower(),
        "state_text": str(scheduler.get("state_text") or "").strip(),
        "running_agent_count": int(scheduler.get("running_agent_count") or 0),
        "system_running_agent_count": int(scheduler.get("system_running_agent_count") or 0),
        "graph_running_node_count": int(scheduler.get("graph_running_node_count") or 0),
        "system_running_node_count": int(scheduler.get("system_running_node_count") or 0),
        "global_concurrency_limit": int(scheduler.get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
        "graph_concurrency_limit": int(scheduler.get("graph_concurrency_limit") or 0),
        "effective_concurrency_limit": int(scheduler.get("effective_concurrency_limit") or 0),
        "pause_note": str(scheduler.get("pause_note") or "").strip(),
        "settings_updated_at": str(scheduler.get("settings_updated_at") or "").strip(),
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
    return _assignment_status_detail_payload(
        root,
        ticket_id=_assignment_resolve_graph_ticket_id(root, ticket_id),
        node_id=node_id,
        include_test_data=include_test_data,
    )
