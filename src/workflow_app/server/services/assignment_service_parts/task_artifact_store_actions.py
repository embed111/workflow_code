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
    schedule_trigger_node = bool(
        str((body or {}).get("source_schedule_id") or "").strip()
        and str((body or {}).get("trigger_instance_id") or "").strip()
    )
    if schedule_trigger_node:
        task_record = _assignment_load_task_record(cfg.root, ticket_id)
        if not _assignment_task_visible(task_record, include_test_data=include_test_data):
            raise AssignmentCenterError(
                404,
                "assignment graph not found",
                "assignment_graph_not_found",
                {"ticket_id": ticket_id},
            )
        node_records = _assignment_load_node_records(cfg.root, ticket_id, include_deleted=True)
        snapshot = _assignment_response_snapshot_from_records(
            task_record=task_record,
            node_records=node_records,
            scheduler_payload={},
        )
    else:
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
