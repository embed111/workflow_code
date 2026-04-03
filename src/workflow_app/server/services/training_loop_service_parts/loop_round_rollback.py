

def rollback_training_queue_round_increment(
    root: Path,
    *,
    queue_task_id_text: str,
    operator: str,
    reason: str = "",
) -> dict[str, object]:
    qid = safe_token(str(queue_task_id_text or ""), "", 160)
    if not qid:
        raise TrainingCenterError(400, "queue_task_id required", "queue_task_id_required")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)
    reason_text = str(reason or "").strip()

    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        read_model = _sync_training_loop_read_model(
            conn,
            queue_task_id=qid,
            now_text=iso_ts(now_local()),
        )
        current_node_id = str(read_model["current_node_id"] or "").strip()
        current_node = read_model["nodes_by_id"].get(current_node_id) if isinstance(read_model.get("nodes_by_id"), dict) else None
        if not current_node or str(current_node.get("queue_task_id") or current_node.get("node_id") or "").strip() != qid:
            raise TrainingCenterError(
                409,
                "loop current node changed",
                "loop_current_task_changed",
                {"queue_task_id": qid, "loop_id": str(read_model["loop_id"] or ""), "current_node_id": current_node_id},
            )
        if str(current_node.get("node_type") or "").strip().lower() != "round":
            raise TrainingCenterError(
                409,
                "current node is not round",
                "loop_current_node_not_round",
                {"queue_task_id": qid, "current_node_id": current_node_id},
            )
        available_actions = list(current_node.get("available_actions") or [])
        if "rollback-round-increment" not in available_actions:
            raise TrainingCenterError(
                409,
                "rollback not available",
                "rollback_round_increment_not_available",
                {
                    "queue_task_id": qid,
                    "available_actions": available_actions,
                    "decision": str(current_node.get("decision") or "").strip(),
                    "decision_code": str(current_node.get("decision_code") or "").strip(),
                },
            )

        loop_id = str(read_model["loop_id"] or "").strip()
        graph = _parse_loop_graph(read_model["graph"])
        raw_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        rollback_node_id = f"rb-{qid}"
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue
            if str(raw_edge.get("kind") or "main").strip().lower() != "rollback":
                continue
            if str(raw_edge.get("from") or raw_edge.get("from_id") or "").strip() != qid:
                continue
            existing_rb = str(raw_edge.get("to") or raw_edge.get("to_id") or "").strip()
            if existing_rb:
                raise TrainingCenterError(
                    409,
                    "rollback already exists",
                    "loop_rollback_exists",
                    {"queue_task_id": qid, "loop_id": loop_id, "rollback_node_id": existing_rb},
                )

        now_text = iso_ts(now_local())
        nodes = list(graph.get("nodes") or [])
        if not any(str(node.get("node_id") or "").strip() == rollback_node_id for node in nodes if isinstance(node, dict)):
            metrics_payload = current_node.get("metrics") if isinstance(current_node.get("metrics"), dict) else {
                "avg_score": None,
                "threshold": None,
                "previous_avg_score": None,
                "run_results": [],
            }
            nodes.append(
                {
                    "node_id": rollback_node_id,
                    "title": "撤销本轮新增",
                    "round_index": int(current_node.get("round_index") or 0),
                    "round_label": f"R{int(current_node.get('round_index') or 0)}",
                    "node_type": "rollback",
                    "decision": "已撤销本轮新增",
                    "decision_code": "round_increment_rolled_back",
                    "next_action": "当前轮已回退",
                    "next_action_code": "",
                    "impact": reason_text or f"按当前轮判定回退 R{int(current_node.get('round_index') or 0)} 的本轮新增",
                    "metrics": metrics_payload,
                    "metrics_available": bool(current_node.get("metrics_available")),
                    "metrics_unavailable_reason": str(current_node.get("metrics_unavailable_reason") or "").strip(),
                    "queue_task_id": qid,
                    "plan_id": str(current_node.get("plan_id") or "").strip(),
                    "status": "active",
                    "available_actions": [],
                    "run_ids": list(current_node.get("run_ids") or []),
                    "execution_engine": str(current_node.get("execution_engine") or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
                    "created_at": now_text,
                    "updated_at": now_text,
                }
            )
        edges = list(graph.get("edges") or [])
        edges.append({"from": qid, "to": rollback_node_id, "kind": "rollback"})
        graph["nodes"] = nodes
        graph["edges"] = edges
        graph["current_node_id"] = rollback_node_id

        conn.execute(
            """
            UPDATE training_loop_state
            SET graph_json=?,
                current_node_id=?,
                metrics_available=?,
                metrics_unavailable_reason=?,
                updated_at=?
            WHERE loop_id=?
            """,
            (
                json.dumps(graph, ensure_ascii=False),
                rollback_node_id,
                1 if bool(current_node.get("metrics_available")) else 0,
                str(current_node.get("metrics_unavailable_reason") or "").strip(),
                now_text,
                loop_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    audit_id = append_training_center_audit(
        root,
        action="rollback-round-increment",
        operator=operator_text,
        target_id=loop_id,
        detail={
            "queue_task_id": qid,
            "loop_id": loop_id,
            "rollback_node_id": rollback_node_id,
            "reason": reason_text,
            "execution_engine": EXECUTION_ENGINE,
        },
    )
    return {
        "ok": True,
        "audit_id": audit_id,
        "loop_id": loop_id,
        "current_node_id": rollback_node_id,
        "rollback_node_id": rollback_node_id,
        "execution_engine": EXECUTION_ENGINE,
    }
