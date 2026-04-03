

ASSIGNMENT_GLOBAL_GRAPH_NAME = "任务中心全局主图"
ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW = "workflow-ui"
ASSIGNMENT_GLOBAL_GRAPH_REQUEST_ID = "workflow-ui-global-graph-v1"
ASSIGNMENT_GLOBAL_GRAPH_SUMMARY = "任务中心手动创建（全局主图）"


def _node_blocking_reasons(
    node_id: str,
    *,
    node_map_by_id: dict[str, dict[str, Any]],
    upstream_map: dict[str, list[str]],
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    for upstream_id in list(upstream_map.get(node_id) or []):
        upstream = node_map_by_id.get(upstream_id) or {}
        upstream_status = str(upstream.get("status") or "").strip().lower()
        if upstream_status == "succeeded":
            continue
        reason_code = "upstream_failed" if upstream_status == "failed" else "upstream_incomplete"
        reasons.append(
            {
                "code": reason_code,
                "node_id": upstream_id,
                "node_name": str(upstream.get("node_name") or upstream_id),
                "status": upstream_status,
                "status_text": _node_status_text(upstream_status),
            }
        )
    return reasons


def _serialize_node(
    node: dict[str, Any],
    *,
    node_map_by_id: dict[str, dict[str, Any]],
    upstream_map: dict[str, list[str]],
    downstream_map: dict[str, list[str]],
) -> dict[str, Any]:
    node_id = str(node.get("node_id") or "").strip()
    upstream_ids = list(upstream_map.get(node_id) or [])
    downstream_ids = list(downstream_map.get(node_id) or [])
    status = str(node.get("status") or "").strip().lower()
    artifact_paths = list(node.get("artifact_paths") or [])
    delivery_target_agent_id = _node_delivery_target_agent_id(node)
    delivery_target_agent_name = _node_delivery_target_agent_name(node)
    delivery_inbox_relative_path = _node_delivery_inbox_relative_path(node)
    return {
        "node_id": node_id,
        "ticket_id": str(node.get("ticket_id") or "").strip(),
        "node_name": str(node.get("node_name") or "").strip(),
        "source_schedule_id": str(node.get("source_schedule_id") or "").strip(),
        "planned_trigger_at": str(node.get("planned_trigger_at") or "").strip(),
        "trigger_instance_id": str(node.get("trigger_instance_id") or "").strip(),
        "trigger_rule_summary": str(node.get("trigger_rule_summary") or "").strip(),
        "assigned_agent_id": str(node.get("assigned_agent_id") or "").strip(),
        "assigned_agent_name": str(
            node.get("assigned_agent_name") or node.get("assigned_agent_id") or ""
        ).strip(),
        "node_goal": str(node.get("node_goal") or "").strip(),
        "expected_artifact": str(node.get("expected_artifact") or "").strip(),
        "delivery_mode": str(node.get("delivery_mode") or "none").strip().lower() or "none",
        "delivery_mode_text": _delivery_mode_text(node.get("delivery_mode") or "none"),
        "delivery_receiver_agent_id": str(node.get("delivery_receiver_agent_id") or "").strip(),
        "delivery_receiver_agent_name": str(node.get("delivery_receiver_agent_name") or "").strip(),
        "delivery_target_agent_id": delivery_target_agent_id,
        "delivery_target_agent_name": delivery_target_agent_name,
        "delivery_inbox_relative_path": delivery_inbox_relative_path,
        "delivery_info_relative_path": _node_delivery_info_relative_path(node),
        "delivery_inbox_relative_paths": _node_delivery_inbox_relative_paths(node, artifact_paths),
        "artifact_delivery_status": str(node.get("artifact_delivery_status") or "pending").strip().lower() or "pending",
        "artifact_delivery_status_text": _artifact_delivery_status_text(
            node.get("artifact_delivery_status") or "pending"
        ),
        "artifact_delivered_at": str(node.get("artifact_delivered_at") or "").strip(),
        "artifact_paths": artifact_paths,
        "status": status,
        "status_text": _node_status_text(status),
        "priority": int(node.get("priority") or 0),
        "priority_label": assignment_priority_label(node.get("priority")),
        "completed_at": str(node.get("completed_at") or "").strip(),
        "success_reason": str(node.get("success_reason") or "").strip(),
        "result_ref": str(node.get("result_ref") or "").strip(),
        "failure_reason": str(node.get("failure_reason") or "").strip(),
        "created_at": str(node.get("created_at") or "").strip(),
        "updated_at": str(node.get("updated_at") or "").strip(),
        "upstream_node_ids": upstream_ids,
        "downstream_node_ids": downstream_ids,
        "upstream_nodes": [
            {
                "node_id": upstream_id,
                "node_name": str((node_map_by_id.get(upstream_id) or {}).get("node_name") or upstream_id),
                "status": str((node_map_by_id.get(upstream_id) or {}).get("status") or "").strip().lower(),
            }
            for upstream_id in upstream_ids
        ],
        "downstream_nodes": [
            {
                "node_id": downstream_id,
                "node_name": str((node_map_by_id.get(downstream_id) or {}).get("node_name") or downstream_id),
                "status": str((node_map_by_id.get(downstream_id) or {}).get("status") or "").strip().lower(),
            }
            for downstream_id in downstream_ids
        ],
        "blocking_reasons": _node_blocking_reasons(
            node_id,
            node_map_by_id=node_map_by_id,
            upstream_map=upstream_map,
        ),
        "last_receipt": {
            "completed_at": str(node.get("completed_at") or "").strip(),
            "success_reason": str(node.get("success_reason") or "").strip(),
            "result_ref": str(node.get("result_ref") or "").strip(),
            "failure_reason": str(node.get("failure_reason") or "").strip(),
        },
    }


def _graph_metrics(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "pending": 0,
        "ready": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "blocked": 0,
    }
    for node in nodes:
        status = str(node.get("status") or "").strip().lower()
        if status in counts:
            counts[status] += 1
    return {
        "total_nodes": len(nodes),
        "status_counts": counts,
        "executed_count": counts["running"] + counts["succeeded"] + counts["failed"],
        "unexecuted_count": counts["pending"] + counts["ready"] + counts["blocked"],
    }


def _graph_overview_payload(
    graph_row: sqlite3.Row,
    *,
    metrics_summary: dict[str, Any],
    scheduler_state_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ticket_id": str(graph_row["ticket_id"] or "").strip(),
        "graph_name": str(graph_row["graph_name"] or "").strip(),
        "source_workflow": str(graph_row["source_workflow"] or "").strip(),
        "summary": str(graph_row["summary"] or "").strip(),
        "review_mode": str(graph_row["review_mode"] or "").strip(),
        "global_concurrency_limit": int(graph_row["global_concurrency_limit"] or 0),
        "is_test_data": _row_is_test_data(graph_row),
        "external_request_id": str(graph_row["external_request_id"] or "").strip(),
        "scheduler_state": str(graph_row["scheduler_state"] or "").strip().lower(),
        "scheduler_state_text": _scheduler_state_text(graph_row["scheduler_state"]),
        "pause_note": str(graph_row["pause_note"] or "").strip(),
        "created_at": str(graph_row["created_at"] or "").strip(),
        "updated_at": str(graph_row["updated_at"] or "").strip(),
        "metrics_summary": metrics_summary,
        "scheduler": scheduler_state_payload,
    }


def _validate_node_ids_exist(
    *,
    all_node_ids: set[str],
    upstream_node_ids: list[str],
    downstream_node_ids: list[str],
) -> None:
    missing = [
        node_id
        for node_id in list(upstream_node_ids) + list(downstream_node_ids)
        if node_id not in all_node_ids
    ]
    if missing:
        raise AssignmentCenterError(
            400,
            "dependency node not found",
            "dependency_node_not_found",
            {"missing_node_ids": missing[:20]},
        )


def _assert_no_cycles(node_ids: set[str], edges: list[tuple[str, str]]) -> None:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    indegree: dict[str, int] = {node_id: 0 for node_id in node_ids}
    for from_id, to_id in edges:
        if from_id == to_id:
            raise AssignmentCenterError(
                400,
                "self dependency not allowed",
                "self_dependency_not_allowed",
                {"node_id": from_id},
            )
        if from_id not in adjacency or to_id not in adjacency:
            continue
        adjacency[from_id].append(to_id)
        indegree[to_id] += 1
    queue = sorted([node_id for node_id, deg in indegree.items() if deg == 0])
    visited = 0
    while queue:
        current = queue.pop(0)
        visited += 1
        for child in adjacency.get(current) or []:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    if visited != len(node_ids):
        raise AssignmentCenterError(
            400,
            "cycle dependency detected",
            "dependency_cycle_detected",
        )


def _normalize_graph_header(conn: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:
    system_limit, _updated_at = _get_global_concurrency_limit(conn)
    is_test_data = _normalize_assignment_test_flag(body.get("is_test_data"), default=False)
    review_mode = _normalize_review_mode(body.get("review_mode"))
    graph_name = _normalize_text(
        body.get("graph_name") or ASSIGNMENT_GLOBAL_GRAPH_NAME,
        field="graph_name",
        required=True,
        max_len=120,
    )
    source_workflow = _normalize_text(
        body.get("source_workflow") or ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW,
        field="source_workflow",
        required=True,
        max_len=120,
    )
    summary = _normalize_text(
        body.get("summary") or ASSIGNMENT_GLOBAL_GRAPH_SUMMARY,
        field="summary",
        required=False,
        max_len=500,
    )
    external_request_id = _normalize_text(
        body.get("external_request_id") or "",
        field="external_request_id",
        required=False,
        max_len=160,
    )
    if (not is_test_data) and source_workflow == ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW:
        graph_name = ASSIGNMENT_GLOBAL_GRAPH_NAME
        summary = ASSIGNMENT_GLOBAL_GRAPH_SUMMARY
        external_request_id = ASSIGNMENT_GLOBAL_GRAPH_REQUEST_ID
    graph_limit = _normalize_positive_int(
        body.get("global_concurrency_limit"),
        field="global_concurrency_limit",
        default=system_limit,
        minimum=1,
        maximum=64,
    )
    return {
        "graph_name": graph_name,
        "source_workflow": source_workflow,
        "summary": summary,
        "review_mode": review_mode,
        "external_request_id": external_request_id,
        "global_concurrency_limit": graph_limit,
        "is_test_data": is_test_data,
    }


def _resolve_assignment_agent(
    conn: sqlite3.Connection,
    cfg: Any,
    raw: Any,
    *,
    source_workflow: Any = "",
    allow_creating_agent: bool = False,
) -> dict[str, str]:
    requested = _normalize_text(raw, field="assigned_agent_id", required=True, max_len=120)
    token = safe_token(requested, "", 120)
    if not token:
        raise AssignmentCenterError(400, "assigned_agent_id invalid", "assigned_agent_id_invalid")
    source_text = str(source_workflow or "").strip().lower()
    row = conn.execute(
        """
        SELECT agent_id,agent_name,runtime_status
        FROM agent_registry
        WHERE agent_id=? OR agent_name=? COLLATE NOCASE
        LIMIT 1
        """,
        (token, requested),
    ).fetchone()
    if row is not None:
        runtime_status = str(row["runtime_status"] or "idle").strip().lower() or "idle"
        if runtime_status == "creating" and source_text != "training-role-creation" and not allow_creating_agent:
            raise AssignmentCenterError(
                409,
                "assigned agent is creating and only available to role creation workflow",
                "assigned_agent_creating_locked",
                {
                    "assigned_agent_id": str(row["agent_id"] or "").strip(),
                    "assigned_agent_name": str(row["agent_name"] or "").strip(),
                    "runtime_status": runtime_status,
                    "allowed_source_workflow": "training-role-creation",
                    "source_workflow": source_text,
                },
            )
        return {
            "agent_id": str(row["agent_id"] or "").strip(),
            "agent_name": str(row["agent_name"] or "").strip(),
        }
    items = []
    try:
        items = list_available_agents(cfg)
    except Exception:
        items = []
    for item in items:
        agent_name = str(item.get("agent_name") or "").strip()
        candidate_id = safe_token(agent_name, "", 120)
        if requested == agent_name or token == candidate_id:
            return {"agent_id": candidate_id, "agent_name": agent_name}
    raise AssignmentCenterError(
        400,
        "assigned_agent_id not found in training agent pool",
        "assigned_agent_not_found",
        {"assigned_agent_id": requested},
    )


def _resolve_optional_assignment_agent(
    conn: sqlite3.Connection,
    cfg: Any,
    raw: Any,
    *,
    source_workflow: Any = "",
    allow_creating_agent: bool = False,
) -> dict[str, str]:
    text = str(raw or "").strip()
    if not text:
        return {"agent_id": "", "agent_name": ""}
    return _resolve_assignment_agent(
        conn,
        cfg,
        text,
        source_workflow=source_workflow,
        allow_creating_agent=allow_creating_agent,
    )


def _normalize_dependency_lists(body: dict[str, Any]) -> tuple[list[str], list[str]]:
    upstream_raw = body.get("upstream_node_ids")
    downstream_raw = body.get("downstream_node_ids")
    if upstream_raw is None and "upstream_node_id" in body:
        upstream_raw = [body.get("upstream_node_id")]
    if downstream_raw is None and "downstream_node_id" in body:
        downstream_raw = [body.get("downstream_node_id")]
    upstream_ids = _dedupe_tokens(
        _safe_json_list(upstream_raw) if not isinstance(upstream_raw, list) else upstream_raw
    )
    downstream_ids = _dedupe_tokens(
        _safe_json_list(downstream_raw) if not isinstance(downstream_raw, list) else downstream_raw
    )
    return upstream_ids, downstream_ids


def _normalize_node_payload(
    conn: sqlite3.Connection,
    cfg: Any,
    body: dict[str, Any],
    *,
    node_id: str = "",
    source_workflow: Any = "",
) -> dict[str, Any]:
    source_text = _normalize_text(
        source_workflow or body.get("source_workflow") or "workflow-ui",
        field="source_workflow",
        required=True,
        max_len=120,
    )
    allow_creating_agent_raw = (
        body.get("allow_creating_agent")
        if "allow_creating_agent" in body
        else body.get("allowCreatingAgent")
    )
    allow_creating_agent = False
    if isinstance(allow_creating_agent_raw, bool):
        allow_creating_agent = allow_creating_agent_raw
    elif allow_creating_agent_raw is not None:
        allow_creating_agent = str(allow_creating_agent_raw).strip().lower() in {"1", "true", "yes", "on"}
    agent_meta = _resolve_assignment_agent(
        conn,
        cfg,
        body.get("assigned_agent_id") or body.get("agent_id") or body.get("agent_name"),
        source_workflow=source_text,
        allow_creating_agent=allow_creating_agent,
    )
    delivery_mode = _normalize_delivery_mode(
        body.get("delivery_mode")
        or body.get("deliveryMode")
        or body.get("artifact_delivery_mode")
        or "none"
    )
    receiver_meta = _resolve_optional_assignment_agent(
        conn,
        cfg,
        body.get("delivery_receiver_agent_id")
        or body.get("deliveryReceiverAgentId")
        or body.get("delivery_receiver_agent_name")
        or "",
        source_workflow=source_text,
        allow_creating_agent=allow_creating_agent,
    )
    if delivery_mode == "specified" and not str(receiver_meta.get("agent_id") or "").strip():
        raise AssignmentCenterError(
            400,
            "delivery_receiver_agent_id required when delivery_mode=specified",
            "delivery_receiver_agent_required",
        )
    upstream_ids, downstream_ids = _normalize_dependency_lists(body)
    node_name = _normalize_text(body.get("node_name"), field="node_name", required=True, max_len=200)
    node_goal = _normalize_text(body.get("node_goal"), field="node_goal", required=True, max_len=4000)
    expected_artifact = _normalize_text(
        body.get("expected_artifact") or "",
        field="expected_artifact",
        required=False,
        max_len=1000,
    )
    priority = normalize_assignment_priority(body.get("priority"), required=True)
    assigned_node_id = safe_token(str(body.get("node_id") or node_id or ""), "", 160) or assignment_node_id()
    return {
        "node_id": assigned_node_id,
        "source_workflow": source_text,
        "node_name": node_name,
        "source_schedule_id": _normalize_text(body.get("source_schedule_id") or "", field="source_schedule_id", required=False, max_len=160),
        "planned_trigger_at": _normalize_text(body.get("planned_trigger_at") or "", field="planned_trigger_at", required=False, max_len=64),
        "trigger_instance_id": _normalize_text(body.get("trigger_instance_id") or "", field="trigger_instance_id", required=False, max_len=160),
        "trigger_rule_summary": _normalize_text(body.get("trigger_rule_summary") or "", field="trigger_rule_summary", required=False, max_len=500),
        "assigned_agent_id": str(agent_meta["agent_id"] or "").strip(),
        "assigned_agent_name": str(agent_meta["agent_name"] or "").strip(),
        "node_goal": node_goal,
        "expected_artifact": expected_artifact,
        "delivery_mode": delivery_mode,
        "delivery_receiver_agent_id": str(receiver_meta.get("agent_id") or "").strip(),
        "delivery_receiver_agent_name": str(receiver_meta.get("agent_name") or "").strip(),
        "artifact_delivery_status": "pending",
        "artifact_delivered_at": "",
        "artifact_paths": [],
        "priority": int(priority),
        "upstream_node_ids": upstream_ids,
        "downstream_node_ids": downstream_ids,
    }


def _collect_edges_from_request(
    *,
    node_payloads: list[dict[str, Any]],
    explicit_edges: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for node in node_payloads:
        node_id = str(node.get("node_id") or "").strip()
        for upstream_id in list(node.get("upstream_node_ids") or []):
            edges.append((str(upstream_id), node_id))
        for downstream_id in list(node.get("downstream_node_ids") or []):
            edges.append((node_id, str(downstream_id)))
    for edge in explicit_edges:
        from_id = safe_token(str(edge.get("from_node_id") or edge.get("from") or ""), "", 160)
        to_id = safe_token(str(edge.get("to_node_id") or edge.get("to") or ""), "", 160)
        if not from_id or not to_id:
            continue
        edges.append((from_id, to_id))
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if edge in seen:
            continue
        seen.add(edge)
        deduped.append(edge)
    return deduped


def _insert_graph_nodes(
    conn: sqlite3.Connection,
    *,
    ticket_id: str,
    node_payloads: list[dict[str, Any]],
    created_at: str,
) -> None:
    for node in node_payloads:
        node_status = _normalize_status(node.get("status") or "pending", field="status")
        node_created_at = str(node.get("created_at") or created_at).strip() or created_at
        node_updated_at = str(node.get("updated_at") or node_created_at).strip() or node_created_at
        conn.execute(
            """
            INSERT INTO assignment_nodes (
                node_id,ticket_id,node_name,assigned_agent_id,node_goal,expected_artifact,
                delivery_mode,delivery_receiver_agent_id,artifact_delivery_status,artifact_delivered_at,
                artifact_paths_json,status,priority,completed_at,success_reason,result_ref,failure_reason,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(node["node_id"]),
                ticket_id,
                str(node["node_name"]),
                str(node["assigned_agent_id"]),
                str(node["node_goal"]),
                str(node["expected_artifact"]),
                str(node.get("delivery_mode") or "none"),
                str(node.get("delivery_receiver_agent_id") or ""),
                str(node.get("artifact_delivery_status") or "pending"),
                str(node.get("artifact_delivered_at") or ""),
                json.dumps(list(node.get("artifact_paths") or []), ensure_ascii=False),
                node_status,
                int(node["priority"]),
                str(node.get("completed_at") or ""),
                str(node.get("success_reason") or ""),
                str(node.get("result_ref") or ""),
                str(node.get("failure_reason") or ""),
                node_created_at,
                node_updated_at,
            ),
        )


def _insert_edges(
    conn: sqlite3.Connection,
    *,
    ticket_id: str,
    edges: list[tuple[str, str]],
    created_at: str,
) -> None:
    for from_id, to_id in edges:
        conn.execute(
            """
            INSERT OR IGNORE INTO assignment_edges (
                ticket_id,from_node_id,to_node_id,edge_kind,created_at
            ) VALUES (?,?,?,?,?)
            """,
            (ticket_id, from_id, to_id, "depends_on", created_at),
        )


def _plan_bridge_edges_after_delete(
    *,
    node_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    node_order = {
        str(node.get("node_id") or "").strip(): index
        for index, node in enumerate(nodes)
        if str(node.get("node_id") or "").strip()
    }
    remaining_node_ids = {
        current_id
        for current_id in node_order
        if current_id and current_id != node_id
    }
    upstream_ids = sorted(
        {
            str(edge.get("from_node_id") or "").strip()
            for edge in edges
            if str(edge.get("to_node_id") or "").strip() == node_id
            and str(edge.get("from_node_id") or "").strip() in remaining_node_ids
        },
        key=lambda item: (node_order.get(item, 10**9), item),
    )
    downstream_ids = sorted(
        {
            str(edge.get("to_node_id") or "").strip()
            for edge in edges
            if str(edge.get("from_node_id") or "").strip() == node_id
            and str(edge.get("to_node_id") or "").strip() in remaining_node_ids
        },
        key=lambda item: (node_order.get(item, 10**9), item),
    )
    base_edges = [
        (
            str(edge.get("from_node_id") or "").strip(),
            str(edge.get("to_node_id") or "").strip(),
        )
        for edge in edges
        if str(edge.get("from_node_id") or "").strip() in remaining_node_ids
        and str(edge.get("to_node_id") or "").strip() in remaining_node_ids
        and str(edge.get("from_node_id") or "").strip() != node_id
        and str(edge.get("to_node_id") or "").strip() != node_id
    ]
    existing_edges = set(base_edges)
    bridge_added: list[dict[str, str]] = []
    bridge_skipped: list[dict[str, str]] = []
    for upstream_id in upstream_ids:
        for downstream_id in downstream_ids:
            candidate = (upstream_id, downstream_id)
            if upstream_id == downstream_id:
                bridge_skipped.append(
                    {
                        "from_node_id": upstream_id,
                        "to_node_id": downstream_id,
                        "reason": "self_loop_rejected",
                    }
                )
                continue
            if candidate in existing_edges:
                bridge_skipped.append(
                    {
                        "from_node_id": upstream_id,
                        "to_node_id": downstream_id,
                        "reason": "duplicate_edge_skipped",
                    }
                )
                continue
            try:
                _assert_no_cycles(remaining_node_ids, base_edges + [candidate])
            except AssignmentCenterError:
                bridge_skipped.append(
                    {
                        "from_node_id": upstream_id,
                        "to_node_id": downstream_id,
                        "reason": "cycle_rejected",
                    }
                )
                continue
            base_edges.append(candidate)
            existing_edges.add(candidate)
            bridge_added.append(
                {
                    "from_node_id": upstream_id,
                    "to_node_id": downstream_id,
                }
            )
    return {
        "upstream_node_ids": upstream_ids,
        "downstream_node_ids": downstream_ids,
        "bridge_added": bridge_added,
        "bridge_skipped": bridge_skipped,
    }


def _current_assignment_snapshot(conn: sqlite3.Connection, ticket_id: str) -> dict[str, Any]:
    _reconcile_stale_running_nodes(conn, ticket_id=ticket_id)
    graph_row = _ensure_graph_row(conn, ticket_id)
    nodes = _load_nodes(conn, ticket_id)
    edges = _load_edges(conn, ticket_id)
    node_map_by_id = _node_map(nodes)
    upstream_map, downstream_map = _edge_maps(edges)
    system_limit, system_limit_updated_at = _get_global_concurrency_limit(conn)
    counts = _running_counts(conn, ticket_id=ticket_id)
    scheduler_payload = {
        "state": str(graph_row["scheduler_state"] or "").strip().lower(),
        "state_text": _scheduler_state_text(graph_row["scheduler_state"]),
        "running_agent_count": int(counts["running_agent_count"]),
        "system_running_agent_count": int(counts["system_running_agent_count"]),
        "graph_running_node_count": int(counts["graph_running_node_count"]),
        "system_running_node_count": int(counts["system_running_node_count"]),
        "global_concurrency_limit": int(system_limit),
        "graph_concurrency_limit": int(graph_row["global_concurrency_limit"] or 0),
        "effective_concurrency_limit": _graph_effective_limit(
            graph_limit=int(graph_row["global_concurrency_limit"] or 0),
            system_limit=system_limit,
        ),
        "pause_note": str(graph_row["pause_note"] or "").strip(),
        "settings_updated_at": system_limit_updated_at,
    }
    serialized_nodes = [
        _serialize_node(
            node,
            node_map_by_id=node_map_by_id,
            upstream_map=upstream_map,
            downstream_map=downstream_map,
        )
        for node in nodes
    ]
    is_test_data = _row_is_test_data(graph_row)
    for node in serialized_nodes:
        node["is_test_data"] = is_test_data
    return {
        "graph_row": graph_row,
        "nodes": nodes,
        "edges": edges,
        "node_map_by_id": node_map_by_id,
        "upstream_map": upstream_map,
        "downstream_map": downstream_map,
        "metrics_summary": _graph_metrics(nodes),
        "scheduler": scheduler_payload,
        "serialized_nodes": serialized_nodes,
    }


def _assignment_extract_agent_message_text(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type") or "").strip().lower()
    if event_type != "item.completed":
        return ""
    item = event.get("item")
    if not isinstance(item, dict):
        return ""
    if str(item.get("type") or "").strip().lower() != "agent_message":
        return ""
    return str(item.get("text") or "").strip()


def _assignment_extract_json_objects(text: str) -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    decoder = json.JSONDecoder()
    payloads: list[dict[str, Any]] = []
    index = 0
    while index < len(raw):
        next_open = raw.find("{", index)
        if next_open < 0:
            break
        try:
            candidate, consumed = decoder.raw_decode(raw[next_open:])
        except Exception:
            index = next_open + 1
            continue
        if isinstance(candidate, dict):
            payloads.append(candidate)
        index = next_open + max(1, int(consumed))
    return payloads


def _short_assignment_text(text: str, limit: int = 500) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _normalize_assignment_execution_result(raw_payload: dict[str, Any], *, fallback_text: str, node: dict[str, Any]) -> dict[str, Any]:
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    summary = _normalize_text(
        payload.get("result_summary") or payload.get("summary") or _short_assignment_text(fallback_text, 240),
        field="result_summary",
        required=False,
        max_len=2000,
    )
    artifact_label = _normalize_text(
        payload.get("artifact_label") or payload.get("title") or payload.get("artifact_title") or "",
        field="artifact_label",
        required=False,
        max_len=200,
    )
    artifact_markdown = _normalize_text(
        payload.get("artifact_markdown") or payload.get("result_markdown") or payload.get("markdown") or fallback_text,
        field="artifact_markdown",
        required=False,
        max_len=120000,
    )
    warnings = [
        _normalize_text(item, field="warnings", required=False, max_len=500)
        for item in list(payload.get("warnings") or [])
        if str(item or "").strip()
    ]
    artifact_files_raw = payload.get("artifact_files")
    if artifact_files_raw in (None, ""):
        artifact_files_raw = payload.get("artifact_paths")
    if artifact_files_raw in (None, ""):
        artifact_files_raw = payload.get("files")
    artifact_files: list[str] = []
    seen_artifact_files: set[str] = set()
    for item in _safe_json_list(artifact_files_raw):
        text = _normalize_text(item, field="artifact_files", required=False, max_len=1000)
        if not text:
            continue
        key = text.lower()
        if key in seen_artifact_files:
            continue
        seen_artifact_files.add(key)
        artifact_files.append(text)
    if not artifact_label:
        artifact_label = (
            str(node.get("expected_artifact") or "").strip()
            or str(node.get("node_name") or "").strip()
            or str(node.get("node_id") or "").strip()
            or "任务产物"
        )
    if not summary:
        summary = _short_assignment_text(artifact_markdown or fallback_text, 240) or "执行完成"
    return {
        "result_summary": summary,
        "artifact_label": artifact_label,
        "artifact_markdown": artifact_markdown,
        "artifact_files": artifact_files,
        "warnings": warnings,
    }


def _build_assignment_execution_prompt(
    *,
    graph_row: sqlite3.Row,
    node: dict[str, Any],
    upstream_nodes: list[dict[str, Any]],
    workspace_path: Path,
    delivery_inbox_path: Path | None = None,
) -> str:
    upstream_lines: list[str] = []
    for item in upstream_nodes:
        upstream_lines.append(
            "- "
            + str(item.get("node_name") or item.get("node_id") or "").strip()
            + f"（status={str(item.get('status') or '').strip()}, "
            + f"result_ref={str(item.get('result_ref') or '-').strip() or '-'}, "
            + f"success_reason={str(item.get('success_reason') or '-').strip() or '-'}, "
            + f"failure_reason={str(item.get('failure_reason') or '-').strip() or '-'}）"
        )
    if not upstream_lines:
        upstream_lines.append("- 无上游任务，直接按目标执行。")
    expected_artifact = str(node.get("expected_artifact") or "").strip() or "未指定"
    delivery_mode = _delivery_mode_text(node.get("delivery_mode") or "none")
    receiver = str(node.get("delivery_receiver_agent_name") or node.get("delivery_receiver_agent_id") or "-").strip() or "-"
    delivery_target = str(
        node.get("delivery_target_agent_name")
        or node.get("delivery_target_agent_id")
        or _node_delivery_target_agent_name(node)
        or receiver
        or "-"
    ).strip() or "-"
    delivery_inbox_path_text = (
        delivery_inbox_path.as_posix()
        if isinstance(delivery_inbox_path, Path)
        else str(node.get("delivery_inbox_relative_path") or _node_delivery_inbox_relative_path(node) or "-").strip()
        or "-"
    )
    delivery_info_path_text = (
        (delivery_inbox_path / ASSIGNMENT_DELIVERY_INFO_FILE_NAME).as_posix()
        if isinstance(delivery_inbox_path, Path)
        else str(node.get("delivery_info_relative_path") or _node_delivery_info_relative_path(node) or "-").strip()
        or "-"
    )
    lines = [
        "你是 workflow 任务中心的真实执行 worker。",
        "当前任务已经由调度器真实派发，必须在目标工作区内完成任务，并遵守该工作区的 AGENTS.md / 本地规则。",
        "",
        "任务上下文：",
        f"- ticket_id: {str(node.get('ticket_id') or '').strip()}",
        f"- node_id: {str(node.get('node_id') or '').strip()}",
        f"- graph_name: {str(graph_row['graph_name'] or '').strip()}",
        f"- assigned_agent_id: {str(node.get('assigned_agent_id') or '').strip()}",
        f"- assigned_agent_name: {str(node.get('assigned_agent_name') or '').strip()}",
        f"- workspace_path: {workspace_path.as_posix()}",
        f"- task_name: {str(node.get('node_name') or '').strip()}",
        f"- task_goal: {str(node.get('node_goal') or '').strip()}",
        f"- expected_artifact: {expected_artifact}",
        f"- delivery_mode: {delivery_mode}",
        f"- delivery_receiver: {receiver}",
        f"- effective_delivery_target: {delivery_target}",
        f"- delivery_inbox_path: {delivery_inbox_path_text}",
        f"- delivery_info_path: {delivery_info_path_text}",
        "",
        "上游任务结果：",
        *upstream_lines,
        "",
        "执行要求：",
        "1. 若需要修改或新增文件，只允许写入当前 workspace_path 内的内容。",
        "2. 完成后必须只输出一个 JSON 对象，不要输出 markdown fence、不要追加解释。",
        "3. 输出 JSON 结构固定为：",
        "{",
        '  "result_summary": "",',
        '  "artifact_label": "",',
        '  "artifact_markdown": "",',
        '  "artifact_files": [],',
        '  "warnings": []',
        "}",
        "4. 如果最终产物是 workspace_path 内的真实文件，artifact_label 优先填写最终文件名，artifact_files 必须返回相对 workspace_path 的文件路径列表。",
        "5. artifact_markdown 必须给出可直接交付的完整正文；若同时写了工作区文件，artifact_markdown 应与最终文件内容保持一致。",
        "6. 系统在收集 artifact_files 后会自动清理这些源文件；若某个文件必须继续保留在 workspace_path，就不要把它放进 artifact_files。",
        "7. 系统会在收集结果后把最终交付件投影到 delivery_inbox_path，并在同目录写入 DELIVERY_INFO.json 标记交付者与接收者；你自己仍然只能写 workspace_path。",
    ]
    return "\n".join(lines).strip() + "\n"


def _build_assignment_execution_command(
    *,
    provider: str,
    codex_command_path: str,
    command_template: str,
    workspace_path: Path,
) -> tuple[list[str], str]:
    provider_text = _normalize_execution_provider(provider)
    if provider_text != DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER:
        raise AssignmentCenterError(
            409,
            "execution provider not supported in phase1",
            "assignment_execution_provider_not_supported",
            {"provider": provider_text},
        )
    resolved = str(command_template or _default_assignment_command_template(provider_text)).format(
        codex_path=_normalize_codex_command_path(codex_command_path),
        workspace_path=workspace_path.as_posix(),
    )
    try:
        command = shlex.split(resolved, posix=False)
    except Exception as exc:
        raise AssignmentCenterError(
            400,
            "assignment command template invalid",
            "assignment_command_template_invalid",
            {"command_template": resolved},
        ) from exc
    command = [
        item[1:-1] if len(item) >= 2 and item[0] == item[-1] == '"' else item
        for item in command
        if str(item or "").strip()
    ]
    if not command:
        raise AssignmentCenterError(
            400,
            "assignment command template resolved empty",
            "assignment_command_template_invalid",
        )
    return command, resolved


def _register_assignment_run_process(run_id: str, process: subprocess.Popen[str]) -> None:
    with _ASSIGNMENT_ACTIVE_RUN_LOCK:
        _ASSIGNMENT_ACTIVE_RUN_PROCESSES[str(run_id or "").strip()] = process


def _terminate_assignment_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    try:
        if process.poll() is not None:
            return
    except Exception:
        return
    if str(os.name or "").lower() == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        except Exception:
            pass
    try:
        if process.poll() is None:
            process.kill()
    except Exception:
        pass


def _unregister_assignment_run_process(run_id: str) -> None:
    with _ASSIGNMENT_ACTIVE_RUN_LOCK:
        _ASSIGNMENT_ACTIVE_RUN_PROCESSES.pop(str(run_id or "").strip(), None)


def _active_assignment_run_ids() -> list[str]:
    active: list[str] = []
    stale: list[str] = []
    with _ASSIGNMENT_ACTIVE_RUN_LOCK:
        for run_id, process in list(_ASSIGNMENT_ACTIVE_RUN_PROCESSES.items()):
            if process is None or process.poll() is not None:
                stale.append(str(run_id or "").strip())
                continue
            active.append(str(run_id or "").strip())
        for run_id in stale:
            _ASSIGNMENT_ACTIVE_RUN_PROCESSES.pop(run_id, None)
    return [run_id for run_id in active if run_id]


def _kill_assignment_run_process(run_id: str) -> None:
    process = None
    with _ASSIGNMENT_ACTIVE_RUN_LOCK:
        process = _ASSIGNMENT_ACTIVE_RUN_PROCESSES.get(str(run_id or "").strip())
    _terminate_assignment_process(process)
