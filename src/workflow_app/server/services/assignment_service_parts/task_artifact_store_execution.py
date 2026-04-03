from __future__ import annotations


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
    operator_text = _default_assignment_operator(operator)
    now_text = iso_ts(now_local())
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
                target=_assignment_execution_worker,
                kwargs={
                    "root": root,
                    "run_id": str(execution_run.get("run_id") or "").strip(),
                    "ticket_id": ticket_id,
                    "node_id": str(execution_run.get("node_id") or "").strip(),
                    "workspace_path": execution_run.get("workspace_path"),
                    "command": list(execution_run.get("command") or []),
                    "command_summary": str(execution_run.get("command_summary") or "").strip(),
                    "prompt_text": str(execution_run.get("prompt_text") or ""),
                },
                daemon=True,
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
    graph_overview = _graph_overview_payload(
        snapshot["graph_row"],
        metrics_summary=snapshot["metrics_summary"],
        scheduler_state_payload=snapshot["scheduler"],
    )
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
