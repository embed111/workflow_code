from __future__ import annotations

_ASSIGNMENT_STALE_RECOVERY_LOCK_GUARD = threading.Lock()
_ASSIGNMENT_STALE_RECOVERY_LOCKS: dict[str, threading.Lock] = {}


def _assignment_stale_recovery_lock(ticket_id: str, node_id: str) -> threading.Lock:
    ticket_key = safe_token(str(ticket_id or ""), "", 160)
    node_key = safe_token(str(node_id or ""), "", 160)
    if not ticket_key or not node_key:
        return _ASSIGNMENT_STALE_RECOVERY_LOCK_GUARD
    lock_key = f"{ticket_key}:{node_key}"
    with _ASSIGNMENT_STALE_RECOVERY_LOCK_GUARD:
        existing = _ASSIGNMENT_STALE_RECOVERY_LOCKS.get(lock_key)
        if existing is not None:
            return existing
        created = threading.Lock()
        _ASSIGNMENT_STALE_RECOVERY_LOCKS[lock_key] = created
        return created


def _assignment_persist_stale_node_terminal_state(
    root: Path,
    *,
    task_record: dict[str, Any],
    node_record: dict[str, Any],
    now_text: str,
) -> None:
    ticket_id = str(task_record.get("ticket_id") or "").strip()
    node_id = str(node_record.get("node_id") or "").strip()
    if not ticket_id or not node_id:
        return
    _assignment_write_json(_assignment_node_record_path(root, ticket_id, node_id), node_record)
    task_snapshot = dict(task_record)
    task_snapshot["updated_at"] = now_text
    _assignment_write_json(_assignment_graph_record_path(root, ticket_id), task_snapshot)


def _assignment_has_stale_recovery_audit(root: Path, *, ticket_id: str, node_id: str) -> bool:
    return any(
        str(item.get("action") or "").strip().lower() == "recover_stale_running"
        for item in _assignment_load_audit_records(root, ticket_id=ticket_id, node_id=node_id, limit=32)
    )


def _assignment_parse_iso_timestamp(value: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return None
    from datetime import datetime

    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _assignment_recent_runtime_upgrade_recovery_detail(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    now_text: str,
) -> dict[str, Any]:
    now_dt = _assignment_parse_iso_timestamp(now_text)
    if now_dt is None:
        return {}
    try:
        from workflow_app.server.services import runtime_upgrade_service
    except Exception:
        return {}
    last_action = dict(runtime_upgrade_service.read_prod_last_action() or {})
    if str(last_action.get("action") or "").strip().lower() != "upgrade":
        return {}
    status = str(last_action.get("status") or "").strip().lower()
    if status != "success":
        return {}
    finished_at_text = str(last_action.get("finished_at") or "").strip()
    finished_at_dt = _assignment_parse_iso_timestamp(finished_at_text)
    if finished_at_dt is None:
        return {}
    if abs((now_dt - finished_at_dt).total_seconds()) > 180:
        return {}
    matched_run: dict[str, Any] = {}
    for run in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        run_status = str(run.get("status") or "").strip().lower()
        if run_status not in {"starting", "running"}:
            continue
        started_at_dt = _assignment_parse_iso_timestamp(
            run.get("started_at") or run.get("created_at") or run.get("updated_at")
        )
        if started_at_dt is not None and finished_at_dt < started_at_dt:
            continue
        matched_run = dict(run)
        break
    if not matched_run:
        return {}
    previous_version = str(last_action.get("previous_version") or "").strip()
    current_version = str(last_action.get("current_version") or last_action.get("candidate_version") or "").strip()
    if previous_version and current_version and previous_version != current_version:
        failure_reason = (
            f"正式环境已从 {previous_version} 升级到 {current_version}，当前批次在升级切换中中断，请在新版本继续。"
        )
    elif current_version:
        failure_reason = f"正式环境已切换到 {current_version}，当前批次在升级切换中中断，请在新版本继续。"
    else:
        failure_reason = "检测到正式环境升级切换，当前批次在升级切换中中断，请在新版本继续。"
    return {
        "run_id": str(matched_run.get("run_id") or "").strip(),
        "run_latest_event": "检测到正式环境已完成升级切换，已自动结束当前批次。",
        "failure_reason": failure_reason,
        "audit_reason": "recover stale running node after runtime upgrade switch",
        "audit_detail": {
            "action": "upgrade",
            "status": status,
            "finished_at": finished_at_text,
            "previous_version": previous_version,
            "current_version": current_version,
            "candidate_version": str(last_action.get("candidate_version") or "").strip(),
            "evidence_path": str(last_action.get("evidence_path") or "").strip(),
            "run_id": str(matched_run.get("run_id") or "").strip(),
        },
    }


def _assignment_task_visible(task_record: dict[str, Any], *, include_test_data: bool) -> bool:
    if str(task_record.get("record_state") or "active").strip().lower() == "deleted":
        return False
    if include_test_data:
        return True
    return not bool(task_record.get("is_test_data"))


def _assignment_active_node_records(node_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(node_records or [])
        if str(item.get("record_state") or "active").strip().lower() != "deleted"
    ]


def _assignment_active_edges(task_record: dict[str, Any], node_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = list(task_record.get("edges") or [])
    if not edges:
        edges = _assignment_edges_from_node_records(node_records)
    active_node_ids = {
        str(item.get("node_id") or "").strip()
        for item in list(node_records or [])
        if str(item.get("record_state") or "active").strip().lower() != "deleted"
    }
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for edge in list(edges or []):
        from_id = str(edge.get("from_node_id") or "").strip()
        to_id = str(edge.get("to_node_id") or "").strip()
        if not from_id or not to_id:
            continue
        if from_id not in active_node_ids or to_id not in active_node_ids:
            continue
        if str(edge.get("record_state") or "active").strip().lower() == "deleted":
            continue
        pair = (from_id, to_id)
        if pair in seen:
            continue
        seen.add(pair)
        out.append(
            {
                "from_node_id": from_id,
                "to_node_id": to_id,
                "edge_kind": str(edge.get("edge_kind") or "depends_on").strip() or "depends_on",
                "created_at": str(edge.get("created_at") or "").strip(),
                "record_state": "active",
            }
        )
    out.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("from_node_id") or ""),
            str(item.get("to_node_id") or ""),
        )
    )
    return out


