from __future__ import annotations


def _assignment_active_run_record(root: Path, *, ticket_id: str, node_id: str) -> dict[str, Any]:
    for row in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        if str(row.get("status") or "").strip().lower() in {"starting", "running"}:
            return dict(row)
    return {}


def _assignment_execution_thread_should_daemon(operator: str) -> bool:
    raw = str(os.getenv("WORKFLOW_ASSIGNMENT_EXECUTION_THREAD_DAEMON") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    operator_text = str(operator or "").strip().lower()
    # PM-triggered one-shot dispatches can originate from a short-lived local process.
    # Keep worker threads non-daemon so helper runs are not orphaned when that host exits.
    if operator_text.startswith("pm-"):
        return False
    return True


def _assignment_execution_worker_guarded(
    root: Path,
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    workspace_path: Path,
    command: list[str],
    command_summary: str,
    prompt_text: str,
    operator: str = "",
) -> None:
    try:
        _assignment_execution_worker(
            root,
            run_id=run_id,
            ticket_id=ticket_id,
            node_id=node_id,
            workspace_path=workspace_path,
            command=command,
            command_summary=command_summary,
            prompt_text=prompt_text,
        )
    except Exception as exc:
        failed_at = iso_ts(now_local())
        failure_message = f"assignment execution worker bootstrap failed: {exc}"
        traceback_text = traceback.format_exc()
        try:
            files = _assignment_run_file_paths(root, ticket_id, run_id)
            _append_assignment_run_event(
                files["events"],
                event_type="provider_start_failed",
                message=f"Provider 启动前异常: {exc}",
                created_at=failed_at,
                detail={
                    "exception_type": type(exc).__name__,
                    "operator": str(operator or "").strip(),
                },
            )
            _append_assignment_run_text(files["stderr"], traceback_text)
        except Exception:
            pass
        try:
            _finalize_assignment_execution_run(
                root,
                run_id=run_id,
                ticket_id=ticket_id,
                node_id=node_id,
                exit_code=1,
                stdout_text="",
                stderr_text=traceback_text,
                result_payload={},
                failure_message=failure_message,
            )
        except Exception:
            pass


def _assignment_dispatch_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    def _workflow_lane_rank(node: dict[str, Any]) -> int:
        if _assignment_is_workflow_mainline_node(node):
            return 0
        if _assignment_is_workflow_patrol_node(node):
            return 2
        return 1

    rows = [
        dict(node)
        for node in list(snapshot.get("nodes") or [])
        if str(node.get("status") or "").strip().lower() == "ready"
    ]
    rows.sort(
        key=lambda item: (
            int(item.get("priority") or 0),
            _workflow_lane_rank(item),
            str(item.get("created_at") or ""),
            str(item.get("node_id") or ""),
        )
    )
    return rows


def _assignment_dispatch_snapshot(
    root: Path,
    *,
    ticket_id: str,
    include_test_data: bool,
    reconcile_running: bool,
) -> dict[str, Any]:
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
        reconcile_running=reconcile_running,
    )
    if changed:
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    active_nodes = _assignment_active_node_records(node_records)
    settings = get_assignment_concurrency_settings(root)
    system_counts = _assignment_system_running_counts(root, include_test_data=include_test_data)
    scheduler_payload = _assignment_scheduler_payload(
        task_record,
        active_nodes,
        system_limit=int(settings.get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
        settings_updated_at=str(settings.get("updated_at") or ""),
        system_counts=system_counts,
    )
    edges = _assignment_active_edges(task_record, active_nodes)
    node_map_by_id = _node_map(active_nodes)
    upstream_map, downstream_map = _edge_maps(edges)
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
        "serialized_nodes": [],
    }


