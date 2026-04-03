

def _sync_training_loop_read_model(
    conn: sqlite3.Connection,
    *,
    queue_task_id: str,
    now_text: str,
) -> dict[str, Any]:
    seed = _resolve_training_queue_row(conn, queue_task_id)
    loop_id = _ensure_plan_loop_id(conn, seed)
    loop_row = _ensure_loop_state_row(conn, loop_id=loop_id, seed_row=seed, now_text=now_text)
    graph = _parse_loop_graph(loop_row["graph_json"])
    raw_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    raw_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    existing_current_node_id = str(loop_row["current_node_id"] or graph.get("current_node_id") or "").strip()

    graph_nodes_by_id: dict[str, dict[str, Any]] = {}
    rollback_nodes: list[dict[str, Any]] = []
    rollback_targets: set[str] = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_id = str(raw_node.get("node_id") or "").strip()
        if not node_id:
            continue
        graph_nodes_by_id[node_id] = dict(raw_node)
        if str(raw_node.get("node_type") or "").strip().lower() == "rollback":
            rollback_nodes.append(dict(raw_node))
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        if str(raw_edge.get("kind") or "main").strip().lower() != "rollback":
            continue
        from_id = str(raw_edge.get("from") or raw_edge.get("from_id") or "").strip()
        if from_id:
            rollback_targets.add(from_id)

    queue_rows = _load_loop_queue_rows(conn, loop_id)
    queue_ids = [str(row["queue_task_id"] or "").strip() for row in queue_rows if str(row["queue_task_id"] or "").strip()]
    eval_run_map = _load_loop_eval_runs(conn, queue_ids)
    queue_audit_map = _load_queue_audits(conn, queue_ids)
    loop_audits = _load_loop_action_audits(conn, loop_id)
    queue_order_map = {
        str(row["queue_task_id"] or "").strip(): index
        for index, row in enumerate(queue_rows)
        if str(row["queue_task_id"] or "").strip()
    }
    queue_rows = sorted(
        queue_rows,
        key=lambda row: (
            _round_index_for_queue(
                order_index=queue_order_map.get(str(row["queue_task_id"] or "").strip(), 0),
                graph_node=graph_nodes_by_id.get(str(row["queue_task_id"] or "").strip(), {}),
                eval_rows=eval_run_map.get(str(row["queue_task_id"] or "").strip(), []),
            ),
            str(row["enqueued_at"] or ""),
            str(row["queue_task_id"] or ""),
        ),
    )

    base_node = _loop_node_base(str(loop_row["created_at"] or now_text).strip() or now_text)
    nodes: list[dict[str, Any]] = [base_node]
    round_records: list[dict[str, Any]] = []
    history_records: list[dict[str, Any]] = []
    previous_avg_score: float | None = None
    previous_tasks: list[str] = []

    for order_index, row in enumerate(queue_rows):
        qid = str(row["queue_task_id"] or "").strip()
        graph_node = graph_nodes_by_id.get(qid, {})
        eval_rows = eval_run_map.get(qid, [])
        round_index = _round_index_for_queue(
            order_index=order_index,
            graph_node=graph_node,
            eval_rows=eval_rows,
        )
        action_audits = _related_action_audits(
            qid,
            queue_audit_map=queue_audit_map,
            loop_audits=loop_audits,
        )
        rolled_back = qid in rollback_targets
        evaluation = summarize_training_eval_runs(
            priority=row["priority"] or row["plan_priority"],
            run_results=eval_rows,
            previous_avg_score=previous_avg_score,
        )
        if evaluation["metrics_available"] and evaluation["avg_score"] is not None:
            previous_avg_score = float(evaluation["avg_score"])

        workset_changes = _build_workset_changes(
            row,
            round_index=round_index,
            previous_tasks=previous_tasks,
            action_audits=action_audits,
            rolled_back=rolled_back,
        )
        previous_tasks = _parse_training_tasks(row["training_tasks_json"])

        decision = str(evaluation["decision"] or "").strip()
        decision_code = str(evaluation["decision_code"] or "").strip()
        next_action = str(evaluation["next_action"] or "").strip()
        next_action_code = str(evaluation["next_action_code"] or "").strip()
        if not decision:
            queue_status = str(row["status"] or "").strip().lower()
            if not eval_rows:
                decision = "等待执行三轮评测"
                decision_code = "awaiting_evaluation"
                next_action = "执行三轮评测"
                next_action_code = "execute"
            elif queue_status == "running":
                decision = "三轮评测执行中"
                decision_code = "evaluation_running"
                next_action = "等待三轮评测完成"
                next_action_code = ""
            else:
                decision = "三轮评测未完整回写"
                decision_code = "evaluation_partial"
                next_action = "等待三轮评测完成"
                next_action_code = ""

        metrics_payload = {
            "avg_score": evaluation["avg_score"],
            "threshold": evaluation["threshold"],
            "previous_avg_score": evaluation["previous_avg_score"],
            "run_results": evaluation["run_results"],
            "decision_code": decision_code,
            "next_action_code": next_action_code,
        }
        queue_status_value = "rolled_back" if rolled_back else str(row["status"] or "").strip().lower() or "queued"
        title = str(graph_node.get("title") or "").strip() or (
            f"R{round_index}"
            + (
                " 已回退"
                if queue_status_value == "rolled_back"
                else " 当前"
                if queue_status_value not in {"done", "removed"}
                else " 已完成"
            )
        )
        impact = str(graph_node.get("impact") or "").strip() or str(workset_changes["delta_summary"] or "").strip()
        updated_at = str(
            row["latest_run_updated_at"] or row["finished_at"] or row["started_at"] or row["enqueued_at"] or now_text
        ).strip() or now_text
        run_ids = [
            str(item.get("eval_run_id") or "").strip()
            for item in evaluation["run_results"]
            if str(item.get("eval_run_id") or "").strip()
        ]

        node = {
            "node_id": qid,
            "title": title,
            "round_index": round_index,
            "round_label": f"R{round_index}",
            "node_type": "round",
            "decision": decision,
            "decision_code": decision_code,
            "next_action": next_action,
            "next_action_code": next_action_code,
            "impact": impact,
            "metrics": metrics_payload,
            "metrics_available": bool(evaluation["metrics_available"]),
            "metrics_unavailable_reason": str(evaluation["metrics_unavailable_reason"] or "").strip(),
            "queue_task_id": qid,
            "plan_id": str(row["plan_id"] or "").strip(),
            "status": queue_status_value,
            "available_actions": list(evaluation["available_actions"] or []),
            "run_ids": run_ids,
            "execution_engine": str(row["execution_engine"] or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
            "created_at": str(row["enqueued_at"] or "").strip() or now_text,
            "updated_at": updated_at,
        }
        nodes.append(node)

        audit_refs = [
            {
                "audit_id": str(item.get("audit_id") or "").strip(),
                "action": str(item.get("action") or "").strip(),
                "created_at": str(item.get("created_at") or "").strip(),
            }
            for item in action_audits
            if str(item.get("audit_id") or "").strip()
        ]
        history_record = {
            "round_index": round_index,
            "queue_task_id": qid,
            "node_id": qid,
            "title": title,
            "decision": decision,
            "decision_code": decision_code,
            "avg_score": evaluation["avg_score"],
            "threshold": evaluation["threshold"],
            "previous_avg_score": evaluation["previous_avg_score"],
            "next_action": next_action,
            "next_action_code": next_action_code,
            "workset_delta_summary": workset_changes["delta_summary"],
            "rollback_applied": rolled_back,
            "audit_refs": audit_refs,
            "created_at": str(row["enqueued_at"] or "").strip() or now_text,
            "updated_at": updated_at,
            "execution_engine": str(row["execution_engine"] or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
        }
        history_records.append(history_record)

        round_records.append(
            {
                "queue_task_id": qid,
                "plan_id": str(row["plan_id"] or "").strip(),
                "round_index": round_index,
                "round_label": f"R{round_index}",
                "title": title,
                "status": str(row["status"] or "").strip().lower() or "queued",
                "execution_engine": str(row["execution_engine"] or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
                "run_results": evaluation["run_results"],
                "avg_score": evaluation["avg_score"],
                "threshold": evaluation["threshold"],
                "previous_avg_score": evaluation["previous_avg_score"],
                "decision": decision,
                "decision_code": decision_code,
                "next_action": next_action,
                "next_action_code": next_action_code,
                "available_actions": list(evaluation["available_actions"] or []),
                "metrics_available": bool(evaluation["metrics_available"]),
                "metrics_unavailable_reason": str(evaluation["metrics_unavailable_reason"] or "").strip(),
                "workset_changes": workset_changes,
                "history_record": history_record,
                "latest_run_id": str(row["latest_run_id"] or "").strip(),
                "latest_run_status": str(row["latest_run_status"] or "").strip(),
                "latest_run_ref": str(row["latest_run_ref"] or "").strip(),
                "latest_result_summary": str(row["latest_result_summary"] or "").strip(),
                "updated_at": updated_at,
                "created_at": str(row["enqueued_at"] or "").strip() or now_text,
            }
        )

    round_record_by_queue = {
        str(item["queue_task_id"] or "").strip(): item
        for item in round_records
        if str(item["queue_task_id"] or "").strip()
    }
    for raw_node in rollback_nodes:
        parent_qid = str(raw_node.get("queue_task_id") or "").strip()
        round_record = round_record_by_queue.get(parent_qid)
        round_value = int(raw_node.get("round_index") or (round_record.get("round_index") if round_record else 0) or 0)
        nodes.append(
            {
                "node_id": str(raw_node.get("node_id") or "").strip(),
                "title": str(raw_node.get("title") or "撤销本轮新增").strip() or "撤销本轮新增",
                "round_index": round_value,
                "round_label": f"R{round_value}",
                "node_type": "rollback",
                "decision": "已撤销本轮新增",
                "decision_code": "round_increment_rolled_back",
                "next_action": "当前轮已回退",
                "next_action_code": "",
                "impact": str(raw_node.get("impact") or (round_record.get("workset_changes", {}).get("delta_summary") if round_record else "") or "").strip(),
                "metrics": {
                    "avg_score": round_record.get("avg_score") if round_record else None,
                    "threshold": round_record.get("threshold") if round_record else None,
                    "previous_avg_score": round_record.get("previous_avg_score") if round_record else None,
                    "run_results": list(round_record.get("run_results") or []) if round_record else [],
                    "decision_code": str(round_record.get("decision_code") or "").strip() if round_record else "",
                    "next_action_code": str(round_record.get("next_action_code") or "").strip() if round_record else "",
                },
                "metrics_available": bool(round_record.get("metrics_available")) if round_record else False,
                "metrics_unavailable_reason": str(round_record.get("metrics_unavailable_reason") or "").strip() if round_record else "rollback_without_round_metrics",
                "queue_task_id": parent_qid,
                "plan_id": str(raw_node.get("plan_id") or (round_record.get("plan_id") if round_record else "") or "").strip(),
                "status": "active",
                "available_actions": [],
                "run_ids": [
                    str(item.get("eval_run_id") or "").strip()
                    for item in (round_record.get("run_results") or [] if round_record else [])
                    if str(item.get("eval_run_id") or "").strip()
                ],
                "execution_engine": str(
                    raw_node.get("execution_engine")
                    or (round_record.get("execution_engine") if round_record else EXECUTION_ENGINE)
                    or EXECUTION_ENGINE
                ).strip()
                or EXECUTION_ENGINE,
                "created_at": str(raw_node.get("created_at") or now_text).strip() or now_text,
                "updated_at": str(raw_node.get("updated_at") or now_text).strip() or now_text,
            }
        )

    nodes_by_id = {
        str(node.get("node_id") or "").strip(): node
        for node in nodes
        if isinstance(node, dict) and str(node.get("node_id") or "").strip()
    }
    valid_ids = set(nodes_by_id.keys())
    edges: list[dict[str, Any]] = []
    edge_seen: set[tuple[str, str, str]] = set()
    if round_records:
        _append_edge(
            edges,
            edge_seen,
            from_id="baseline",
            to_id=str(round_records[0]["queue_task_id"] or "").strip(),
            kind="main",
            valid_ids=valid_ids,
        )
    for idx in range(1, len(round_records)):
        _append_edge(
            edges,
            edge_seen,
            from_id=str(round_records[idx - 1]["queue_task_id"] or "").strip(),
            to_id=str(round_records[idx]["queue_task_id"] or "").strip(),
            kind="main",
            valid_ids=valid_ids,
        )
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        _append_edge(
            edges,
            edge_seen,
            from_id=str(raw_edge.get("from") or raw_edge.get("from_id") or "").strip(),
            to_id=str(raw_edge.get("to") or raw_edge.get("to_id") or "").strip(),
            kind=str(raw_edge.get("kind") or "main").strip().lower() or "main",
            valid_ids=valid_ids,
        )

    current_node_id = existing_current_node_id if existing_current_node_id in valid_ids else ""
    if not current_node_id:
        current_node_id = str(round_records[-1]["queue_task_id"] or "").strip() if round_records else "baseline"
    current_node = nodes_by_id.get(current_node_id) or base_node

    queue_row_map = {
        str(row["queue_task_id"] or "").strip(): row
        for row in queue_rows
        if str(row["queue_task_id"] or "").strip()
    }
    selected_round = round_record_by_queue.get(queue_task_id)
    selected_row = queue_row_map.get(queue_task_id, seed)
    selected_workset = dict(selected_round.get("workset_changes") or {}) if isinstance(selected_round, dict) else {
        "queue_task_id": queue_task_id,
        "round_index": 0,
        "delta_summary": "当前没有可用工作集摘要",
        "current_items": _parse_training_tasks(selected_row["training_tasks_json"]),
        "items": [],
        "added_items": [],
        "carried_items": [],
        "removed_items": [],
        "rollback_applied": False,
        "execution_engine": str(selected_row["execution_engine"] or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
        "updated_at": now_text,
    }
    overview_decision = str(selected_round.get("decision") or "").strip() if isinstance(selected_round, dict) else "等待执行三轮评测"
    overview_decision_code = str(selected_round.get("decision_code") or "").strip() if isinstance(selected_round, dict) else "awaiting_evaluation"
    overview_next_action = str(selected_round.get("next_action") or "").strip() if isinstance(selected_round, dict) else "执行三轮评测"
    overview_next_action_code = str(selected_round.get("next_action_code") or "").strip() if isinstance(selected_round, dict) else "execute"
    overview_available_actions = list(selected_round.get("available_actions") or []) if isinstance(selected_round, dict) else []
    if (
        selected_workset.get("rollback_applied")
        and str(current_node.get("node_type") or "").strip().lower() == "rollback"
        and str(current_node.get("queue_task_id") or "").strip() == queue_task_id
    ):
        overview_decision = "本轮已回退"
        overview_decision_code = "round_increment_rolled_back"
        overview_next_action = "当前轮已回退"
        overview_next_action_code = ""
        overview_available_actions = []
    current_overview = {
        "queue_task_id": queue_task_id,
        "plan_id": str(selected_row["plan_id"] or "").strip(),
        "loop_id": loop_id,
        "current_node_id": current_node_id,
        "selected_node_id": queue_task_id,
        "target_agent_id": str(selected_row["target_agent_id"] or "").strip(),
        "agent_name": str(selected_row["agent_name"] or selected_row["target_agent_id"] or "").strip(),
        "capability_goal": str(selected_row["capability_goal"] or "").strip(),
        "acceptance_criteria": str(selected_row["acceptance_criteria"] or "").strip(),
        "priority": str(selected_row["priority"] or selected_row["plan_priority"] or "").strip() or "P1",
        "queue_status": str(selected_row["status"] or "").strip().lower() or "queued",
        "execution_engine": str(selected_row["execution_engine"] or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
        "round_index": int(selected_round.get("round_index") or 0) if isinstance(selected_round, dict) else 0,
        "avg_score": selected_round.get("avg_score") if isinstance(selected_round, dict) else None,
        "threshold": selected_round.get("threshold") if isinstance(selected_round, dict) else training_threshold_for_priority(selected_row["priority"]),
        "previous_avg_score": selected_round.get("previous_avg_score") if isinstance(selected_round, dict) else None,
        "decision": overview_decision,
        "decision_code": overview_decision_code,
        "next_action": overview_next_action,
        "next_action_code": overview_next_action_code,
        "metrics_available": bool(selected_round.get("metrics_available")) if isinstance(selected_round, dict) else False,
        "metrics_unavailable_reason": str(selected_round.get("metrics_unavailable_reason") or "").strip() if isinstance(selected_round, dict) else "evaluation_not_started",
        "available_actions": overview_available_actions,
        "latest_run_id": str(selected_round.get("latest_run_id") or "").strip() if isinstance(selected_round, dict) else str(selected_row["latest_run_id"] or "").strip(),
        "latest_run_status": str(selected_round.get("latest_run_status") or "").strip() if isinstance(selected_round, dict) else str(selected_row["latest_run_status"] or "").strip(),
        "latest_run_ref": str(selected_round.get("latest_run_ref") or "").strip() if isinstance(selected_round, dict) else str(selected_row["latest_run_ref"] or "").strip(),
        "latest_result_summary": str(selected_round.get("latest_result_summary") or "").strip() if isinstance(selected_round, dict) else str(selected_row["latest_result_summary"] or "").strip(),
        "updated_at": str(selected_round.get("updated_at") or now_text).strip() if isinstance(selected_round, dict) else now_text,
    }

    synced_graph = {
        "version": 2,
        "loop_id": loop_id,
        "nodes": nodes,
        "edges": edges,
        "current_node_id": current_node_id,
    }
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
            json.dumps(synced_graph, ensure_ascii=False),
            current_node_id,
            1 if bool(current_node.get("metrics_available")) else 0,
            str(current_node.get("metrics_unavailable_reason") or "").strip(),
            now_text,
            loop_id,
        ),
    )

    return {
        "loop_id": loop_id,
        "is_test_data": bool(int(loop_row["is_test_data"] or 0)),
        "queue_task_id": queue_task_id,
        "nodes": nodes,
        "edges": edges,
        "nodes_by_id": nodes_by_id,
        "current_node_id": current_node_id,
        "current_node": current_node,
        "queue_rows": queue_rows,
        "queue_row_map": queue_row_map,
        "round_records": round_records,
        "round_record_by_queue": round_record_by_queue,
        "history_records": history_records,
        "current_overview": current_overview,
        "workset_changes": selected_workset,
        "evaluations": round_records,
        "metrics_available": bool(current_node.get("metrics_available")),
        "metrics_unavailable_reason": str(current_node.get("metrics_unavailable_reason") or "").strip(),
        "graph": synced_graph,
    }


def _training_loop_split_text_items(raw: object, *, limit: int = 8) -> list[str]:
    items: list[str] = []
    if isinstance(raw, list):
        source_items = raw
    else:
        source_items = [str(raw or "")]
    for source in source_items:
        text = str(source or "").replace("\r", "\n")
        if not text.strip():
            continue
        normalized = text
        for mark in ("；", ";", "|", "，", ","):
            normalized = normalized.replace(mark, "\n")
        for part in normalized.split("\n"):
            item = str(part or "").strip(" -•\t")
            if not item or item in items:
                continue
            items.append(item)
            if len(items) >= max(1, int(limit)):
                return items
    return items


def _training_loop_agent_baseline(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
) -> dict[str, Any]:
    aid = str(agent_id or "").strip()
    if not aid:
        return {}
    row = conn.execute(
        """
        SELECT
            agent_id,agent_name,current_version,latest_release_version,bound_release_version,
            core_capabilities,capability_summary,knowledge_scope,applicable_scenarios,version_notes,updated_at
        FROM agent_registry
        WHERE agent_id=?
        LIMIT 1
        """,
        (aid,),
    ).fetchone()
    if row is None:
        return {}
    key_capabilities = _training_loop_split_text_items(
        row["core_capabilities"] or row["capability_summary"] or row["knowledge_scope"] or "",
        limit=8,
    )
    return {
        "agent_id": aid,
        "agent_name": str(row["agent_name"] or aid).strip() or aid,
        "current_version": str(row["current_version"] or "").strip(),
        "latest_release_version": str(row["latest_release_version"] or "").strip(),
        "bound_release_version": str(row["bound_release_version"] or "").strip(),
        "capability_summary": str(row["capability_summary"] or "").strip(),
        "knowledge_scope": str(row["knowledge_scope"] or "").strip(),
        "applicable_scenarios": _training_loop_split_text_items(row["applicable_scenarios"] or "", limit=6),
        "version_notes": str(row["version_notes"] or "").strip(),
        "history_key_capabilities": key_capabilities,
        "updated_at": str(row["updated_at"] or "").strip(),
    }


def _training_loop_gate_status_chip(status: str) -> str:
    key = str(status or "").strip().lower()
    if key in {"pass", "passed", "safe", "ready"}:
        return "pass"
    if key in {"blocked", "risk", "regressed", "fail", "failed"}:
        return "blocked"
    return "pending"


def _training_loop_preview_payload(
    round_record: dict[str, Any],
    *,
    capability_name: str,
    fallback_summary: str,
    regression_summary: str,
) -> dict[str, Any]:
    run_results = round_record.get("run_results") if isinstance(round_record, dict) else []
    if not isinstance(run_results, list):
        run_results = []
    preferred_run = None
    for item in reversed(run_results):
        if not isinstance(item, dict):
            continue
        if str(item.get("summary") or "").strip() or str(item.get("evidence_ref") or "").strip():
            preferred_run = item
            break
    preview_summary = (
        str((preferred_run or {}).get("summary") or "").strip()
        or str(round_record.get("latest_result_summary") or "").strip()
        or str(fallback_summary or "").strip()
        or str(regression_summary or "").strip()
        or "当前能力暂无额外展示证据，先使用本轮结果摘要占位。"
    )
    return {
        "title": f"{capability_name} 展示效果",
        "summary": preview_summary,
        "source_kind": (
            "evaluation_run"
            if preferred_run
            else "result_summary"
            if str(round_record.get("latest_result_summary") or "").strip()
            else "workset_summary"
        ),
        "evidence_ref": str((preferred_run or {}).get("evidence_ref") or "").strip(),
        "run_label": str((preferred_run or {}).get("run_label") or "").strip(),
        "updated_at": str(
            (preferred_run or {}).get("finished_at")
            or (preferred_run or {}).get("started_at")
            or round_record.get("updated_at")
            or ""
        ).strip(),
    }


def _build_training_loop_capabilities(
    read_model: dict[str, Any],
    *,
    queue_task_id: str,
    agent_baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    overview = dict(read_model.get("current_overview") or {}) if isinstance(read_model, dict) else {}
    workset = dict(read_model.get("workset_changes") or {}) if isinstance(read_model, dict) else {}
    round_record_by_queue = read_model.get("round_record_by_queue") if isinstance(read_model, dict) else {}
    if not isinstance(round_record_by_queue, dict):
        round_record_by_queue = {}
    selected_round = dict(round_record_by_queue.get(queue_task_id) or {})

    labels = _training_loop_split_text_items(workset.get("current_items") or [], limit=12)
    if not labels:
        labels = _training_loop_split_text_items(workset.get("added_items") or [], limit=12)
    if not labels:
        labels = _training_loop_split_text_items(overview.get("capability_goal") or "", limit=6)
    if not labels:
        labels = ["当前轮能力目标"]

    avg_score = _safe_float(selected_round.get("avg_score") if isinstance(selected_round, dict) else None)
    target_score = _safe_float(overview.get("threshold"))
    baseline_score = _safe_float(overview.get("previous_avg_score"))
    metrics_available = bool(overview.get("metrics_available"))
    decision_code = str(overview.get("decision_code") or "").strip().lower()
    regression_blocked = decision_code == "degraded_vs_previous" or (
        metrics_available and baseline_score is not None and avg_score is not None and avg_score < baseline_score
    )
    regression_summary = (
        "历史能力较上一轮下降，自动发布保持阻塞。"
        if regression_blocked
        else "历史能力未出现明显退化。"
        if metrics_available
        else "历史能力回归尚未完成。"
    )
    impact_scope = str(
        overview.get("capability_goal")
        or workset.get("delta_summary")
        or selected_round.get("decision")
        or ""
    ).strip()
    fallback_summary = str(
        selected_round.get("latest_result_summary")
        or selected_round.get("decision")
        or workset.get("delta_summary")
        or overview.get("acceptance_criteria")
        or ""
    ).strip()
    risk_index = 0
    if isinstance(workset.get("items"), list):
        for idx, item in enumerate(workset.get("items") or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("state") or "").strip().lower() == "added":
                risk_index = idx
                break

    capabilities: list[dict[str, Any]] = []
    for idx, label in enumerate(labels):
        capability_name = str(label or "").strip() or f"能力 {idx + 1}"
        preview_evidence = _training_loop_preview_payload(
            selected_round,
            capability_name=capability_name,
            fallback_summary=fallback_summary,
            regression_summary=regression_summary,
        )
        delta_score = None
        if avg_score is not None:
            compare_base = baseline_score if baseline_score is not None else target_score
            if compare_base is not None:
                delta_score = round(float(avg_score) - float(compare_base), 2)
        gate_b_status = (
            "pass"
            if metrics_available and avg_score is not None and target_score is not None and avg_score >= target_score
            else "blocked"
            if metrics_available
            else "pending"
        )
        gate_c_status = "blocked" if regression_blocked and idx == risk_index else "pass" if metrics_available else "pending"
        current_status = (
            "有风险"
            if gate_c_status == "blocked"
            else "已达标"
            if gate_b_status == "pass"
            else "待补强"
            if gate_b_status == "blocked"
            else "待评测"
        )
        delta_conclusion = (
            "历史能力下降，需回补后再发布"
            if gate_c_status == "blocked"
            else "已达到目标阈值"
            if gate_b_status == "pass"
            else "距离目标阈值仍有缺口"
            if gate_b_status == "blocked"
            else "等待三轮评测完成"
        )
        historical_result = {
            "status": "regressed" if gate_c_status == "blocked" else "not_affected" if metrics_available else "pending",
            "summary": (
                "该能力项触发历史能力退化，自动发布保持阻塞。"
                if gate_c_status == "blocked"
                else "未影响历史能力，可继续沿主线推进。"
                if metrics_available
                else "历史能力回归尚未完成。"
            ),
            "blocking": bool(gate_c_status == "blocked"),
            "impact_items": (
                [capability_name]
                if gate_c_status == "blocked"
                else []
            ),
        }
        capabilities.append(
            {
                "capability_id": f"{queue_task_id}:capability:{idx + 1}",
                "capability_name": capability_name,
                "capability_goal": str(overview.get("capability_goal") or capability_name).strip() or capability_name,
                "current_status": current_status,
                "preview_evidence": preview_evidence,
                "score_current": avg_score,
                "score_target": target_score,
                "score_baseline": baseline_score,
                "score_delta": delta_score,
                "score_conclusion": delta_conclusion,
                "gate_status": {
                    "overall": _training_loop_gate_status_chip("blocked" if gate_c_status == "blocked" else gate_b_status),
                    "gate_b": {
                        "status": gate_b_status,
                        "label": "Gate-B",
                        "reason": (
                            "当前能力得分已达到目标阈值。"
                            if gate_b_status == "pass"
                            else "当前能力得分仍未达到目标阈值。"
                            if gate_b_status == "blocked"
                            else "等待三轮评测完成后再判定。"
                        ),
                    },
                    "gate_c": {
                        "status": gate_c_status,
                        "label": "Gate-C",
                        "reason": (
                            "该能力项导致历史能力下降，自动发布保持阻塞。"
                            if gate_c_status == "blocked"
                            else "未影响历史能力。"
                            if gate_c_status == "pass"
                            else "等待历史能力回归结果。"
                        ),
                    },
                    "auto_publish_blocked": bool(gate_c_status == "blocked" or gate_b_status != "pass"),
                },
                "historical_regression_result": historical_result,
                "impact_scope": impact_scope or capability_name,
                "baseline_reference_version": str(
                    agent_baseline.get("bound_release_version")
                    or agent_baseline.get("latest_release_version")
                    or agent_baseline.get("current_version")
                    or ""
                ).strip(),
            }
        )
    return capabilities


def _build_training_loop_tasks_evolution(
    read_model: dict[str, Any],
    *,
    queue_task_id: str,
    capabilities: list[dict[str, Any]],
) -> dict[str, Any]:
    overview = dict(read_model.get("current_overview") or {}) if isinstance(read_model, dict) else {}
    round_records = list(read_model.get("round_records") or []) if isinstance(read_model, dict) else []
    blockers: list[dict[str, Any]] = []
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        gate_status = capability.get("gate_status") if isinstance(capability.get("gate_status"), dict) else {}
        gate_b = gate_status.get("gate_b") if isinstance(gate_status, dict) else {}
        gate_c = gate_status.get("gate_c") if isinstance(gate_status, dict) else {}
        if str((gate_c or {}).get("status") or "").strip().lower() == "blocked":
            blockers.append(
                {
                    "capability_id": str(capability.get("capability_id") or "").strip(),
                    "capability_name": str(capability.get("capability_name") or "").strip(),
                    "gate": "Gate-C",
                    "reason": str((gate_c or {}).get("reason") or "").strip(),
                }
            )
        elif str((gate_b or {}).get("status") or "").strip().lower() == "blocked":
            blockers.append(
                {
                    "capability_id": str(capability.get("capability_id") or "").strip(),
                    "capability_name": str(capability.get("capability_name") or "").strip(),
                    "gate": "Gate-B",
                    "reason": str((gate_b or {}).get("reason") or "").strip(),
                }
            )
    auto_publish_ready = not blockers and bool(overview.get("metrics_available"))
    return {
        "default_tab": "tasks",
        "current_stage": (
            "能力回补"
            if any(str(item.get("gate") or "").strip() == "Gate-C" for item in blockers)
            else "结果回看与调向"
            if blockers
            else "等待发布评审"
            if auto_publish_ready
            else "执行三轮评测"
        ),
        "blockers": blockers,
        "pending_nodes": [
            {
                "queue_task_id": str(item.get("queue_task_id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "decision": str(item.get("decision") or "").strip(),
                "current": str(item.get("queue_task_id") or "").strip() == queue_task_id,
            }
            for item in round_records
            if isinstance(item, dict)
        ],
        "auto_publish": {
            "status": "ready" if auto_publish_ready else "blocked" if blockers else "pending",
            "reason": (
                "Gate-B / Gate-C 均已通过，可以进入发布评审。"
                if auto_publish_ready
                else "存在能力项门禁阻塞，自动发布保持关闭。"
                if blockers
                else "当前轮评测尚未完成，自动发布暂不放行。"
            ),
        },
    }


def _build_training_loop_baseline_view(
    overview: dict[str, Any],
    *,
    agent_baseline: dict[str, Any],
    capabilities: list[dict[str, Any]],
) -> dict[str, Any]:
    release_version = str(
        agent_baseline.get("bound_release_version")
        or agent_baseline.get("latest_release_version")
        or agent_baseline.get("current_version")
        or ""
    ).strip()
    history_items = list(agent_baseline.get("history_key_capabilities") or []) if isinstance(agent_baseline, dict) else []
    if not history_items:
        history_items = [
            str(item.get("capability_name") or "").strip()
            for item in capabilities
            if isinstance(item, dict) and str(item.get("capability_name") or "").strip()
        ][:6]
    regression_rows = []
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        history_result = capability.get("historical_regression_result") if isinstance(capability.get("historical_regression_result"), dict) else {}
        regression_rows.append(
            {
                "capability_id": str(capability.get("capability_id") or "").strip(),
                "capability_name": str(capability.get("capability_name") or "").strip(),
                "status": str(history_result.get("status") or "").strip() or "pending",
                "summary": str(history_result.get("summary") or "").strip(),
                "current_score": capability.get("score_current"),
                "baseline_score": capability.get("score_baseline"),
            }
        )
    return {
        "current_release_version": release_version,
        "current_role_profile_summary": str(
            agent_baseline.get("capability_summary")
            or agent_baseline.get("knowledge_scope")
            or overview.get("capability_goal")
            or ""
        ).strip(),
        "history_key_capabilities": history_items,
        "regression_results": regression_rows,
        "source": "agent_registry" if agent_baseline else "training_queue_fallback",
    }


def get_training_queue_loop(
    root: Path,
    queue_task_id_text: str,
    *,
    include_test_data: bool = True,
) -> dict[str, object]:
    qid = safe_token(str(queue_task_id_text or ""), "", 160)
    if not qid:
        raise TrainingCenterError(400, "queue_task_id required", "queue_task_id_required")

    conn = connect_db(root)
    try:
        read_model = _sync_training_loop_read_model(
            conn,
            queue_task_id=qid,
            now_text=iso_ts(now_local()),
        )
        conn.commit()
    finally:
        conn.close()

    if bool(read_model["is_test_data"]) and not include_test_data:
        raise TrainingCenterError(
            404,
            "test data hidden when include_test_data=false",
            "test_data_hidden",
            {"queue_task_id": qid, "loop_id": str(read_model["loop_id"] or "")},
        )

    return {
        "loop_id": str(read_model["loop_id"] or ""),
        "queue_task_id": qid,
        "current_node_id": str(read_model["current_node_id"] or ""),
        "nodes": list(read_model["nodes"] or []),
        "edges": list(read_model["edges"] or []),
        "metrics_available": bool(read_model["metrics_available"]),
        "metrics_unavailable_reason": str(read_model["metrics_unavailable_reason"] or ""),
        "is_test_data": bool(read_model["is_test_data"]),
    }


def get_training_queue_status_detail(
    root: Path,
    queue_task_id_text: str,
    *,
    include_test_data: bool = True,
) -> dict[str, object]:
    qid = safe_token(str(queue_task_id_text or ""), "", 160)
    if not qid:
        raise TrainingCenterError(400, "queue_task_id required", "queue_task_id_required")

    conn = connect_db(root)
    try:
        read_model = _sync_training_loop_read_model(
            conn,
            queue_task_id=qid,
            now_text=iso_ts(now_local()),
        )
        agent_baseline = _training_loop_agent_baseline(
            conn,
            agent_id=str((read_model.get("current_overview") or {}).get("target_agent_id") or "").strip(),
        )
        conn.commit()
    finally:
        conn.close()

    if bool(read_model["is_test_data"]) and not include_test_data:
        raise TrainingCenterError(
            404,
            "test data hidden when include_test_data=false",
            "test_data_hidden",
            {"queue_task_id": qid, "loop_id": str(read_model["loop_id"] or "")},
        )

    capabilities = _build_training_loop_capabilities(
        read_model,
        queue_task_id=qid,
        agent_baseline=agent_baseline,
    )
    tasks_evolution = _build_training_loop_tasks_evolution(
        read_model,
        queue_task_id=qid,
        capabilities=capabilities,
    )
    baseline = _build_training_loop_baseline_view(
        dict(read_model["current_overview"] or {}),
        agent_baseline=agent_baseline,
        capabilities=capabilities,
    )

    return {
        "queue_task_id": qid,
        "loop_id": str(read_model["loop_id"] or ""),
        "current_node_id": str(read_model["current_node_id"] or ""),
        "execution_engine": EXECUTION_ENGINE,
        "current_overview": dict(read_model["current_overview"] or {}),
        "workset_changes": dict(read_model["workset_changes"] or {}),
        "evaluations": list(read_model["evaluations"] or []),
        "history_records": list(read_model["history_records"] or []),
        "capabilities": capabilities,
        "tasks_evolution": tasks_evolution,
        "baseline": baseline,
        "is_test_data": bool(read_model["is_test_data"]),
    }


def enter_training_queue_next_round(
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
        if "enter-next-round" not in available_actions:
            raise TrainingCenterError(
                409,
                "enter next round not available",
                "enter_next_round_not_available",
                {
                    "queue_task_id": qid,
                    "available_actions": available_actions,
                    "decision": str(current_node.get("decision") or "").strip(),
                    "decision_code": str(current_node.get("decision_code") or "").strip(),
                },
            )

        graph = _parse_loop_graph(read_model["graph"])
        raw_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue
            if str(raw_edge.get("kind") or "main").strip().lower() == "rollback":
                continue
            if str(raw_edge.get("from") or raw_edge.get("from_id") or "").strip() != qid:
                continue
            existing_next_qid = str(raw_edge.get("to") or raw_edge.get("to_id") or "").strip()
            if existing_next_qid:
                raise TrainingCenterError(
                    409,
                    "next round already exists",
                    "loop_next_round_exists",
                    {
                        "queue_task_id": qid,
                        "loop_id": str(read_model["loop_id"] or ""),
                        "created_queue_task_id": existing_next_qid,
                    },
                )

        seed = _resolve_training_queue_row(conn, qid)
        loop_id = _ensure_plan_loop_id(conn, seed)
        now_text = iso_ts(now_local())
        plan_id_text = training_plan_id()
        next_queue_task_id = training_queue_task_id()
        priority = str(seed["priority"] or seed["plan_priority"] or "").strip() or "P1"
        execution_engine = EXECUTION_ENGINE
        trainer_match = str(seed["trainer_match"] or "").strip()
        is_test_data = bool(int(seed["plan_is_test_data"] or seed["queue_is_test_data"] or 0))
        next_round_index = int(current_node.get("round_index") or 0) + 1

        conn.execute(
            """
            INSERT INTO training_plan (
                plan_id,loop_id,source,target_agent_id,capability_goal,training_tasks_json,acceptance_criteria,priority,similar_flag,created_by,is_test_data,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                plan_id_text,
                loop_id,
                "loop",
                str(seed["target_agent_id"] or "").strip(),
                str(seed["capability_goal"] or "").strip(),
                str(seed["training_tasks_json"] or "[]"),
                str(seed["acceptance_criteria"] or "").strip(),
                priority,
                0,
                operator_text,
                1 if is_test_data else 0,
                now_text,
            ),
        )
        conn.execute(
            """
            INSERT INTO training_queue (
                queue_task_id,plan_id,priority,status,execution_engine,trainer_match,is_test_data,enqueued_at,started_at,finished_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                next_queue_task_id,
                plan_id_text,
                priority,
                "queued",
                execution_engine,
                trainer_match,
                1 if is_test_data else 0,
                now_text,
                "",
                "",
            ),
        )

        nodes = list(graph.get("nodes") or [])
        if not any(str(node.get("node_id") or "").strip() == next_queue_task_id for node in nodes if isinstance(node, dict)):
            current_metrics = current_node.get("metrics") if isinstance(current_node.get("metrics"), dict) else {}
            nodes.append(
                {
                    "node_id": next_queue_task_id,
                    "title": f"R{next_round_index} 当前",
                    "round_index": next_round_index,
                    "round_label": f"R{next_round_index}",
                    "node_type": "round",
                    "decision": "等待执行三轮评测",
                    "decision_code": "awaiting_evaluation",
                    "next_action": "执行三轮评测",
                    "next_action_code": "execute",
                    "impact": reason_text or f"由 R{int(current_node.get('round_index') or 0)} 推进到下一轮",
                    "metrics": {
                        "avg_score": None,
                        "threshold": training_threshold_for_priority(priority),
                        "previous_avg_score": _safe_float(current_metrics.get("avg_score")),
                        "run_results": [],
                    },
                    "metrics_available": False,
                    "metrics_unavailable_reason": "evaluation_not_started",
                    "queue_task_id": next_queue_task_id,
                    "plan_id": plan_id_text,
                    "status": "queued",
                    "available_actions": [],
                    "run_ids": [],
                    "execution_engine": execution_engine,
                    "created_at": now_text,
                    "updated_at": now_text,
                }
            )
        edges = list(graph.get("edges") or [])
        edges.append({"from": qid, "to": next_queue_task_id, "kind": "main"})
        graph["nodes"] = nodes
        graph["edges"] = edges
        graph["current_node_id"] = next_queue_task_id

        conn.execute(
            """
            UPDATE training_loop_state
            SET graph_json=?,
                current_node_id=?,
                metrics_available=0,
                metrics_unavailable_reason='evaluation_not_started',
                updated_at=?
            WHERE loop_id=?
            """,
            (
                json.dumps(graph, ensure_ascii=False),
                next_queue_task_id,
                now_text,
                loop_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    audit_id = append_training_center_audit(
        root,
        action="enter-next-round",
        operator=operator_text,
        target_id=loop_id,
        detail={
            "queue_task_id": qid,
            "loop_id": loop_id,
            "created_queue_task_id": next_queue_task_id,
            "created_plan_id": plan_id_text,
            "reason": reason_text,
            "execution_engine": EXECUTION_ENGINE,
        },
    )
    return {
        "ok": True,
        "audit_id": audit_id,
        "loop_id": loop_id,
        "current_node_id": next_queue_task_id,
        "created_queue_task_id": next_queue_task_id,
        "created_plan_id": plan_id_text,
        "execution_engine": EXECUTION_ENGINE,
    }