def _assignment_edge_pairs(edges: list[dict[str, Any]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for edge in list(edges or []):
        from_id = str(edge.get("from_node_id") or "").strip()
        to_id = str(edge.get("to_node_id") or "").strip()
        if from_id and to_id:
            pairs.append((from_id, to_id))
    return pairs


def _assignment_apply_edges_to_nodes(
    node_records: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    upstream_map, downstream_map = _edge_maps(edges)
    changed = False
    updated: list[dict[str, Any]] = []
    for row in list(node_records or []):
        current = dict(row)
        if str(current.get("record_state") or "active").strip().lower() == "deleted":
            updated.append(current)
            continue
        node_id = str(current.get("node_id") or "").strip()
        next_upstream = list(upstream_map.get(node_id) or [])
        next_downstream = list(downstream_map.get(node_id) or [])
        prev_upstream = [
            str(item or "").strip()
            for item in list(current.get("upstream_node_ids") or [])
            if str(item or "").strip()
        ]
        prev_downstream = [
            str(item or "").strip()
            for item in list(current.get("downstream_node_ids") or [])
            if str(item or "").strip()
        ]
        if prev_upstream != next_upstream:
            current["upstream_node_ids"] = next_upstream
            changed = True
        if prev_downstream != next_downstream:
            current["downstream_node_ids"] = next_downstream
            changed = True
        updated.append(current)
    return updated, changed


def _assignment_live_run_keys_from_files(root: Path, *, ticket_id: str = "") -> set[tuple[str, str]]:
    ticket_filter = _assignment_resolve_graph_ticket_id(root, ticket_id)
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    now_dt = now_local()
    live_keys: set[tuple[str, str]] = set()
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for current_ticket_id in _assignment_list_ticket_ids_lightweight(root):
        if ticket_filter and current_ticket_id != ticket_filter:
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            current_ticket_id,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        for run in _assignment_load_run_records(root, ticket_id=current_ticket_id):
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
            if node_id:
                live_keys.add((current_ticket_id, node_id))
    return live_keys


def _assignment_list_ticket_ids_lightweight(root: Path) -> list[str]:
    tasks_root = _assignment_tasks_root(root)
    if not tasks_root.exists() or not tasks_root.is_dir():
        return []
    return [
        str(path.name or "").strip()
        for path in sorted(tasks_root.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir() and str(path.name or "").strip()
    ]


def _assignment_load_task_record_lightweight(root: Path, ticket_id: str) -> dict[str, Any]:
    task_record = _assignment_read_json(_assignment_graph_record_path(root, ticket_id))
    if task_record:
        return task_record
    try:
        return _assignment_load_task_record(root, ticket_id)
    except AssignmentCenterError:
        return {}


def _assignment_load_active_node_records_lightweight(root: Path, ticket_id: str) -> list[dict[str, Any]]:
    nodes_root = _assignment_ticket_workspace_dir(root, ticket_id) / "nodes"
    if nodes_root.exists() and nodes_root.is_dir():
        rows: list[dict[str, Any]] = []
        for path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            payload = _assignment_read_json(path)
            if not payload:
                continue
            if str(payload.get("record_state") or "active").strip().lower() == "deleted":
                continue
            rows.append(payload)
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("node_id") or "")))
        return rows
    try:
        return _assignment_active_node_records(_assignment_load_node_records(root, ticket_id, include_deleted=True))
    except AssignmentCenterError:
        return []


def _assignment_live_node_ids_for_ticket(root: Path, *, ticket_id: str) -> set[str]:
    ticket_text = safe_token(str(ticket_id or ""), "", 160)
    if not ticket_text:
        return set()
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    now_dt = now_local()
    live_node_ids: set[str] = set()
    for run in _assignment_load_run_records(root, ticket_id=ticket_text):
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
        if node_id:
            live_node_ids.add(node_id)
    return live_node_ids


def _assignment_terminal_run_truth_from_files(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
) -> dict[str, Any]:
    for run in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        status = str(run.get("status") or "").strip().lower()
        if status not in {"succeeded", "failed", "cancelled"}:
            continue
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            continue
        refs = _assignment_run_file_paths(root, ticket_id, run_id)
        result_payload = _assignment_read_json(refs["result"])
        events = _assignment_read_jsonl(refs["events"])
        final_event = next(
            (
                item
                for item in reversed(list(events or []))
                if str((item or {}).get("event_type") or "").strip().lower() == "final_result"
            ),
            {},
        )
        result_exists = refs["result"].exists()
        result_ref = str(run.get("result_ref") or "").strip()
        if not result_ref and result_exists:
            result_ref = refs["result"].as_posix()
        if not (
            result_exists
            or result_ref
            or bool(final_event)
            or str(run.get("finished_at") or "").strip()
        ):
            continue
        return {
            "status": status,
            "run_record": dict(run),
            "result_payload": result_payload if isinstance(result_payload, dict) else {},
            "final_event": final_event if isinstance(final_event, dict) else {},
            "result_ref": result_ref,
        }
    return {}


def _assignment_project_terminal_run_truth_to_node(
    node_record: dict[str, Any],
    terminal_truth: dict[str, Any],
    *,
    now_text: str,
) -> dict[str, Any]:
    current = dict(node_record or {})
    truth = dict(terminal_truth or {})
    if not current or not truth:
        return current
    run_record = dict(truth.get("run_record") or {})
    result_payload = dict(truth.get("result_payload") or {})
    final_event = dict(truth.get("final_event") or {})
    status = str(truth.get("status") or "").strip().lower()
    result_ref = str(truth.get("result_ref") or "").strip()
    completed_at = str(run_record.get("finished_at") or current.get("completed_at") or now_text).strip() or now_text
    latest_event = str(run_record.get("latest_event") or final_event.get("message") or "").strip()
    current["completed_at"] = completed_at
    current["updated_at"] = now_text
    if status == "succeeded":
        current["status"] = "succeeded"
        current["status_text"] = _node_status_text("succeeded")
        current["success_reason"] = (
            str(result_payload.get("result_summary") or "").strip()
            or latest_event
            or str(current.get("success_reason") or "").strip()
            or "执行完成"
        )
        current["result_ref"] = result_ref
        current["failure_reason"] = ""
        return current
    failure_text = (
        latest_event
        or str(final_event.get("message") or "").strip()
        or str(result_payload.get("result_summary") or "").strip()
        or ("执行已取消" if status == "cancelled" else "assignment execution failed")
    )
    current["status"] = "failed"
    current["status_text"] = _node_status_text("failed")
    current["success_reason"] = ""
    current["result_ref"] = result_ref
    current["failure_reason"] = failure_text
    return current


def _assignment_project_live_run_status_for_nodes(
    root: Path,
    *,
    ticket_id: str,
    node_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    live_node_ids = _assignment_live_node_ids_for_ticket(root, ticket_id=ticket_id)
    updated: list[dict[str, Any]] = []
    for row in list(node_records or []):
        current = dict(row)
        if str(current.get("record_state") or "active").strip().lower() == "deleted":
            updated.append(current)
            continue
        node_id = str(current.get("node_id") or "").strip()
        status = str(current.get("status") or "").strip().lower()
        if status == "running" and node_id and node_id not in live_node_ids:
            terminal_truth = _assignment_terminal_run_truth_from_files(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
            )
            if terminal_truth:
                current = _assignment_project_terminal_run_truth_to_node(
                    current,
                    terminal_truth,
                    now_text=iso_ts(now_local()),
                )
            else:
                current["status"] = "failed"
                current["status_text"] = _node_status_text("failed")
        updated.append(current)
    return updated


def _assignment_try_recover_terminal_run_from_files(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    run_record: dict[str, Any],
) -> bool:
    run_id = str(run_record.get("run_id") or "").strip()
    if not run_id:
        return False
    refs = _assignment_run_file_paths(root, ticket_id, run_id)
    result_payload = _assignment_read_json(refs["result"])
    events = _assignment_read_jsonl(refs["events"])
    final_event = next(
        (
            item
            for item in reversed(list(events or []))
            if str((item or {}).get("event_type") or "").strip().lower() == "final_result"
        ),
        {},
    )
    has_result_payload = bool(result_payload)
    has_final_event = bool(final_event)
    if not has_result_payload and not has_final_event:
        return False
    stdout_text = _read_assignment_run_text(refs["stdout"].as_posix())
    stderr_text = _read_assignment_run_text(refs["stderr"].as_posix())
    detail = dict(final_event.get("detail") or {}) if isinstance(final_event, dict) else {}
    try:
        exit_code = int(detail.get("exit_code") or run_record.get("exit_code") or 0)
    except Exception:
        exit_code = 0
    failure_message = ""
    if exit_code != 0:
        failure_message = (
            str(final_event.get("message") or "").strip()
            or _short_assignment_text(stderr_text, 500)
            or f"assignment execution failed with exit={exit_code}"
        )
    _finalize_assignment_execution_run(
        root,
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        exit_code=exit_code,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        result_payload=result_payload if isinstance(result_payload, dict) else {},
        failure_message=failure_message,
        suppress_followup_dispatch=True,
    )
    _kill_assignment_run_process(run_id, provider_pid=int(run_record.get("provider_pid") or 0))
    return True


def _assignment_try_recover_terminal_node_from_files(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
) -> bool:
    recovered = False
    for run in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        status = str(run.get("status") or "").strip().lower()
        if status not in {"starting", "running"}:
            continue
        if _assignment_try_recover_terminal_run_from_files(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            run_record=run,
        ):
            recovered = True
    return recovered


def _assignment_reconcile_stale_task_state_internal(
    root: Path,
    *,
    task_record: dict[str, Any],
    node_records: list[dict[str, Any]],
    live_keys: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    if bool(task_record.get("is_test_data")):
        return dict(task_record), [dict(item) for item in list(node_records or [])], False
    ticket_id = str(task_record.get("ticket_id") or "").strip()
    if not ticket_id:
        return dict(task_record), [dict(item) for item in list(node_records or [])], False
    if live_keys is None:
        live_keys = _assignment_live_run_keys_from_files(root, ticket_id=ticket_id)
    now_text = iso_ts(now_local())
    changed = False
    updated_nodes: list[dict[str, Any]] = []
    for node in list(node_records or []):
        current = dict(node)
        if str(current.get("record_state") or "active").strip().lower() == "deleted":
            updated_nodes.append(current)
            continue
        node_id = str(current.get("node_id") or "").strip()
        status = str(current.get("status") or "").strip().lower()
        if (ticket_id, node_id) in live_keys and status in {"pending", "ready", "blocked"}:
            current["status"] = "running"
            current["status_text"] = _node_status_text("running")
            current["updated_at"] = now_text
            changed = True
        elif status == "running" and (ticket_id, node_id) not in live_keys:
            with _assignment_stale_recovery_lock(ticket_id, node_id):
                latest_node = _assignment_read_json(_assignment_node_record_path(root, ticket_id, node_id))
                latest_status = str(
                    latest_node.get("status") or current.get("status") or ""
                ).strip().lower()
                if latest_node and latest_status != "running":
                    current = dict(latest_node)
                    changed = True
                elif _assignment_try_recover_terminal_node_from_files(
                    root,
                    ticket_id=ticket_id,
                    node_id=node_id,
                ):
                    refreshed_task = _assignment_read_json(_assignment_graph_record_path(root, ticket_id))
                    refreshed_nodes = _assignment_load_node_records(root, ticket_id, include_deleted=True)
                    return (
                        dict(refreshed_task or task_record),
                        [dict(item) for item in list(refreshed_nodes or node_records)],
                        True,
                    )
                else:
                    terminal_truth = _assignment_terminal_run_truth_from_files(
                        root,
                        ticket_id=ticket_id,
                        node_id=node_id,
                    )
                    if terminal_truth:
                        current = _assignment_project_terminal_run_truth_to_node(
                            current,
                            terminal_truth,
                            now_text=now_text,
                        )
                        _assignment_persist_stale_node_terminal_state(
                            root,
                            task_record=task_record,
                            node_record=current,
                            now_text=now_text,
                        )
                        changed = True
                        updated_nodes.append(current)
                        continue
                    runtime_upgrade_recovery = _assignment_recent_runtime_upgrade_recovery_detail(
                        root,
                        ticket_id=ticket_id,
                        node_id=node_id,
                        now_text=now_text,
                    )
                    stale_failure_context = (
                        {}
                        if runtime_upgrade_recovery
                        else _assignment_stale_recovery_failure_context(
                            root,
                            ticket_id=ticket_id,
                            node_id=node_id,
                            node_record=current,
                        )
                    )
                    failure_base_text = str(
                        runtime_upgrade_recovery.get("failure_reason")
                        or stale_failure_context.get("failure_reason")
                        or current.get("failure_reason")
                        or "运行句柄缺失或 workflow 已重启，请手动重跑。"
                    ).strip()
                    preserved_result_ref = str(current.get("result_ref") or "").strip()
                    preserved_result_payload: dict[str, Any] = {}
                    if preserved_result_ref:
                        existing_payload = _assignment_read_json(Path(preserved_result_ref))
                        if isinstance(existing_payload, dict) and _assignment_result_payload_has_meaningful_content(
                            existing_payload
                        ):
                            preserved_result_payload = existing_payload
                        else:
                            preserved_result_ref = ""
                    current["status"] = "failed"
                    current["status_text"] = _node_status_text("failed")
                    current["completed_at"] = now_text
                    current["success_reason"] = ""
                    current["result_ref"] = preserved_result_ref
                    current["failure_reason"] = (
                        _assignment_failure_message_with_result_context(
                            failure_base_text,
                            result_payload=preserved_result_payload,
                        )
                        if preserved_result_ref
                        else failure_base_text
                    )
                    current["updated_at"] = now_text
                    changed = True
                    for run in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
                        run_status = str(run.get("status") or "").strip().lower()
                        if run_status not in {"starting", "running"}:
                            continue
                        run_id = str(run.get("run_id") or "").strip()
                        workspace_path_text = str(run.get("workspace_path") or "").strip()
                        provider_pid = int(run.get("provider_pid") or 0)
                        run_result_ref = str(run.get("result_ref") or "").strip()
                        run_result_payload: dict[str, Any] = {}
                        refs = _assignment_run_file_paths(root, ticket_id, run_id) if run_id else {}
                        result_path = refs.get("result") if isinstance(refs, dict) else None
                        if not run_result_ref and isinstance(result_path, Path) and result_path.exists():
                            run_result_ref = result_path.as_posix()
                        if isinstance(result_path, Path) and result_path.exists():
                            raw_result_payload = _assignment_read_json(result_path)
                            if isinstance(raw_result_payload, dict):
                                run_result_payload = raw_result_payload
                        if (
                            not preserved_result_ref
                            and run_result_ref
                            and _assignment_result_payload_has_meaningful_content(run_result_payload)
                        ):
                            preserved_result_ref = run_result_ref
                            preserved_result_payload = run_result_payload
                        run["status"] = "cancelled"
                        run["latest_event"] = str(
                            runtime_upgrade_recovery.get("run_latest_event")
                            or stale_failure_context.get("run_latest_event")
                            or "检测到运行句柄缺失，已自动结束当前批次。"
                        ).strip()
                        run["latest_event_at"] = now_text
                        run["finished_at"] = now_text
                        run["updated_at"] = now_text
                        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run)
                        _kill_assignment_run_process(run_id, provider_pid=provider_pid)
                        current["result_ref"] = preserved_result_ref
                        current["failure_reason"] = (
                            _assignment_failure_message_with_result_context(
                                failure_base_text,
                                result_payload=preserved_result_payload,
                            )
                            if preserved_result_ref
                            else failure_base_text
                        )
                        try:
                            memory_detail = _append_assignment_workspace_memory_round(
                                workspace_path_text,
                                ticket_id=ticket_id,
                                node_record=current,
                                run_id=run_id,
                                exit_code=int(run.get("exit_code") or 1),
                                result_ref=preserved_result_ref or run_result_ref,
                                summary_text=str(current.get("failure_reason") or "").strip() or failure_base_text,
                                artifact_paths=list(current.get("artifact_paths") or []),
                                warnings=(
                                    list(preserved_result_payload.get("warnings") or [])
                                    if preserved_result_ref
                                    else []
                                ),
                                appended_at=now_text,
                            )
                            if memory_detail:
                                _assignment_write_audit_entry(
                                    root,
                                    ticket_id=ticket_id,
                                    node_id=node_id,
                                    action="append_workspace_memory",
                                    operator="assignment-system",
                                    reason="appended workspace daily memory after stale run recovery",
                                    target_status="failed",
                                    detail=memory_detail,
                                    created_at=now_text,
                                )
                        except Exception:
                            pass
                    # Persist the terminal node state before emitting side effects so concurrent
                    # readers do not keep re-entering stale recovery from the old running file.
                    _assignment_persist_stale_node_terminal_state(
                        root,
                        task_record=task_record,
                        node_record=current,
                        now_text=now_text,
                    )
                    if not _assignment_has_stale_recovery_audit(root, ticket_id=ticket_id, node_id=node_id):
                        audit_detail = {"result_ref": preserved_result_ref}
                        runtime_upgrade_audit_detail = dict(runtime_upgrade_recovery.get("audit_detail") or {})
                        if runtime_upgrade_audit_detail:
                            audit_detail["runtime_upgrade"] = runtime_upgrade_audit_detail
                        preserved_failure_context = dict(stale_failure_context.get("audit_detail") or {})
                        if preserved_failure_context:
                            audit_detail["preserved_failure_context"] = preserved_failure_context
                        _assignment_write_audit_entry(
                            root,
                            ticket_id=ticket_id,
                            node_id=node_id,
                            action="recover_stale_running",
                            operator="assignment-system",
                            reason=str(
                                runtime_upgrade_recovery.get("audit_reason")
                                or "recover stale running node without live execution"
                            ).strip(),
                            target_status="failed",
                            detail=audit_detail,
                            created_at=now_text,
                        )
                        try:
                            schedule_result = _assignment_queue_self_iteration_schedule(
                                root,
                                task_record=task_record,
                                node_record=current,
                                result_summary=str(current.get("failure_reason") or "").strip()
                                or "运行句柄缺失或 workflow 已重启，请手动重跑。",
                                success=False,
                            )
                            if bool(schedule_result.get("queued")):
                                _assignment_write_audit_entry(
                                    root,
                                    ticket_id=ticket_id,
                                    node_id=node_id,
                                    action="schedule_self_iteration",
                                    operator="assignment-system",
                                    reason="queued next self-iteration schedule after stale run recovery",
                                    target_status="failed",
                                    detail=schedule_result,
                                    created_at=now_text,
                                )
                        except Exception:
                            pass
        updated_nodes.append(current)
    return dict(task_record), updated_nodes, changed


def _assignment_reconcile_stale_task_state(
    root: Path,
    *,
    task_record: dict[str, Any],
    node_records: list[dict[str, Any]],
    live_keys: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    next_task, next_nodes, _changed = _assignment_reconcile_stale_task_state_internal(
        root,
        task_record=task_record,
        node_records=node_records,
        live_keys=live_keys,
    )
    return next_task, next_nodes


def _assignment_find_ticket_by_source_request(
    root: Path,
    *,
    source_workflow: str,
    external_request_id: str,
) -> str:
    source_text = str(source_workflow or "").strip()
    request_text = str(external_request_id or "").strip()
    if not source_text or not request_text:
        return ""
    if (
        source_text == ASSIGNMENT_GLOBAL_GRAPH_SOURCE_WORKFLOW
        and request_text == ASSIGNMENT_GLOBAL_GRAPH_REQUEST_ID
    ):
        return _assignment_ensure_workflow_ui_global_graph_ticket(root)
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for ticket_id in _assignment_list_ticket_ids(root):
        try:
            task_record = _assignment_load_task_record(root, ticket_id)
        except AssignmentCenterError:
            continue
        if str(task_record.get("record_state") or "active").strip().lower() == "deleted":
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            ticket_id,
            ticket_record=task_record,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        if str(task_record.get("source_workflow") or "").strip() != source_text:
            continue
        if str(task_record.get("external_request_id") or "").strip() != request_text:
            continue
        return ticket_id
    return ""


def list_assignments(
    root: Path,
    *,
    include_test_data: bool = True,
    source_workflow: Any = "",
    external_request_id: Any = "",
    offset: Any = 0,
    limit: Any = 0,
) -> dict[str, Any]:
    source_filter = str(source_workflow or "").strip()
    request_filter = str(external_request_id or "").strip()
    page_offset = _normalize_history_loaded(offset)
    try:
        page_limit = int(limit or 0)
    except Exception:
        page_limit = 0
    if page_limit > 0:
        page_limit = max(1, min(200, page_limit))
    else:
        page_limit = 0
    items: list[dict[str, Any]] = []
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for ticket_id in _assignment_list_ticket_ids_lightweight(root):
        graph_row = _assignment_load_task_record_lightweight(root, ticket_id)
        if not graph_row:
            continue
        if not _assignment_task_visible(graph_row, include_test_data=include_test_data):
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            ticket_id,
            ticket_record=graph_row,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        if source_filter and str(graph_row.get("source_workflow") or "").strip() != source_filter:
            continue
        if request_filter and str(graph_row.get("external_request_id") or "").strip() != request_filter:
            continue
        node_records = _assignment_project_live_run_status_for_nodes(
            root,
            ticket_id=ticket_id,
            node_records=_assignment_load_active_node_records_lightweight(root, ticket_id),
        )
        metrics_summary = _graph_metrics(node_records)
        items.append(
            {
                "ticket_id": str(graph_row.get("ticket_id") or "").strip(),
                "graph_name": str(graph_row.get("graph_name") or "").strip(),
                "source_workflow": str(graph_row.get("source_workflow") or "").strip(),
                "summary": str(graph_row.get("summary") or "").strip(),
                "review_mode": str(graph_row.get("review_mode") or "").strip(),
                "global_concurrency_limit": int(graph_row.get("global_concurrency_limit") or 0),
                "is_test_data": bool(graph_row.get("is_test_data")),
                "external_request_id": str(graph_row.get("external_request_id") or "").strip(),
                "scheduler_state": str(graph_row.get("scheduler_state") or "idle").strip().lower(),
                "scheduler_state_text": _scheduler_state_text(graph_row.get("scheduler_state") or "idle"),
                "pause_note": str(graph_row.get("pause_note") or "").strip(),
                "created_at": str(graph_row.get("created_at") or "").strip(),
                "updated_at": str(graph_row.get("updated_at") or "").strip(),
                "metrics_summary": {
                    "total_nodes": int(metrics_summary.get("total_nodes") or 0),
                    "pending_nodes": int((metrics_summary.get("status_counts") or {}).get("pending") or 0),
                    "ready_nodes": int((metrics_summary.get("status_counts") or {}).get("ready") or 0),
                    "running_nodes": int((metrics_summary.get("status_counts") or {}).get("running") or 0),
                    "failed_nodes": int((metrics_summary.get("status_counts") or {}).get("failed") or 0),
                    "blocked_nodes": int((metrics_summary.get("status_counts") or {}).get("blocked") or 0),
                    "executed_count": int(metrics_summary.get("executed_count") or 0),
                    "unexecuted_count": int(metrics_summary.get("unexecuted_count") or 0),
                },
            }
        )
    items.sort(
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("ticket_id") or ""),
        ),
        reverse=True,
    )
    items.sort(
        key=lambda item: (
            0 if int((item.get("metrics_summary") or {}).get("running_nodes") or 0) > 0 else
            1 if int((item.get("metrics_summary") or {}).get("unexecuted_count") or 0) > 0 else
            2,
            -int((item.get("metrics_summary") or {}).get("running_nodes") or 0),
            -int((item.get("metrics_summary") or {}).get("unexecuted_count") or 0),
        )
    )
    total_items = len(items)
    if page_offset > 0 or page_limit > 0:
        end = page_offset + page_limit if page_limit > 0 else None
        items = items[page_offset:end]
    settings = get_assignment_concurrency_settings(root)
    return {
        "items": items,
        "pagination": {
            "offset": page_offset,
            "limit": page_limit,
            "returned": len(items),
            "total_items": total_items,
            "has_more": (page_offset + len(items)) < total_items,
        },
        "settings": {
            "global_concurrency_limit": int(settings.get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
            "updated_at": str(settings.get("updated_at") or ""),
        },
    }


def get_assignment_overview(root: Path, ticket_id_text: str, *, include_test_data: bool = True) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
        include_serialized_nodes=False,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    return {
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "priority_rules": {
            "ui_levels": ["P0", "P1", "P2", "P3"],
            "backend_levels": [0, 1, 2, 3],
            "highest_first": True,
            "tie_breaker": "created_at_asc",
        },
    }


def get_assignment_graph(
    root: Path,
    ticket_id_text: str,
    *,
    active_loaded: Any = 0,
    active_batch_size: Any = 24,
    history_loaded: Any = 0,
    history_batch_size: Any = 12,
    include_test_data: bool = True,
    focus_node_ids: Any = None,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    extra_active_loaded = _normalize_history_loaded(active_loaded)
    active_batch = _normalize_positive_int(
        active_batch_size,
        field="active_batch_size",
        default=24,
        minimum=1,
        maximum=200,
    )
    extra_loaded = _normalize_history_loaded(history_loaded)
    batch_size = _normalize_positive_int(
        history_batch_size,
        field="history_batch_size",
        default=12,
        minimum=1,
        maximum=50,
    )
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
        include_serialized_nodes=False,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    focus_node_id_set = {
        safe_token(str(item or ""), "", 160)
        for item in list(focus_node_ids or [])
        if safe_token(str(item or ""), "", 160)
    }
    raw_nodes = [
        dict(row)
        for row in list(snapshot["nodes"] or [])
        if not focus_node_id_set or str((row or {}).get("node_id") or "").strip() in focus_node_id_set
    ]
    completed_rows = _assignment_sort_completed_rows(
        [
            row
            for row in raw_nodes
            if _assignment_node_status_text(row) in {"succeeded", "failed"}
        ]
    )
    active_rows = _assignment_sort_active_rows(
        [
            row
            for row in raw_nodes
            if _assignment_node_status_text(row) not in {"succeeded", "failed"}
        ]
    )
    base_active = active_batch
    base_recent = 12
    visible_active = active_rows[: min(len(active_rows), base_active + extra_active_loaded)]
    visible_completed = completed_rows[: min(len(completed_rows), base_recent + extra_loaded)]
    visible_ids = {
        str(row.get("node_id") or "").strip()
        for row in visible_active + visible_completed
        if str(row.get("node_id") or "").strip()
    }
    visible_edges = [
        edge
        for edge in list(snapshot["edges"] or [])
        if str(edge.get("from_node_id") or "").strip() in visible_ids
        and str(edge.get("to_node_id") or "").strip() in visible_ids
    ]
    remaining_active = max(0, len(active_rows) - len(visible_active))
    remaining_completed = max(0, len(completed_rows) - len(visible_completed))
    visible_nodes = [
        _serialize_node(
            row,
            node_map_by_id=snapshot["node_map_by_id"],
            upstream_map=snapshot["upstream_map"],
            downstream_map=snapshot["downstream_map"],
        )
        for row in visible_active + visible_completed
    ]
    is_test_data = bool(snapshot["graph_row"].get("is_test_data"))
    for node in visible_nodes:
        node["is_test_data"] = is_test_data
    ordered_catalog_rows = active_rows + completed_rows
    return {
        "ticket_id": ticket_id,
        "graph": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "nodes": visible_nodes,
        "edges": visible_edges,
        "node_catalog": _assignment_build_node_catalog(ordered_catalog_rows),
        "metrics_summary": snapshot["metrics_summary"],
        "priority_rules": {
            "ui_levels": ["P0", "P1", "P2", "P3"],
            "backend_levels": [0, 1, 2, 3],
            "highest_first": True,
            "tie_breaker": "created_at_asc",
        },
        "active": {
            "base_visible_count": min(base_active, len(active_rows)),
            "loaded_extra_count": max(0, len(visible_active) - min(base_active, len(active_rows))),
            "next_active_loaded": extra_active_loaded + active_batch,
            "remaining_count": remaining_active,
            "has_more": remaining_active > 0,
            "batch_size": active_batch,
            "visible_count": len(visible_active),
            "total_count": len(active_rows),
        },
        "history": {
            "base_recent_count": min(base_recent, len(completed_rows)),
            "loaded_extra_count": max(0, len(visible_completed) - min(base_recent, len(completed_rows))),
            "next_history_loaded": extra_loaded + batch_size,
            "remaining_completed_count": remaining_completed,
            "has_more": remaining_completed > 0,
            "batch_size": batch_size,
        },
    }


def get_assignment_scheduler_state(root: Path, ticket_id_text: str, *, include_test_data: bool = True) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
        include_serialized_nodes=False,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    scheduler = snapshot["scheduler"]
    return {
        "ticket_id": ticket_id,
        "state": str(scheduler.get("state") or "").strip().lower(),
        "state_text": str(scheduler.get("state_text") or "").strip(),
        "running_agent_count": int(scheduler.get("running_agent_count") or 0),
        "system_running_agent_count": int(scheduler.get("system_running_agent_count") or 0),
        "graph_running_node_count": int(scheduler.get("graph_running_node_count") or 0),
        "system_running_node_count": int(scheduler.get("system_running_node_count") or 0),
        "global_concurrency_limit": int(scheduler.get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
        "graph_concurrency_limit": int(scheduler.get("graph_concurrency_limit") or 0),
        "effective_concurrency_limit": int(scheduler.get("effective_concurrency_limit") or 0),
        "pause_note": str(scheduler.get("pause_note") or "").strip(),
        "settings_updated_at": str(scheduler.get("settings_updated_at") or "").strip(),
    }


def get_assignment_status_detail(
    root: Path,
    ticket_id_text: str,
    *,
    node_id_text: str = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    node_id = safe_token(str(node_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    return _assignment_status_detail_payload(
        root,
        ticket_id=_assignment_resolve_graph_ticket_id(root, ticket_id),
        node_id=node_id,
        include_test_data=include_test_data,
    )