def _assignment_dispatch_drain_state(task_record: dict[str, Any]) -> dict[str, Any]:
    current = dict(task_record or {})
    if bool(current.get("is_test_data")):
        return {"active": False, "code": "", "reason": "", "message": ""}
    try:
        from workflow_app.server.services import runtime_upgrade_service

        drain_state = runtime_upgrade_service.runtime_upgrade_drain_state()
    except Exception:
        drain_state = {}
    active = bool(drain_state.get("active"))
    reason_code = str(drain_state.get("code") or "").strip()
    reason_text = _short_assignment_text(str(drain_state.get("reason") or "").strip(), 500)
    message = ""
    if active:
        marker = reason_code or "unknown"
        message = f"[upgrade_drain_active:{marker}] {reason_text or 'prod upgrade drain active'}"
    return {
        "active": active,
        "code": reason_code,
        "reason": reason_text,
        "message": message,
        "environment": str(drain_state.get("environment") or "").strip(),
        "current_version": str(drain_state.get("current_version") or "").strip(),
        "candidate_version": str(drain_state.get("candidate_version") or "").strip(),
    }


def _prepare_assignment_execution_run(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    now_text: str,
    snapshot_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_assignment_support_tables(root)
    snapshot = dict(snapshot_override or {})
    if not snapshot:
        snapshot = _assignment_snapshot_from_files(
            root,
            ticket_id,
            include_test_data=True,
            reconcile_running=True,
        )
    serialized_node = next(
        (
            node
            for node in list(snapshot.get("serialized_nodes") or [])
            if str(node.get("node_id") or "").strip() == node_id
        ),
        {},
    )
    if not serialized_node:
        target_node = next(
            (
                dict(node)
                for node in list(snapshot.get("nodes") or [])
                if str(node.get("node_id") or "").strip() == node_id
            ),
            {},
        )
        if target_node:
            serialized_node = _serialize_node(
                target_node,
                node_map_by_id=dict(snapshot.get("node_map_by_id") or {}),
                upstream_map=dict(snapshot.get("upstream_map") or {}),
                downstream_map=dict(snapshot.get("downstream_map") or {}),
            )
    if not serialized_node:
        raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found", {"node_id": node_id})
    upstream_nodes = [
        snapshot["node_map_by_id"].get(str(item.get("node_id") or "").strip()) or {}
        for item in list(serialized_node.get("upstream_nodes") or [])
    ]
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        workspace_path = _resolve_assignment_workspace_path(
            conn,
            root,
            agent_id=str(serialized_node.get("assigned_agent_id") or "").strip(),
        )
        settings = _assignment_execution_settings_from_conn(conn)
        conn.commit()
    finally:
        conn.close()
    provider = _normalize_execution_provider(settings.get("execution_provider"))
    prompt_text = _build_assignment_execution_prompt(
        graph_row=snapshot["graph_row"],
        node=serialized_node,
        upstream_nodes=upstream_nodes,
        workspace_path=workspace_path,
        delivery_inbox_path=_node_delivery_inbox_dir(root, serialized_node),
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
    run_record = _assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider=provider,
        workspace_path=workspace_path.as_posix(),
        status="starting",
        command_summary=command_summary,
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="已创建运行批次，等待 provider 启动。",
        latest_event_at=now_text,
        exit_code=0,
        started_at=now_text,
        finished_at="",
        created_at=now_text,
        updated_at=now_text,
    )
    _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
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


def dispatch_assignment_next(
    root: Path,
    *,
    ticket_id_text: str,
    operator: str,
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    with _assignment_ticket_dispatch_lock(ticket_id):
        operator_text = _default_assignment_operator(operator)
        now_text = iso_ts(now_local())
        use_lightweight_snapshot = operator_text == "schedule-worker"
        if use_lightweight_snapshot:
            snapshot = _assignment_dispatch_snapshot(
                root,
                ticket_id=ticket_id,
                include_test_data=include_test_data,
                reconcile_running=True,
            )
        else:
            snapshot = _assignment_snapshot_from_files(
                root,
                ticket_id,
                include_test_data=include_test_data,
                reconcile_running=True,
            )
        ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
        task_record = dict(snapshot["graph_row"])
        node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
        scheduler_state = str(task_record.get("scheduler_state") or "").strip().lower()
        if scheduler_state != "running":
            return {
                "ticket_id": ticket_id,
                "dispatched": [],
                "dispatched_runs": [],
                "skipped": [],
                "message": "scheduler_not_running",
                "graph_overview": _graph_overview_payload(
                    snapshot["graph_row"],
                    metrics_summary=snapshot["metrics_summary"],
                    scheduler_state_payload=snapshot["scheduler"],
                ),
            }
        drain_state = _assignment_dispatch_drain_state(task_record)
        if bool(drain_state.get("active")):
            drain_message = str(drain_state.get("message") or "").strip() or "[upgrade_drain_active] prod upgrade drain active"
            return {
                "ticket_id": ticket_id,
                "dispatched": [],
                "dispatched_runs": [],
                "skipped": [
                    {
                        "code": "upgrade_drain_active",
                        "message": drain_message,
                    }
                ],
                "message": drain_message,
                "code": "upgrade_drain_active",
                "drain": drain_state,
                "graph_overview": _graph_overview_payload(
                    snapshot["graph_row"],
                    metrics_summary=snapshot["metrics_summary"],
                    scheduler_state_payload=snapshot["scheduler"],
                ),
            }
        system_limit = int(snapshot["scheduler"].get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT)
        effective_limit = int(snapshot["scheduler"].get("effective_concurrency_limit") or system_limit)
        graph_running_count = int(snapshot["scheduler"].get("graph_running_node_count") or 0)
        system_running_state = _assignment_system_running_state(root, include_test_data=include_test_data)
        graph_slots = max(0, effective_limit - graph_running_count)
        system_slots = max(0, system_limit - int(system_running_state.get("running_node_count") or 0))
        dispatch_slots = min(graph_slots, system_slots)
        if dispatch_slots <= 0:
            return {
                "ticket_id": ticket_id,
                "dispatched": [],
                "dispatched_runs": [],
                "skipped": [
                    {
                        "code": "concurrency_limit_reached",
                        "message": "global_or_graph_concurrency_limit_reached",
                    }
                ],
                "graph_overview": _graph_overview_payload(
                    snapshot["graph_row"],
                    metrics_summary=snapshot["metrics_summary"],
                    scheduler_state_payload=snapshot["scheduler"],
                ),
            }
        running_agents = set(system_running_state.get("running_agents") or set())
        dispatched: list[dict[str, Any]] = []
        dispatched_runs: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        pending_execution_runs: list[dict[str, Any]] = []
        changed = False
        for candidate in _assignment_dispatch_candidates(snapshot):
            if dispatch_slots <= 0:
                break
            node_id = str(candidate.get("node_id") or "").strip()
            agent_id = str(candidate.get("assigned_agent_id") or "").strip()
            if not node_id or not agent_id:
                continue
            active_run = _assignment_active_run_record(root, ticket_id=ticket_id, node_id=node_id)
            if active_run:
                for row in node_records:
                    if str(row.get("node_id") or "").strip() != node_id:
                        continue
                    if str(row.get("status") or "").strip().lower() != "running":
                        row["status"] = "running"
                        row["status_text"] = _node_status_text("running")
                        row["updated_at"] = now_text
                        changed = True
                    break
                task_record["updated_at"] = now_text
                skipped.append(
                    {
                        "node_id": node_id,
                        "code": "node_already_running",
                        "message": str(active_run.get("run_id") or "node already has active run"),
                    }
                )
                continue
            if agent_id in running_agents:
                skipped.append(
                    {
                        "node_id": node_id,
                        "code": "agent_busy",
                        "message": "assigned agent already has running node",
                    }
                )
                continue
            try:
                execution_run = _prepare_assignment_execution_run(
                    root,
                    ticket_id=ticket_id,
                    node_id=node_id,
                    now_text=now_text,
                    snapshot_override=snapshot if use_lightweight_snapshot else None,
                )
            except AssignmentCenterError as exc:
                for row in node_records:
                    if str(row.get("node_id") or "").strip() != node_id:
                        continue
                    row["status"] = "failed"
                    row["status_text"] = _node_status_text("failed")
                    row["completed_at"] = now_text
                    row["success_reason"] = ""
                    row["result_ref"] = ""
                    row["failure_reason"] = _short_assignment_text(str(exc), 500) or "dispatch preparation failed"
                    row["updated_at"] = now_text
                    break
                task_record["updated_at"] = now_text
                _assignment_write_audit_entry(
                    root,
                    ticket_id=ticket_id,
                    node_id=node_id,
                    action="dispatch_failed",
                    operator=operator_text,
                    reason=_short_assignment_text(str(exc), 500) or "dispatch preparation failed",
                    target_status="failed",
                    detail={"code": exc.code, **exc.extra},
                    created_at=now_text,
                )
                skipped.append(
                    {
                        "node_id": node_id,
                        "code": str(exc.code or "dispatch_prepare_failed"),
                        "message": str(exc),
                    }
                )
                changed = True
                continue
            for row in node_records:
                if str(row.get("node_id") or "").strip() != node_id:
                    continue
                row["status"] = "running"
                row["status_text"] = _node_status_text("running")
                row["updated_at"] = now_text
                break
            task_record["updated_at"] = now_text
            audit_id = _assignment_write_audit_entry(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
                action="dispatch",
                operator=operator_text,
                reason="dispatch next ready node",
                target_status="running",
                detail={
                    "assigned_agent_id": agent_id,
                    "priority": int(candidate.get("priority") or 0),
                    "run_id": str(execution_run.get("run_id") or "").strip(),
                    "provider": str(execution_run.get("provider") or "").strip(),
                    "workspace_path": str((execution_run.get("workspace_path") or Path(".")).as_posix()),
                    "prompt_ref": execution_run.get("files", {}).get("prompt").as_posix(),
                    "stdout_ref": execution_run.get("files", {}).get("stdout").as_posix(),
                    "stderr_ref": execution_run.get("files", {}).get("stderr").as_posix(),
                    "result_ref": execution_run.get("files", {}).get("result").as_posix(),
                },
                created_at=now_text,
            )
            running_agents.add(agent_id)
            dispatch_slots -= 1
            changed = True
            pending_execution_runs.append(execution_run)
            dispatched.append({"node_id": node_id, "audit_id": audit_id, "run_id": str(execution_run.get("run_id") or "").strip()})
            dispatched_runs.append(
                {
                    "run_id": str(execution_run.get("run_id") or "").strip(),
                    "ticket_id": ticket_id,
                    "node_id": node_id,
                    "provider": str(execution_run.get("provider") or "").strip(),
                    "workspace_path": str((execution_run.get("workspace_path") or Path(".")).as_posix()),
                    "command_summary": str(execution_run.get("command_summary") or "").strip(),
                    "prompt_ref": execution_run.get("files", {}).get("prompt").as_posix(),
                    "stdout_ref": execution_run.get("files", {}).get("stdout").as_posix(),
                    "stderr_ref": execution_run.get("files", {}).get("stderr").as_posix(),
                    "result_ref": execution_run.get("files", {}).get("result").as_posix(),
                }
            )
        if changed:
            task_record, node_records, _changed = _assignment_recompute_task_state(
                root,
                task_record=task_record,
                node_records=node_records,
                reconcile_running=False,
            )
            _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
            snapshot = _assignment_snapshot_from_files(
                root,
                ticket_id,
                include_test_data=include_test_data,
                reconcile_running=False,
            )
        for execution_run in pending_execution_runs:
            try:
                thread = threading.Thread(
                    target=_assignment_execution_worker_guarded,
                    kwargs={
                        "root": root,
                        "run_id": str(execution_run.get("run_id") or "").strip(),
                        "ticket_id": ticket_id,
                        "node_id": str(execution_run.get("node_id") or "").strip(),
                        "workspace_path": execution_run.get("workspace_path"),
                        "command": list(execution_run.get("command") or []),
                        "command_summary": str(execution_run.get("command_summary") or "").strip(),
                        "prompt_text": str(execution_run.get("prompt_text") or ""),
                        "operator": operator_text,
                    },
                    daemon=_assignment_execution_thread_should_daemon(operator_text),
                )
                thread.start()
            except Exception as exc:
                _append_assignment_run_event(
                    execution_run.get("files", {}).get("events"),
                    event_type="provider_start_failed",
                    message=f"后台线程启动失败: {exc}",
                    created_at=iso_ts(now_local()),
                    detail={},
                )
                _finalize_assignment_execution_run(
                    root,
                    run_id=str(execution_run.get("run_id") or "").strip(),
                    ticket_id=ticket_id,
                    node_id=str(execution_run.get("node_id") or "").strip(),
                    exit_code=1,
                    stdout_text="",
                    stderr_text=str(exc),
                    result_payload={},
                    failure_message=f"assignment execution worker start failed: {exc}",
                    suppress_followup_dispatch=True,
                )
        dispatched_node_ids = {item["node_id"] for item in dispatched}
        dispatched_nodes = [
            node
            for node in list(snapshot.get("serialized_nodes") or [])
            if str(node.get("node_id") or "").strip() in dispatched_node_ids
        ]
        return {
            "ticket_id": ticket_id,
            "dispatched": dispatched_nodes,
            "dispatched_runs": dispatched_runs,
            "skipped": skipped,
            "graph_overview": _graph_overview_payload(
                snapshot["graph_row"],
                metrics_summary=snapshot["metrics_summary"],
                scheduler_state_payload=snapshot["scheduler"],
            ),
        }


def pause_assignment_scheduler(
    root: Path,
    *,
    ticket_id_text: str,
    operator: str,
    pause_note: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator_text = _default_assignment_operator(operator)
    note_text = _normalize_text(pause_note, field="pause_note", required=False, max_len=500)
    now_text = iso_ts(now_local())
    with _assignment_ticket_mutation_lock(ticket_id):
        snapshot = _assignment_snapshot_from_files(
            root,
            ticket_id,
            include_test_data=include_test_data,
            reconcile_running=True,
        )
        ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
        task_record = dict(snapshot["graph_row"])
        node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
        running_count = sum(
            1
            for node in _assignment_active_node_records(node_records)
            if str(node.get("status") or "").strip().lower() == "running"
        )
        next_state = "pause_pending" if running_count > 0 else "paused"
        task_record["scheduler_state"] = next_state
        task_record["pause_note"] = note_text
        task_record["updated_at"] = now_text
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id="",
        action="pause_scheduler",
        operator=operator_text,
        reason=note_text or "pause scheduler",
        target_status=next_state,
        detail={"running_count": running_count},
        created_at=now_text,
    )
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=False,
    )
    return {
        "ticket_id": ticket_id,
        "state": next_state,
        "state_text": _scheduler_state_text(next_state),
        "pause_note": note_text,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }


def resume_assignment_scheduler(
    root: Path,
    *,
    ticket_id_text: str,
    operator: str,
    pause_note: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator_text = _default_assignment_operator(operator)
    note_text = _normalize_text(pause_note, field="pause_note", required=False, max_len=500)
    now_text = iso_ts(now_local())
    with _assignment_ticket_mutation_lock(ticket_id):
        snapshot = _assignment_snapshot_from_files(
            root,
            ticket_id,
            include_test_data=include_test_data,
            reconcile_running=True,
        )
        ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
        task_record = dict(snapshot["graph_row"])
        node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
        task_record["scheduler_state"] = "running"
        task_record["pause_note"] = note_text
        task_record["updated_at"] = now_text
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id="",
        action="resume_scheduler",
        operator=operator_text,
        reason=note_text or "resume scheduler",
        target_status="running",
        detail={},
        created_at=now_text,
    )
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=False,
    )
    graph_overview = _graph_overview_payload(
        snapshot["graph_row"],
        metrics_summary=snapshot["metrics_summary"],
        scheduler_state_payload=snapshot["scheduler"],
    )
    drain_state = _assignment_dispatch_drain_state(task_record)
    if bool(drain_state.get("active")):
        return {
            "ticket_id": ticket_id,
            "state": "running",
            "state_text": _scheduler_state_text("running"),
            "pause_note": note_text,
            "audit_id": audit_id,
            "graph_overview": graph_overview,
            "dispatch_result": {
                "mode": "drain",
                "pending": False,
                "code": "upgrade_drain_active",
                "message": str(drain_state.get("message") or "").strip() or "[upgrade_drain_active] prod upgrade drain active",
                "drain": drain_state,
            },
        }

    def _dispatch_after_resume() -> None:
        try:
            dispatch_assignment_next(
                root,
                ticket_id_text=ticket_id,
                operator=operator_text,
                include_test_data=include_test_data,
            )
        except Exception:
            return

    dispatch_thread = threading.Thread(
        target=_dispatch_after_resume,
        daemon=True,
    )
    dispatch_thread.start()
    return {
        "ticket_id": ticket_id,
        "state": "running",
        "state_text": _scheduler_state_text("running"),
        "pause_note": note_text,
        "audit_id": audit_id,
        "graph_overview": graph_overview,
        "dispatch_result": {
            "mode": "async",
            "pending": True,
        },
    }


