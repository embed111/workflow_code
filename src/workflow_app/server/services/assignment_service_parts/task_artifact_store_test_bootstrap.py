from __future__ import annotations


def _assignment_test_iso(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if "T" in text:
        return text if "+" in text or text.endswith("Z") else text + "+08:00"
    return text.replace(" ", "T") + "+08:00"


def bootstrap_assignment_test_graph(cfg: Any, *, operator: str) -> dict[str, Any]:
    operator_text = _default_assignment_operator(operator)
    ticket_id = _assignment_find_ticket_by_source_request(
        cfg.root,
        source_workflow=ASSIGNMENT_TEST_GRAPH_SOURCE,
        external_request_id=ASSIGNMENT_TEST_GRAPH_EXTERNAL_REQUEST_ID,
    )
    created = False
    if not ticket_id:
        ticket_id = assignment_ticket_id()
        created = True
    existing_nodes = []
    if not created:
        try:
            existing_nodes = _assignment_active_node_records(
                _assignment_load_node_records(cfg.root, ticket_id, include_deleted=True)
            )
        except AssignmentCenterError:
            existing_nodes = []
    if not created and existing_nodes:
        snapshot = _assignment_snapshot_from_files(
            cfg.root,
            ticket_id,
            include_test_data=True,
            reconcile_running=False,
        )
        return {
            "ticket_id": ticket_id,
            "created": False,
            "graph_overview": _graph_overview_payload(
                snapshot["graph_row"],
                metrics_summary=snapshot["metrics_summary"],
                scheduler_state_payload=snapshot["scheduler"],
            ),
        }
    seed_nodes, seed_edges, sticky_node_ids = _assignment_test_graph_seed()
    task_record = _assignment_build_task_record(
        ticket_id=ticket_id,
        graph_name=ASSIGNMENT_TEST_GRAPH_NAME,
        source_workflow=ASSIGNMENT_TEST_GRAPH_SOURCE,
        summary=ASSIGNMENT_TEST_GRAPH_SUMMARY,
        review_mode="none",
        global_concurrency_limit=DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT,
        is_test_data=True,
        external_request_id=ASSIGNMENT_TEST_GRAPH_EXTERNAL_REQUEST_ID,
        scheduler_state="running",
        pause_note="",
        created_at=ASSIGNMENT_TEST_GRAPH_CREATED_AT,
        updated_at=iso_ts(now_local()),
        edges=[
            {
                "from_node_id": from_id,
                "to_node_id": to_id,
                "edge_kind": "depends_on",
                "created_at": ASSIGNMENT_TEST_GRAPH_CREATED_AT,
                "record_state": "active",
            }
            for from_id, to_id in list(seed_edges or [])
        ],
    )
    node_records: list[dict[str, Any]] = []
    for node in list(seed_nodes or []):
        node_records.append(
            _assignment_build_node_record(
                ticket_id=ticket_id,
                node_id=str(node.get("node_id") or "").strip(),
                node_name=str(node.get("node_name") or "").strip(),
                source_schedule_id="",
                planned_trigger_at="",
                trigger_instance_id="",
                trigger_rule_summary="",
                assigned_agent_id=str(node.get("assigned_agent_id") or "").strip(),
                assigned_agent_name=str(node.get("assigned_agent_name") or "").strip(),
                node_goal=str(node.get("node_goal") or "").strip(),
                expected_artifact=str(node.get("expected_artifact") or "").strip(),
                delivery_mode=str(node.get("delivery_mode") or "none").strip().lower() or "none",
                delivery_receiver_agent_id=str(node.get("delivery_receiver_agent_id") or "").strip(),
                delivery_receiver_agent_name=str(node.get("delivery_receiver_agent_name") or "").strip(),
                artifact_delivery_status=str(node.get("artifact_delivery_status") or "pending").strip().lower() or "pending",
                artifact_delivered_at=str(node.get("artifact_delivered_at") or "").strip(),
                artifact_paths=list(node.get("artifact_paths") or []),
                status=str(node.get("status") or "pending").strip().lower() or "pending",
                priority=int(node.get("priority") or 1),
                completed_at=str(node.get("completed_at") or "").strip(),
                success_reason=str(node.get("success_reason") or "").strip(),
                result_ref=str(node.get("result_ref") or "").strip(),
                failure_reason=str(node.get("failure_reason") or "").strip(),
                created_at=str(node.get("created_at") or ASSIGNMENT_TEST_GRAPH_CREATED_AT).strip() or ASSIGNMENT_TEST_GRAPH_CREATED_AT,
                updated_at=str(node.get("updated_at") or ASSIGNMENT_TEST_GRAPH_CREATED_AT).strip() or ASSIGNMENT_TEST_GRAPH_CREATED_AT,
                upstream_node_ids=[str(item or "").strip() for item in list(node.get("upstream_node_ids") or []) if str(item or "").strip()],
                downstream_node_ids=[str(item or "").strip() for item in list(node.get("downstream_node_ids") or []) if str(item or "").strip()],
            )
        )
    task_record, node_records, _changed = _assignment_recompute_task_state(
        cfg.root,
        task_record=task_record,
        node_records=node_records,
        sticky_node_ids=sticky_node_ids,
        reconcile_running=False,
    )
    delivered_node = next((item for item in node_records if str(item.get("node_id") or "").strip() == "T8"), {})
    if delivered_node:
        delivered_paths = [path.as_posix() for path in _node_artifact_file_paths(cfg.root, delivered_node)]
        delivered_inbox_paths = [path.as_posix() for path in _node_delivery_inbox_file_paths(cfg.root, delivered_node)]
        delivered_payload = _artifact_delivery_markdown(
            delivered_node,
            delivered_at=_assignment_test_iso("2026-03-14 12:02:07"),
            operator=operator_text,
            artifact_label=str(delivered_node.get("expected_artifact") or delivered_node.get("node_name") or "依赖关系图"),
            delivery_note="任务中心原型测试数据预置交付产物。",
        )
        for raw_path in delivered_paths:
            path = Path(raw_path).resolve(strict=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(delivered_payload, encoding="utf-8")
        for raw_path in delivered_inbox_paths:
            path = Path(raw_path).resolve(strict=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(delivered_payload, encoding="utf-8")
        _write_assignment_delivery_info_file(
            cfg.root,
            node=delivered_node,
            delivered_at=_assignment_test_iso("2026-03-14 12:02:07"),
            operator=operator_text,
            artifact_label=str(delivered_node.get("expected_artifact") or delivered_node.get("node_name") or "依赖关系图"),
            delivery_note="任务中心原型测试数据预置交付产物。",
            canonical_artifact_paths=delivered_paths,
            delivery_inbox_paths=delivered_inbox_paths,
        )
        delivered_node["artifact_delivery_status"] = "delivered"
        delivered_node["artifact_delivery_status_text"] = _artifact_delivery_status_text("delivered")
        delivered_node["artifact_delivered_at"] = _assignment_test_iso("2026-03-14 12:02:07")
        delivered_node["artifact_paths"] = delivered_paths
        delivered_node["result_ref"] = delivered_paths[0] if delivered_paths else ""
        delivered_node["updated_at"] = _assignment_test_iso("2026-03-14 12:02:07")
    failed_node = next((item for item in node_records if str(item.get("node_id") or "").strip() == "T20"), {})
    if failed_node:
        failed_paths = [path.as_posix() for path in _node_artifact_file_paths(cfg.root, failed_node)]
        failed_payload = "\n".join(
            [
                "# 沙箱试跑失败日志",
                "",
                "- node_id: T20",
                "- node_name: 沙箱试跑",
                "- completed_at: 2026-03-14T12:19:33+08:00",
                "- failure_reason: 运行失败：沙箱冒烟未通过。",
                "",
                "## 摘要",
                "",
                "接口联调前置检查未通过，调度链路保持阻塞。",
                "",
            ]
        ).strip() + "\n"
        failed_payload = _artifact_text_to_html_document(
            failed_payload,
            title=str(failed_node.get("expected_artifact") or failed_node.get("node_name") or "失败日志"),
        )
        for raw_path in failed_paths:
            path = Path(raw_path).resolve(strict=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(failed_payload, encoding="utf-8")
        failed_node["artifact_paths"] = failed_paths
        failed_node["updated_at"] = _assignment_test_iso("2026-03-14 12:19:33")
    _assignment_store_snapshot(cfg.root, task_record=task_record, node_records=node_records)
    _assignment_write_audit_entry(
        cfg.root,
        ticket_id=ticket_id,
        node_id="",
        action="bootstrap_test_graph",
        operator=operator_text,
        reason="bootstrap assignment prototype graph",
        target_status="running",
        detail={
            "graph_name": ASSIGNMENT_TEST_GRAPH_NAME,
            "source_workflow": ASSIGNMENT_TEST_GRAPH_SOURCE,
            "external_request_id": ASSIGNMENT_TEST_GRAPH_EXTERNAL_REQUEST_ID,
        },
        created_at=iso_ts(now_local()),
    )
    snapshot = _assignment_snapshot_from_files(
        cfg.root,
        ticket_id,
        include_test_data=True,
        reconcile_running=False,
        sticky_node_ids=sticky_node_ids,
    )
    return {
        "ticket_id": ticket_id,
        "created": True if created else not bool(existing_nodes),
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }
