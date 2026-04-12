from __future__ import annotations


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
    with _assignment_ticket_mutation_lock(ticket_id):
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
        artifact_name = label_text or (
            str(selected_node.get("expected_artifact") or "").strip()
            or str(selected_node.get("node_name") or "").strip()
            or str(selected_node.get("node_id") or "").strip()
            or "任务产物"
        )
        now_text = iso_ts(now_local())
        payload = _artifact_delivery_markdown(
            selected_node,
            delivered_at=now_text,
            operator=operator_text,
            artifact_label=artifact_name,
            delivery_note=note_text,
        )
        graph_row, delivered_node, artifact_paths, audit_id = _deliver_assignment_artifact_locked(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            operator_text=operator_text,
            artifact_label=artifact_name,
            delivery_note=note_text,
            artifact_body=payload,
            now_text=now_text,
        )
    updated_snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=False,
    )
    return {
        "ticket_id": ticket_id,
        "node": delivered_node,
        "artifact_paths": artifact_paths,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            graph_row,
            metrics_summary=updated_snapshot["metrics_summary"],
            scheduler_state_payload=updated_snapshot["scheduler"],
        ),
    }


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
    result_ref_text = _normalize_text(result_ref, field="result_ref", required=False, max_len=1000)
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
    selected_node = next(
        (
            item
            for item in node_records
            if str(item.get("node_id") or "").strip() == node_id
            and str(item.get("record_state") or "active").strip().lower() != "deleted"
        ),
        {},
    )
    current_status = str(selected_node.get("status") or "").strip().lower()
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
    cancelled_run_ids = _assignment_cancel_active_runs(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        reason="任务被人工标记成功，已终止当前真实执行批次。",
        now_text=now_text,
    )
    selected_node["status"] = "succeeded"
    selected_node["status_text"] = _node_status_text("succeeded")
    selected_node["completed_at"] = now_text
    selected_node["success_reason"] = success_text
    selected_node["result_ref"] = result_ref_text
    selected_node["failure_reason"] = ""
    selected_node["updated_at"] = now_text
    task_record["updated_at"] = now_text
    task_record, node_records, _changed = _assignment_recompute_task_state(
        root,
        task_record=task_record,
        node_records=node_records,
        reconcile_running=False,
    )
    _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        action="mark_success",
        operator=operator_text,
        reason=success_text,
        target_status="succeeded",
        detail={"result_ref": result_ref_text, "cancelled_run_ids": cancelled_run_ids},
        created_at=now_text,
    )
    updated_snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=False,
    )
    selected = next(
        (node for node in list(updated_snapshot["serialized_nodes"] or []) if str(node.get("node_id") or "").strip() == node_id),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": selected,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            updated_snapshot["graph_row"],
            metrics_summary=updated_snapshot["metrics_summary"],
            scheduler_state_payload=updated_snapshot["scheduler"],
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
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    task_record = dict(snapshot["graph_row"])
    node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
    selected_node = next(
        (
            item
            for item in node_records
            if str(item.get("node_id") or "").strip() == node_id
            and str(item.get("record_state") or "active").strip().lower() != "deleted"
        ),
        {},
    )
    current_status = str(selected_node.get("status") or "").strip().lower()
    if current_status != "running":
        raise AssignmentCenterError(
            409,
            "mark-failed only allowed when node is running",
            "mark_failed_status_invalid",
            {"current_status": current_status},
        )
    cancelled_run_ids = _assignment_cancel_active_runs(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        reason="任务被人工标记失败，已终止当前真实执行批次。",
        now_text=now_text,
    )
    selected_node["status"] = "failed"
    selected_node["status_text"] = _node_status_text("failed")
    selected_node["completed_at"] = now_text
    selected_node["success_reason"] = ""
    selected_node["result_ref"] = ""
    selected_node["failure_reason"] = failure_text
    selected_node["updated_at"] = now_text
    task_record["updated_at"] = now_text
    task_record, node_records, _changed = _assignment_recompute_task_state(
        root,
        task_record=task_record,
        node_records=node_records,
        reconcile_running=False,
    )
    _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        action="mark_failed",
        operator=operator_text,
        reason=failure_text,
        target_status="failed",
        detail={"cancelled_run_ids": cancelled_run_ids},
        created_at=now_text,
    )
    updated_snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=False,
    )
    selected = next(
        (node for node in list(updated_snapshot["serialized_nodes"] or []) if str(node.get("node_id") or "").strip() == node_id),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": selected,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            updated_snapshot["graph_row"],
            metrics_summary=updated_snapshot["metrics_summary"],
            scheduler_state_payload=updated_snapshot["scheduler"],
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
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    task_record = dict(snapshot["graph_row"])
    node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
    selected_node = next(
        (
            item
            for item in node_records
            if str(item.get("node_id") or "").strip() == node_id
            and str(item.get("record_state") or "active").strip().lower() != "deleted"
        ),
        {},
    )
    current_status = str(selected_node.get("status") or "").strip().lower()
    if current_status != "failed":
        raise AssignmentCenterError(
            409,
            "rerun only allowed for failed node",
            "rerun_status_invalid",
            {"current_status": current_status},
        )
    selected_node["status"] = "pending"
    selected_node["status_text"] = _node_status_text("pending")
    selected_node["completed_at"] = ""
    selected_node["success_reason"] = ""
    selected_node["result_ref"] = ""
    selected_node["failure_reason"] = ""
    selected_node["artifact_delivery_status"] = "pending"
    selected_node["artifact_delivery_status_text"] = _artifact_delivery_status_text("pending")
    selected_node["artifact_delivered_at"] = ""
    selected_node["artifact_paths"] = []
    selected_node["updated_at"] = now_text
    task_record["updated_at"] = now_text
    task_record, node_records, _changed = _assignment_recompute_task_state(
        root,
        task_record=task_record,
        node_records=node_records,
        sticky_node_ids={node_id},
        reconcile_running=False,
    )
    _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        action="rerun",
        operator=operator_text,
        reason=reason_text or "rerun failed node",
        target_status="pending",
        detail={},
        created_at=now_text,
    )
    updated_snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=False,
    )
    selected = next(
        (node for node in list(updated_snapshot["serialized_nodes"] or []) if str(node.get("node_id") or "").strip() == node_id),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": selected,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            updated_snapshot["graph_row"],
            metrics_summary=updated_snapshot["metrics_summary"],
            scheduler_state_payload=updated_snapshot["scheduler"],
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
    result_ref: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    next_status = _normalize_status(target_status, field="target_status")
    operator_text = _default_assignment_operator(operator)
    reason_text = _normalize_text(reason, field="reason", required=True, max_len=1000)
    result_ref_text = _normalize_text(result_ref, field="result_ref", required=False, max_len=1000)
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
        selected_node = next(
            (
                item
                for item in node_records
                if str(item.get("node_id") or "").strip() == node_id
                and str(item.get("record_state") or "active").strip().lower() != "deleted"
            ),
            {},
        )
        if not selected_node:
            raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found")
        current_status = str(selected_node.get("status") or "").strip().lower()
        blocking_reasons = _node_blocking_reasons(
            node_id,
            node_map_by_id=snapshot["node_map_by_id"],
            upstream_map=snapshot["upstream_map"],
        )
        started_execution_run: dict[str, Any] | None = None
        if next_status == "running":
            if blocking_reasons:
                raise AssignmentCenterError(
                    409,
                    "override to running blocked by upstream",
                    "override_running_blocked_by_upstream",
                    {"blocking_reasons": blocking_reasons},
                )
            if str(task_record.get("scheduler_state") or "").strip().lower() != "running":
                raise AssignmentCenterError(
                    409,
                    "scheduler not running",
                    "scheduler_not_running",
                    {"scheduler_state": str(task_record.get("scheduler_state") or "").strip().lower()},
                )
            system_state = _assignment_system_running_state(root, include_test_data=include_test_data)
            system_limit = int(snapshot["scheduler"].get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT)
            effective_limit = int(snapshot["scheduler"].get("effective_concurrency_limit") or system_limit)
            graph_running_count = int(snapshot["scheduler"].get("graph_running_node_count") or 0)
            system_running_count = int(system_state.get("running_node_count") or 0)
            if graph_running_count >= effective_limit or system_running_count >= system_limit:
                raise AssignmentCenterError(409, "concurrency limit reached", "concurrency_limit_reached")
            running_agents = set(system_state.get("running_agents") or set())
            agent_id = str(selected_node.get("assigned_agent_id") or "").strip()
            if agent_id and agent_id in running_agents:
                raise AssignmentCenterError(
                    409,
                    "assigned agent already has running node",
                    "assigned_agent_busy",
                    {"assigned_agent_id": agent_id},
                )
            started_execution_run = _prepare_assignment_execution_run(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
                now_text=now_text,
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
        if current_status == "running" and next_status != "running":
            _assignment_cancel_active_runs(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
                reason="任务被人工修改执行状态，已终止当前真实执行批次。",
                now_text=now_text,
            )
        selected_node["status"] = next_status
        selected_node["status_text"] = _node_status_text(next_status)
        selected_node["updated_at"] = now_text
        if next_status == "succeeded":
            selected_node["completed_at"] = now_text
            selected_node["success_reason"] = "override: " + reason_text
            selected_node["result_ref"] = result_ref_text
            selected_node["failure_reason"] = ""
        elif next_status == "failed":
            selected_node["completed_at"] = now_text
            selected_node["success_reason"] = ""
            selected_node["result_ref"] = ""
            selected_node["failure_reason"] = "override: " + reason_text
        else:
            selected_node["completed_at"] = ""
            selected_node["success_reason"] = ""
            selected_node["result_ref"] = ""
            selected_node["failure_reason"] = ""
        task_record["updated_at"] = now_text
        sticky = {node_id} if next_status in {"pending", "ready", "blocked"} else set()
        task_record, node_records, _changed = _assignment_recompute_task_state(
            root,
            task_record=task_record,
            node_records=node_records,
            sticky_node_ids=sticky,
            reconcile_running=False,
        )
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
        audit_id = _assignment_write_audit_entry(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            action="override_status",
            operator=operator_text,
            reason=reason_text,
            target_status=next_status,
            detail={"from_status": current_status, "result_ref": result_ref_text},
            created_at=now_text,
        )
        updated_snapshot = _assignment_snapshot_from_files(
            root,
            ticket_id,
            include_test_data=include_test_data,
            reconcile_running=False,
        )
        updated_node = next(
            (node for node in list(updated_snapshot["serialized_nodes"] or []) if str(node.get("node_id") or "").strip() == node_id),
            {},
        )
    if started_execution_run:
        try:
            thread = threading.Thread(
                target=_assignment_execution_worker,
                kwargs={
                    "root": root,
                    "run_id": str(started_execution_run.get("run_id") or "").strip(),
                    "ticket_id": ticket_id,
                    "node_id": node_id,
                    "workspace_path": started_execution_run.get("workspace_path"),
                    "command": list(started_execution_run.get("command") or []),
                    "command_summary": str(started_execution_run.get("command_summary") or "").strip(),
                    "prompt_text": str(started_execution_run.get("prompt_text") or ""),
                },
                daemon=True,
            )
            thread.start()
        except Exception as exc:
            _finalize_assignment_execution_run(
                root,
                run_id=str(started_execution_run.get("run_id") or "").strip(),
                ticket_id=ticket_id,
                node_id=node_id,
                exit_code=1,
                stdout_text="",
                stderr_text=str(exc),
                result_payload={},
                failure_message=f"assignment execution worker start failed: {exc}",
                suppress_followup_dispatch=True,
            )
    return {
        "ticket_id": ticket_id,
        "node": updated_node,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            updated_snapshot["graph_row"],
            metrics_summary=updated_snapshot["metrics_summary"],
            scheduler_state_payload=updated_snapshot["scheduler"],
        ),
    }


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
        deleted_node = next(
            (
                item
                for item in node_records
                if str(item.get("node_id") or "").strip() == node_id
                and str(item.get("record_state") or "active").strip().lower() != "deleted"
            ),
            {},
        )
        if not deleted_node:
            raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found")
        if str(deleted_node.get("status") or "").strip().lower() == "running":
            raise AssignmentCenterError(
                409,
                "running node cannot be deleted",
                "assignment_delete_running_node_blocked",
                {"node_id": node_id},
            )
        bridge_plan = _plan_bridge_edges_after_delete(
            node_id=node_id,
            nodes=list(snapshot["nodes"] or []),
            edges=list(snapshot["edges"] or []),
        )
        remaining_edges = [
            edge
            for edge in list(snapshot["edges"] or [])
            if str(edge.get("from_node_id") or "").strip() != node_id
            and str(edge.get("to_node_id") or "").strip() != node_id
        ]
        remaining_edges.extend(
            _assignment_edge_rows_from_pairs(
                [
                    (
                        str(item.get("from_node_id") or "").strip(),
                        str(item.get("to_node_id") or "").strip(),
                    )
                    for item in list(bridge_plan.get("bridge_added") or [])
                ],
                created_at=now_text,
            )
        )
        deleted_node["record_state"] = "deleted"
        deleted_node["delete_meta"] = {
            "delete_action": "delete_node",
            "deleted_at": now_text,
            "delete_reason": reason_text or "delete assignment node",
            "bridge_summary": bridge_plan,
        }
        deleted_node["updated_at"] = now_text
        task_record["edges"] = remaining_edges
        task_record["updated_at"] = now_text
        task_record, node_records, _changed = _assignment_recompute_task_state(
            root,
            task_record=task_record,
            node_records=node_records,
            reconcile_running=False,
        )
        if not _assignment_active_node_records(node_records):
            task_record["scheduler_state"] = "idle"
            task_record["pause_note"] = ""
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
        audit_id = _assignment_write_audit_entry(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            action="delete_node",
            operator=operator_text,
            reason=reason_text or "delete assignment node",
            target_status="deleted",
            detail={
                "deleted_node": {
                    "node_id": str(deleted_node.get("node_id") or "").strip(),
                    "node_name": str(deleted_node.get("node_name") or "").strip(),
                    "status": str(deleted_node.get("status") or "").strip().lower(),
                },
                "bridge_summary": bridge_plan,
            },
            created_at=now_text,
        )
        updated_snapshot = _assignment_snapshot_from_files(
            root,
            ticket_id,
            include_test_data=include_test_data,
            reconcile_running=False,
        )
    return {
        "ticket_id": ticket_id,
        "deleted_node_id": node_id,
        "removed_edge_count": len(snapshot["edges"]) - len(remaining_edges),
        "bridge_summary": bridge_plan,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            updated_snapshot["graph_row"],
            metrics_summary=updated_snapshot["metrics_summary"],
            scheduler_state_payload=updated_snapshot["scheduler"],
        ),
    }