def clear_assignment_graph(
    root: Path,
    *,
    ticket_id_text: str,
    operator: str,
    reason: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator_text = _default_assignment_operator(operator)
    reason_text = _normalize_text(reason, field="reason", required=False, max_len=1000)
    now_text = iso_ts(now_local())
    with _assignment_ticket_mutation_lock(ticket_id):
        snapshot = _assignment_snapshot_from_files(
            root,
            ticket_id,
            include_test_data=include_test_data,
            reconcile_running=True,
        )
        ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
        task_record = dict(snapshot["graph_row"])
        node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
        active_nodes = _assignment_active_node_records(node_records)
        running_nodes = [
            node
            for node in active_nodes
            if str(node.get("status") or "").strip().lower() == "running"
        ]
        if running_nodes:
            raise AssignmentCenterError(
                409,
                "running nodes prevent clear",
                "assignment_clear_has_running_nodes",
                {
                    "running_node_ids": [
                        str(node.get("node_id") or "").strip()
                        for node in running_nodes
                    ],
                },
            )
        removed_node_count = 0
        for row in node_records:
            if str(row.get("record_state") or "active").strip().lower() == "deleted":
                continue
            removed_node_count += 1
            row["record_state"] = "deleted"
            row["delete_meta"] = {
                "delete_action": "clear_graph",
                "deleted_at": now_text,
                "delete_reason": reason_text or "clear assignment graph",
            }
            row["updated_at"] = now_text
        removed_edge_count = len(_assignment_active_edges(task_record, active_nodes))
        task_record["edges"] = []
        task_record["scheduler_state"] = "idle"
        task_record["pause_note"] = ""
        task_record["updated_at"] = now_text
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id="",
        action="clear_graph",
        operator=operator_text,
        reason=reason_text or "clear assignment graph",
        target_status="idle",
        detail={
            "removed_node_count": removed_node_count,
            "removed_edge_count": removed_edge_count,
        },
        created_at=now_text,
    )
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=False,
    )
    return {
        "ticket_id": ticket_id,
        "removed_node_count": removed_node_count,
        "removed_edge_count": removed_edge_count,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }
