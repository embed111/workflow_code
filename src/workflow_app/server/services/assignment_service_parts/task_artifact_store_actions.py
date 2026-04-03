from __future__ import annotations


def _assignment_edge_rows_from_pairs(edges: list[tuple[str, str]], *, created_at: str) -> list[dict[str, Any]]:
    return [
        {
            "from_node_id": str(from_id or "").strip(),
            "to_node_id": str(to_id or "").strip(),
            "edge_kind": "depends_on",
            "created_at": created_at,
            "record_state": "active",
        }
        for from_id, to_id in list(edges or [])
        if str(from_id or "").strip() and str(to_id or "").strip()
    ]


def create_assignment_graph(cfg: Any, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_assignment_support_tables(cfg.root)
    operator = _default_assignment_operator(body.get("operator"))
    now_text = iso_ts(now_local())
    raw_nodes = body.get("nodes") if isinstance(body.get("nodes"), list) else []
    raw_edges = body.get("edges") if isinstance(body.get("edges"), list) else []
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        graph_payload = _normalize_graph_header(conn, body)
        conn.commit()
    finally:
        conn.close()
    external_request_id = str(graph_payload["external_request_id"] or "").strip()
    if external_request_id:
        existed_ticket_id = _assignment_find_ticket_by_source_request(
            cfg.root,
            source_workflow=str(graph_payload["source_workflow"]),
            external_request_id=external_request_id,
        )
        if existed_ticket_id:
            snapshot = _assignment_snapshot_from_files(
                cfg.root,
                existed_ticket_id,
                include_test_data=True,
                reconcile_running=True,
            )
            return {
                "ticket_id": existed_ticket_id,
                "created": False,
                "graph_overview": _graph_overview_payload(
                    snapshot["graph_row"],
                    metrics_summary=snapshot["metrics_summary"],
                    scheduler_state_payload=snapshot["scheduler"],
                ),
            }
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        node_payloads = [
            _normalize_node_payload(
                conn,
                cfg,
                raw if isinstance(raw, dict) else {},
                node_id="",
                source_workflow=graph_payload["source_workflow"],
            )
            for raw in raw_nodes
        ]
        conn.commit()
    finally:
        conn.close()
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
    ticket_id = assignment_ticket_id()
    task_record = _assignment_build_task_record(
        ticket_id=ticket_id,
        graph_name=str(graph_payload["graph_name"]),
        source_workflow=str(graph_payload["source_workflow"]),
        summary=str(graph_payload["summary"]),
        review_mode=str(graph_payload["review_mode"]),
        global_concurrency_limit=int(graph_payload["global_concurrency_limit"]),
        is_test_data=bool(graph_payload.get("is_test_data")),
        external_request_id=external_request_id,
        scheduler_state="idle",
        pause_note="",
        created_at=now_text,
        updated_at=now_text,
        edges=_assignment_edge_rows_from_pairs(collected_edges, created_at=now_text),
    )
    node_records = [
        _assignment_build_node_record(
            ticket_id=ticket_id,
            node_id=str(node["node_id"]),
            node_name=str(node["node_name"]),
            source_schedule_id=str(node.get("source_schedule_id") or ""),
            planned_trigger_at=str(node.get("planned_trigger_at") or ""),
            trigger_instance_id=str(node.get("trigger_instance_id") or ""),
            trigger_rule_summary=str(node.get("trigger_rule_summary") or ""),
            assigned_agent_id=str(node["assigned_agent_id"]),
            assigned_agent_name=str(node.get("assigned_agent_name") or node["assigned_agent_id"]),
            node_goal=str(node["node_goal"]),
            expected_artifact=str(node["expected_artifact"]),
            delivery_mode=str(node.get("delivery_mode") or "none"),
            delivery_receiver_agent_id=str(node.get("delivery_receiver_agent_id") or ""),
            delivery_receiver_agent_name=str(node.get("delivery_receiver_agent_name") or ""),
            artifact_delivery_status="pending",
            artifact_delivered_at="",
            artifact_paths=[],
            status="pending",
            priority=int(node["priority"]),
            completed_at="",
            success_reason="",
            result_ref="",
            failure_reason="",
            created_at=now_text,
            updated_at=now_text,
            upstream_node_ids=list(node.get("upstream_node_ids") or []),
            downstream_node_ids=list(node.get("downstream_node_ids") or []),
        )
        for node in node_payloads
    ]
    task_record, node_records, _changed = _assignment_recompute_task_state(
        cfg.root,
        task_record=task_record,
        node_records=node_records,
        reconcile_running=False,
    )
    _assignment_store_snapshot(cfg.root, task_record=task_record, node_records=node_records)
    if _assignment_is_workflow_ui_global_graph_payload(graph_payload):
        ticket_id = _assignment_bind_workflow_ui_global_graph_ticket(cfg.root, ticket_id) or ticket_id
    audit_id = _assignment_write_audit_entry(
        cfg.root,
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
            "tasks_root": _assignment_tasks_root(cfg.root).as_posix(),
        },
        created_at=now_text,
    )
    snapshot = _assignment_snapshot_from_files(
        cfg.root,
        ticket_id,
        include_test_data=True,
        reconcile_running=False,
    )
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
    snapshot = _assignment_snapshot_from_files(
        cfg.root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        node_payload = _normalize_node_payload(
            conn,
            cfg,
            body,
            node_id="",
            source_workflow=str(snapshot["graph_row"].get("source_workflow") or "").strip(),
        )
        conn.commit()
    finally:
        conn.close()
    existing_nodes = list(snapshot["nodes"] or [])
    existing_node_ids = {str(node.get("node_id") or "").strip() for node in existing_nodes}
    if str(node_payload["node_id"]) in existing_node_ids:
        raise AssignmentCenterError(409, "node_id duplicated", "node_id_duplicated")
    _validate_node_ids_exist(
        all_node_ids=existing_node_ids,
        upstream_node_ids=list(node_payload["upstream_node_ids"]),
        downstream_node_ids=list(node_payload["downstream_node_ids"]),
    )
    existing_edges = _assignment_edge_pairs(snapshot["edges"])
    new_edges = _collect_edges_from_request(node_payloads=[node_payload], explicit_edges=[])
    _assert_no_cycles(existing_node_ids | {str(node_payload["node_id"])}, existing_edges + new_edges)
    task_record = dict(snapshot["graph_row"])
    node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
    node_records.append(
        _assignment_build_node_record(
            ticket_id=ticket_id,
            node_id=str(node_payload["node_id"]),
            node_name=str(node_payload["node_name"]),
            source_schedule_id=str(node_payload.get("source_schedule_id") or ""),
            planned_trigger_at=str(node_payload.get("planned_trigger_at") or ""),
            trigger_instance_id=str(node_payload.get("trigger_instance_id") or ""),
            trigger_rule_summary=str(node_payload.get("trigger_rule_summary") or ""),
            assigned_agent_id=str(node_payload["assigned_agent_id"]),
            assigned_agent_name=str(node_payload.get("assigned_agent_name") or node_payload["assigned_agent_id"]),
            node_goal=str(node_payload["node_goal"]),
            expected_artifact=str(node_payload["expected_artifact"]),
            delivery_mode=str(node_payload.get("delivery_mode") or "none"),
            delivery_receiver_agent_id=str(node_payload.get("delivery_receiver_agent_id") or ""),
            delivery_receiver_agent_name=str(node_payload.get("delivery_receiver_agent_name") or ""),
            artifact_delivery_status="pending",
            artifact_delivered_at="",
            artifact_paths=[],
            status="pending",
            priority=int(node_payload["priority"]),
            completed_at="",
            success_reason="",
            result_ref="",
            failure_reason="",
            created_at=now_text,
            updated_at=now_text,
            upstream_node_ids=list(node_payload.get("upstream_node_ids") or []),
            downstream_node_ids=list(node_payload.get("downstream_node_ids") or []),
        )
    )
    task_record["edges"] = list(task_record.get("edges") or []) + _assignment_edge_rows_from_pairs(new_edges, created_at=now_text)
    task_record["updated_at"] = now_text
    task_record, node_records, _changed = _assignment_recompute_task_state(
        cfg.root,
        task_record=task_record,
        node_records=node_records,
        reconcile_running=False,
    )
    _assignment_store_snapshot(cfg.root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        cfg.root,
        ticket_id=ticket_id,
        node_id=str(node_payload["node_id"]),
        action="create_node",
        operator=operator,
        reason="create assignment node",
        target_status="pending",
        detail={
            "node_name": node_payload["node_name"],
            "source_schedule_id": node_payload.get("source_schedule_id") or "",
            "planned_trigger_at": node_payload.get("planned_trigger_at") or "",
            "trigger_instance_id": node_payload.get("trigger_instance_id") or "",
            "trigger_rule_summary": node_payload.get("trigger_rule_summary") or "",
            "assigned_agent_id": node_payload["assigned_agent_id"],
            "priority": int(node_payload["priority"]),
            "priority_label": assignment_priority_label(node_payload["priority"]),
            "upstream_node_ids": list(node_payload["upstream_node_ids"]),
            "downstream_node_ids": list(node_payload["downstream_node_ids"]),
            "expected_artifact": node_payload["expected_artifact"],
            "delivery_mode": node_payload["delivery_mode"],
            "delivery_receiver_agent_id": node_payload["delivery_receiver_agent_id"],
        },
        created_at=now_text,
    )
    response_snapshot = _assignment_response_snapshot_from_records(
        task_record=task_record,
        node_records=node_records,
        scheduler_payload=snapshot.get("scheduler"),
    )
    created_node = next(
        (
            node
            for node in list(response_snapshot["serialized_nodes"] or [])
            if str(node.get("node_id") or "").strip() == str(node_payload["node_id"])
        ),
        {},
    )
    return {
        "ticket_id": ticket_id,
        "node": created_node,
        "graph_overview": _graph_overview_payload(
            response_snapshot["graph_row"],
            metrics_summary=response_snapshot["metrics_summary"],
            scheduler_state_payload=response_snapshot["scheduler"],
        ),
        "audit_id": audit_id,
    }


def _assignment_response_snapshot_from_records(
    *,
    task_record: dict[str, Any],
    node_records: list[dict[str, Any]],
    scheduler_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_nodes = _assignment_active_node_records(node_records)
    edges = _assignment_active_edges(task_record, active_nodes)
    node_map_by_id = _node_map(active_nodes)
    upstream_map, downstream_map = _edge_maps(edges)
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
        "scheduler": dict(scheduler_payload or {}),
        "serialized_nodes": serialized_nodes,
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
    raw_nodes = (body or {}).get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise AssignmentCenterError(400, "nodes required", "assignment_nodes_required")
    operator = _default_assignment_operator((body or {}).get("operator"))
    now_text = iso_ts(now_local())
    snapshot = _assignment_snapshot_from_files(
        cfg.root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        node_payloads = [
            _normalize_node_payload(
                conn,
                cfg,
                raw if isinstance(raw, dict) else {},
                node_id="",
                source_workflow=str(snapshot["graph_row"].get("source_workflow") or "").strip(),
            )
            for raw in raw_nodes
        ]
        conn.commit()
    finally:
        conn.close()
    requested_node_ids = [str(node["node_id"]) for node in node_payloads]
    if len(set(requested_node_ids)) != len(requested_node_ids):
        raise AssignmentCenterError(409, "node_id duplicated", "node_id_duplicated")
    existing_nodes = list(snapshot["nodes"] or [])
    existing_node_ids = {str(node.get("node_id") or "").strip() for node in existing_nodes}
    duplicated_node_ids = sorted(node_id for node_id in requested_node_ids if node_id in existing_node_ids)
    if duplicated_node_ids:
        raise AssignmentCenterError(
            409,
            "node_id duplicated",
            "node_id_duplicated",
            {"node_ids": duplicated_node_ids},
        )
    all_node_ids = existing_node_ids | set(requested_node_ids)
    combined_existing_edges = _assignment_edge_pairs(snapshot["edges"])
    new_edges = _collect_edges_from_request(node_payloads=node_payloads, explicit_edges=[])
    _validate_node_ids_exist(
        all_node_ids=all_node_ids,
        upstream_node_ids=[from_id for from_id, _to_id in new_edges],
        downstream_node_ids=[to_id for _from_id, to_id in new_edges],
    )
    _assert_no_cycles(all_node_ids, combined_existing_edges + new_edges)
    task_record = dict(snapshot["graph_row"])
    node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
    for node_payload in node_payloads:
        node_records.append(
            _assignment_build_node_record(
                ticket_id=ticket_id,
                node_id=str(node_payload["node_id"]),
                node_name=str(node_payload["node_name"]),
                source_schedule_id=str(node_payload.get("source_schedule_id") or ""),
                planned_trigger_at=str(node_payload.get("planned_trigger_at") or ""),
                trigger_instance_id=str(node_payload.get("trigger_instance_id") or ""),
                trigger_rule_summary=str(node_payload.get("trigger_rule_summary") or ""),
                assigned_agent_id=str(node_payload["assigned_agent_id"]),
                assigned_agent_name=str(node_payload.get("assigned_agent_name") or node_payload["assigned_agent_id"]),
                node_goal=str(node_payload["node_goal"]),
                expected_artifact=str(node_payload["expected_artifact"]),
                delivery_mode=str(node_payload.get("delivery_mode") or "none"),
                delivery_receiver_agent_id=str(node_payload.get("delivery_receiver_agent_id") or ""),
                delivery_receiver_agent_name=str(node_payload.get("delivery_receiver_agent_name") or ""),
                artifact_delivery_status="pending",
                artifact_delivered_at="",
                artifact_paths=[],
                status="pending",
                priority=int(node_payload["priority"]),
                completed_at="",
                success_reason="",
                result_ref="",
                failure_reason="",
                created_at=now_text,
                updated_at=now_text,
                upstream_node_ids=list(node_payload.get("upstream_node_ids") or []),
                downstream_node_ids=list(node_payload.get("downstream_node_ids") or []),
            )
        )
    task_record["edges"] = list(task_record.get("edges") or []) + _assignment_edge_rows_from_pairs(new_edges, created_at=now_text)
    task_record["updated_at"] = now_text
    task_record, node_records, _changed = _assignment_recompute_task_state(
        cfg.root,
        task_record=task_record,
        node_records=node_records,
        reconcile_running=False,
    )
    _assignment_store_snapshot(cfg.root, task_record=task_record, node_records=node_records)
    audit_ids: list[str] = []
    for node_payload in node_payloads:
        audit_ids.append(
            _assignment_write_audit_entry(
                cfg.root,
                ticket_id=ticket_id,
                node_id=str(node_payload["node_id"]),
                action="create_node",
                operator=operator,
                reason="create assignment node",
                target_status="pending",
                detail={
                    "node_name": node_payload["node_name"],
                    "source_schedule_id": node_payload.get("source_schedule_id") or "",
                    "planned_trigger_at": node_payload.get("planned_trigger_at") or "",
                    "trigger_instance_id": node_payload.get("trigger_instance_id") or "",
                    "trigger_rule_summary": node_payload.get("trigger_rule_summary") or "",
                    "assigned_agent_id": node_payload["assigned_agent_id"],
                    "priority": int(node_payload["priority"]),
                    "priority_label": assignment_priority_label(node_payload["priority"]),
                    "upstream_node_ids": list(node_payload["upstream_node_ids"]),
                    "downstream_node_ids": list(node_payload["downstream_node_ids"]),
                    "expected_artifact": node_payload["expected_artifact"],
                    "delivery_mode": node_payload["delivery_mode"],
                    "delivery_receiver_agent_id": node_payload["delivery_receiver_agent_id"],
                    "created_via": "batch",
                },
                created_at=now_text,
                sync_index=False,
            )
        )
    sync_assignment_task_bundle_index(cfg.root, ticket_id)
    response_snapshot = _assignment_response_snapshot_from_records(
        task_record=task_record,
        node_records=node_records,
        scheduler_payload=snapshot.get("scheduler"),
    )
    node_map = {
        str(node.get("node_id") or "").strip(): dict(node)
        for node in list(response_snapshot["serialized_nodes"] or [])
        if str(node.get("node_id") or "").strip()
    }
    created_nodes = [
        node_map.get(node_id, {})
        for node_id in requested_node_ids
        if node_map.get(node_id, {})
    ]
    return {
        "ticket_id": ticket_id,
        "nodes": created_nodes,
        "graph_overview": _graph_overview_payload(
            response_snapshot["graph_row"],
            metrics_summary=response_snapshot["metrics_summary"],
            scheduler_state_payload=response_snapshot["scheduler"],
        ),
        "audit_ids": audit_ids,
    }


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
