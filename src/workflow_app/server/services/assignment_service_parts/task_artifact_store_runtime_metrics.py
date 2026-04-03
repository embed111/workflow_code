def read_assignment_artifact_preview(
    root: Path,
    *,
    ticket_id_text: str,
    node_id_text: str,
    path_index: int = 0,
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    selected_node = snapshot["node_map_by_id"].get(node_id) or {}
    if not selected_node:
        raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found")
    artifact_paths = list(selected_node.get("artifact_paths") or [])
    if not artifact_paths:
        raise AssignmentCenterError(404, "artifact not delivered", "artifact_not_delivered")
    artifact_root = _assignment_artifact_root(root)
    index = max(0, min(int(path_index or 0), len(artifact_paths) - 1))
    path = Path(str(artifact_paths[index])).resolve(strict=False)
    if not path_in_scope(path, artifact_root):
        raise AssignmentCenterError(400, "artifact path out of root", "artifact_path_out_of_root")
    if not path.exists() or not path.is_file():
        raise AssignmentCenterError(404, "artifact file missing", "artifact_file_missing")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AssignmentCenterError(
            415,
            "artifact preview only supports utf-8 text files",
            "artifact_preview_unsupported_encoding",
            {
                "path": path.as_posix(),
                "suffix": str(path.suffix or "").strip().lower(),
            },
        ) from exc
    return {
        "ticket_id": ticket_id,
        "node_id": node_id,
        "path_index": index,
        "path": path.as_posix(),
        "content": content,
        "content_type": _artifact_preview_content_type(path),
    }


def _zero_assignment_runtime_metrics() -> dict[str, int]:
    return {
        "running_task_count": 0,
        "running_agent_count": 0,
        "active_execution_count": 0,
        "agent_call_count": 0,
    }


def _get_assignment_runtime_metrics_from_files(
    root: Path,
    *,
    active_run_ids: set[str],
    include_test_data: bool,
) -> dict[str, int]:
    tasks_root = _assignment_tasks_root(root)
    if not tasks_root.exists() or not tasks_root.is_dir():
        return _zero_assignment_runtime_metrics()
    now_dt = now_local()
    running_node_count = 0
    running_agents: set[str] = set()
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for ticket_id in [
        str(path.name or "").strip()
        for path in sorted(tasks_root.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir() and str(path.name or "").strip()
    ]:
        task_record = _assignment_read_json(_assignment_graph_record_path(root, ticket_id))
        if not task_record:
            try:
                task_record = _assignment_load_task_record(root, ticket_id)
            except AssignmentCenterError:
                continue
        if not _assignment_task_visible(task_record, include_test_data=include_test_data):
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            ticket_id,
            ticket_record=task_record,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        nodes_root = _assignment_ticket_workspace_dir(root, ticket_id) / "nodes"
        node_lookup: dict[str, dict[str, Any]] = {}
        if nodes_root.exists() and nodes_root.is_dir():
            for path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
                if not path.is_file() or path.suffix.lower() != ".json":
                    continue
                payload = _assignment_read_json(path)
                if not payload:
                    continue
                if str(payload.get("record_state") or "active").strip().lower() == "deleted":
                    continue
                node_id = str(payload.get("node_id") or "").strip()
                if node_id:
                    node_lookup[node_id] = payload
        elif task_record:
            node_lookup = {
                str(node.get("node_id") or "").strip(): dict(node)
                for node in _assignment_active_node_records(
                    _assignment_load_node_records(root, ticket_id, include_deleted=True)
                )
                if str(node.get("node_id") or "").strip()
            }
        for run in _assignment_load_run_records(root, ticket_id=ticket_id):
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
            node = node_lookup.get(node_id) or {}
            running_node_count += 1
            agent_id = str(node.get("assigned_agent_id") or "").strip()
            if agent_id:
                running_agents.add(agent_id)
    return {
        "running_task_count": max(0, running_node_count),
        "running_agent_count": max(0, len(running_agents)),
        "active_execution_count": max(0, running_node_count),
        "agent_call_count": max(0, running_node_count),
    }


def get_assignment_runtime_metrics(root: Path, *, include_test_data: bool = True) -> dict[str, int]:
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    if not active_run_ids:
        return _zero_assignment_runtime_metrics()
    try:
        conn = connect_db(root)
        try:
            marks = ",".join("?" for _ in active_run_ids)
            row = conn.execute(
                """
                SELECT
                    COUNT(1) AS active_execution_count,
                    COUNT(DISTINCT CASE
                        WHEN COALESCE(n.assigned_agent_id, '')<>'' THEN n.assigned_agent_id
                        ELSE NULL
                    END) AS running_agent_count
                FROM assignment_execution_runs r
                JOIN assignment_graphs g ON g.ticket_id = r.ticket_id
                LEFT JOIN assignment_nodes n
                  ON n.ticket_id = r.ticket_id
                 AND n.node_id = r.node_id
                WHERE r.run_id IN ("""
                + marks
                + """)
                  AND (?=1 OR COALESCE(g.is_test_data,0)=0)
                """,
                (*active_run_ids, 1 if include_test_data else 0),
            ).fetchone()
        finally:
            conn.close()
        active_execution_count = int((row or {"active_execution_count": 0})["active_execution_count"] or 0)
        running_agent_count = int((row or {"running_agent_count": 0})["running_agent_count"] or 0)
        return {
            "running_task_count": max(0, active_execution_count),
            "running_agent_count": max(0, running_agent_count),
            "active_execution_count": max(0, active_execution_count),
            "agent_call_count": max(0, active_execution_count),
        }
    except Exception:
        return _get_assignment_runtime_metrics_from_files(
            root,
            active_run_ids=active_run_ids,
            include_test_data=include_test_data,
        )
