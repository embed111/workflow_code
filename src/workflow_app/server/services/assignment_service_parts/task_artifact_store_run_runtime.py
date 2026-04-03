from __future__ import annotations

from workflow_app.server.services.codex_failure_contract import (
    build_codex_failure,
    build_retry_action,
    infer_codex_failure_detail_code,
)


def _assignment_active_run_record(root: Path, *, ticket_id: str, node_id: str) -> dict[str, Any]:
    for row in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        if str(row.get("status") or "").strip().lower() in {"starting", "running"}:
            return dict(row)
    return {}


def _assignment_touch_run_latest_event(
    root: Path,
    *,
    ticket_id: str,
    run_id: str,
    latest_event: str,
    latest_event_at: str,
) -> None:
    run_record = _assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    if not run_record:
        return
    current_status = str(run_record.get("status") or "").strip().lower()
    if current_status not in {"starting", "running"}:
        return
    run_record["latest_event"] = _short_assignment_text(latest_event, 1000) or "执行中"
    run_record["latest_event_at"] = latest_event_at
    run_record["updated_at"] = latest_event_at
    _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)


def _assignment_execution_codex_failure(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    run_id: str,
    run_record: dict[str, Any],
    exit_code: int,
    stderr_text: str,
    failure_message: str,
    failed_at: str,
) -> dict[str, Any]:
    fallback_code = f"codex_exec_failed_exit_{int(exit_code or 0)}" if int(exit_code or 0) > 0 else "assignment_execution_failed"
    detail_code = infer_codex_failure_detail_code(
        str(failure_message or stderr_text or "").strip(),
        fallback=fallback_code,
    )
    attempt_count = len(_assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id))
    trace_refs = {
        "prompt": str(run_record.get("prompt_ref") or "").strip(),
        "stdout": str(run_record.get("stdout_ref") or "").strip(),
        "stderr": str(run_record.get("stderr_ref") or "").strip(),
        "result": str(run_record.get("result_ref") or "").strip(),
    }
    return build_codex_failure(
        feature_key="assignment_node_execution",
        attempt_id=run_id,
        attempt_count=max(1, int(attempt_count or 0)),
        failure_detail_code=detail_code,
        failure_message=str(failure_message or stderr_text or "").strip(),
        retry_action=build_retry_action(
            "rerun_assignment_node",
            payload={
                "ticket_id": str(ticket_id or "").strip(),
                "node_id": str(node_id or "").strip(),
                "run_id": str(run_id or "").strip(),
            },
        ),
        trace_refs=trace_refs,
        failed_at=failed_at,
    )


def _assignment_cancelled_run_final_message(run_record: dict[str, Any]) -> str:
    existing = str(run_record.get("latest_event") or "").strip()
    if not existing:
        return "执行已取消，后台结果不再回写节点状态。"
    if "后台结果不再回写节点状态" in existing:
        return existing
    if existing.endswith("。"):
        return existing[:-1] + "，后台结果不再回写节点状态。"
    return existing + "，后台结果不再回写节点状态。"


def _assignment_cancel_active_runs(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    reason: str,
    now_text: str,
) -> list[str]:
    cancelled: list[str] = []
    for run in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        status = str(run.get("status") or "").strip().lower()
        if status not in {"starting", "running"}:
            continue
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            continue
        run["status"] = "cancelled"
        run["latest_event"] = reason
        run["latest_event_at"] = now_text
        run["finished_at"] = now_text
        run["updated_at"] = now_text
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run)
        _kill_assignment_run_process(run_id)
        cancelled.append(run_id)
    return cancelled


def _resolve_assignment_artifact_source_paths(
    workspace_path: Path | str,
    artifact_files: list[Any],
) -> list[Path]:
    workspace_text = str(workspace_path or "").strip()
    if not workspace_text:
        return []
    base = Path(workspace_text).resolve(strict=False)
    if not base.exists() or not base.is_dir():
        return []
    resolved_paths: list[Path] = []
    seen: set[str] = set()
    for raw in list(artifact_files or []):
        text = str(raw or "").strip()
        if not text:
            continue
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = (base / text).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)
        if not path_in_scope(candidate, base):
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        key = candidate.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        resolved_paths.append(candidate)
    return resolved_paths


def _copy_assignment_artifact_source_files(
    root: Path,
    *,
    node: dict[str, Any],
    artifact_source_paths: list[Path],
) -> list[str]:
    copied_paths: list[str] = []
    seen: set[str] = set()
    for source_path in list(artifact_source_paths or []):
        if not isinstance(source_path, Path) or not source_path.exists() or not source_path.is_file():
            continue
        target_paths = _node_artifact_file_paths(
            root,
            node,
            file_name=source_path.name,
        )
        for target_path in target_paths:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            text = target_path.as_posix()
            if text in seen:
                continue
            seen.add(text)
            copied_paths.append(text)
    return copied_paths


def _copy_assignment_delivery_inbox_source_files(
    root: Path,
    *,
    node: dict[str, Any],
    artifact_source_paths: list[Path],
) -> list[str]:
    copied_paths: list[str] = []
    seen: set[str] = set()
    for source_path in list(artifact_source_paths or []):
        if not isinstance(source_path, Path) or not source_path.exists() or not source_path.is_file():
            continue
        target_paths = _node_delivery_inbox_file_paths(
            root,
            node,
            file_name=source_path.name,
        )
        for target_path in target_paths:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            text = target_path.as_posix()
            if text in seen:
                continue
            seen.add(text)
            copied_paths.append(text)
    return copied_paths


def _write_assignment_delivery_info_file(
    root: Path,
    *,
    node: dict[str, Any],
    delivered_at: str,
    operator: str,
    artifact_label: str,
    delivery_note: str,
    canonical_artifact_paths: list[str],
    delivery_inbox_paths: list[str],
) -> str:
    info_path = _node_delivery_info_path(root, node)
    payload = {
        "record_type": "assignment_delivery_info",
        "schema_version": ASSIGNMENT_TASK_SCHEMA_VERSION,
        "ticket_id": str(node.get("ticket_id") or "").strip(),
        "node_id": str(node.get("node_id") or "").strip(),
        "task_name": str(node.get("node_name") or "").strip(),
        "artifact_label": str(artifact_label or "").strip(),
        "delivery_note": str(delivery_note or "").strip(),
        "delivered_at": str(delivered_at or "").strip(),
        "delivery_mode": str(node.get("delivery_mode") or "none").strip().lower() or "none",
        "delivery_receiver_agent_id": str(node.get("delivery_receiver_agent_id") or "").strip(),
        "delivery_receiver_agent_name": str(node.get("delivery_receiver_agent_name") or "").strip(),
        "delivery_target_agent_id": _node_delivery_target_agent_id(node),
        "delivery_target_agent_name": _node_delivery_target_agent_name(node),
        "delivery_inbox_relative_path": _node_delivery_inbox_relative_path(node),
        "delivery_inbox_relative_paths": _node_delivery_inbox_relative_paths(node, delivery_inbox_paths),
        "delivered_by_agent_id": str(node.get("assigned_agent_id") or "").strip(),
        "delivered_by_agent_name": str(node.get("assigned_agent_name") or node.get("assigned_agent_id") or "").strip(),
        "delivery_recorded_by": str(operator or "").strip(),
        "canonical_artifact_paths": list(canonical_artifact_paths or []),
        "delivery_inbox_paths": list(delivery_inbox_paths or []),
    }
    _assignment_write_json(info_path, payload)
    return info_path.as_posix()


def _cleanup_assignment_artifact_source_files(
    workspace_path: Path | str,
    artifact_source_paths: list[Path],
) -> tuple[list[str], list[str]]:
    workspace_text = str(workspace_path or "").strip()
    if not workspace_text:
        return [], []
    base = Path(workspace_text).resolve(strict=False)
    if not base.exists() or not base.is_dir():
        return [], []
    cleaned_paths: list[str] = []
    cleanup_errors: list[str] = []
    seen: set[str] = set()
    for source_path in list(artifact_source_paths or []):
        if not isinstance(source_path, Path):
            continue
        candidate = source_path.resolve(strict=False)
        candidate_text = candidate.as_posix()
        if candidate_text.lower() in seen:
            continue
        seen.add(candidate_text.lower())
        if not path_in_scope(candidate, base):
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            candidate.unlink()
            cleaned_paths.append(candidate_text)
        except Exception as exc:
            cleanup_errors.append(f"{candidate_text}: {exc}")
            continue
        parent = candidate.parent
        while parent != base:
            try:
                if not path_in_scope(parent, base):
                    break
                parent.rmdir()
            except OSError:
                break
            except Exception as exc:
                cleanup_errors.append(f"{parent.as_posix()}: {exc}")
                break
            parent = parent.parent
    return cleaned_paths, cleanup_errors


def _deliver_assignment_artifact_locked(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    operator_text: str,
    artifact_label: str,
    delivery_note: str,
    artifact_body: str,
    now_text: str,
    artifact_source_paths: list[Path] | None = None,
    source_workspace_path: Path | str = "",
) -> tuple[dict[str, Any], dict[str, Any], list[str], str]:
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=True,
        reconcile_running=False,
    )
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
    artifact_file_paths = _node_artifact_file_paths(root, selected_node)
    artifact_paths: list[str] = []
    delivery_inbox_paths: list[str] = []
    payload = artifact_body or _artifact_delivery_markdown(
        selected_node,
        delivered_at=now_text,
        operator=operator_text,
        artifact_label=artifact_label,
        delivery_note=delivery_note,
    )
    payload = _artifact_text_to_html_document(
        payload,
        title=artifact_label or _artifact_label_text(selected_node),
    )
    copied_source_artifacts = _copy_assignment_artifact_source_files(
        root,
        node=selected_node,
        artifact_source_paths=list(artifact_source_paths or []),
    )
    copied_delivery_inbox_artifacts = _copy_assignment_delivery_inbox_source_files(
        root,
        node=selected_node,
        artifact_source_paths=list(artifact_source_paths or []),
    )
    cleaned_source_paths, cleanup_errors = _cleanup_assignment_artifact_source_files(
        source_workspace_path,
        list(artifact_source_paths or []),
    )
    artifact_paths.extend(copied_source_artifacts)
    delivery_inbox_paths.extend(copied_delivery_inbox_artifacts)
    if not artifact_paths:
        artifact_file_paths = _node_artifact_file_paths(
            root,
            selected_node,
            preferred_extension=_artifact_file_extension_from_body(payload),
        )
        for path in artifact_file_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            artifact_paths.append(path.as_posix())
        for path in _node_delivery_inbox_file_paths(
            root,
            selected_node,
            preferred_extension=_artifact_file_extension_from_body(payload),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            delivery_inbox_paths.append(path.as_posix())
    else:
        artifact_file_paths = [Path(item) for item in copied_source_artifacts]
    delivery_info_path = _write_assignment_delivery_info_file(
        root,
        node=selected_node,
        delivered_at=now_text,
        operator=operator_text,
        artifact_label=artifact_label,
        delivery_note=delivery_note,
        canonical_artifact_paths=artifact_paths,
        delivery_inbox_paths=delivery_inbox_paths,
    )
    artifact_structure_paths = _write_artifact_structure_files(
        root,
        node=selected_node,
        artifact_file_paths=artifact_file_paths,
        delivered_at=now_text,
        operator=operator_text,
    )
    for row in node_records:
        if str(row.get("node_id") or "").strip() != node_id:
            continue
        row["artifact_delivery_status"] = "delivered"
        row["artifact_delivery_status_text"] = _artifact_delivery_status_text("delivered")
        row["artifact_delivered_at"] = now_text
        row["artifact_paths"] = artifact_paths
        row["updated_at"] = now_text
        break
    task_record["updated_at"] = now_text
    _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        action="deliver_artifact",
        operator=operator_text,
        reason=delivery_note or "deliver assignment artifact",
        target_status="delivered",
        detail={
            "artifact_label": artifact_label,
            "delivery_mode": str(selected_node.get("delivery_mode") or "none").strip().lower(),
            "delivery_receiver_agent_id": str(selected_node.get("delivery_receiver_agent_id") or "").strip(),
            "delivery_target_agent_id": _node_delivery_target_agent_id(selected_node),
            "delivery_target_agent_name": _node_delivery_target_agent_name(selected_node),
            "delivery_inbox_dir": _node_delivery_inbox_dir(root, selected_node).as_posix(),
            "delivery_inbox_relative_path": _node_delivery_inbox_relative_path(selected_node),
            "delivery_inbox_paths": delivery_inbox_paths,
            "delivery_info_path": delivery_info_path,
            "artifact_paths": artifact_paths,
            "artifact_structure_paths": artifact_structure_paths,
            "source_workspace_cleanup": {
                "cleaned_paths": cleaned_source_paths,
                "cleanup_errors": cleanup_errors,
            },
        },
        created_at=now_text,
    )
    updated_snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=True,
        reconcile_running=False,
    )
    updated_node = next(
        (
            item
            for item in list(updated_snapshot["serialized_nodes"] or [])
            if str(item.get("node_id") or "").strip() == node_id
        ),
        {},
    )
    return updated_snapshot["graph_row"], updated_node, artifact_paths, audit_id


def _assignment_system_running_state(root: Path, *, include_test_data: bool) -> dict[str, Any]:
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    if not active_run_ids:
        return {
            "running_agents": set(),
            "running_node_count": 0,
        }
    now_dt = now_local()
    running_agents: set[str] = set()
    running_node_keys: set[tuple[str, str]] = set()
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for ticket_id in _assignment_list_ticket_ids_lightweight(root):
        task_record = _assignment_load_task_record_lightweight(root, ticket_id)
        if not task_record:
            continue
        if not _assignment_task_visible(task_record, include_test_data=include_test_data):
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            ticket_id,
            ticket_record=task_record,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        live_node_ids: set[str] = set()
        for run in _assignment_load_run_records(root, ticket_id=ticket_id):
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
                running_node_keys.add((ticket_id, node_id))
        if not live_node_ids:
            continue
        for node_id in live_node_ids:
            node = _assignment_read_json(_assignment_node_record_path(root, ticket_id, node_id))
            agent_id = str(node.get("assigned_agent_id") or "").strip()
            if agent_id:
                running_agents.add(agent_id)
    return {
        "running_agents": running_agents,
        "running_node_count": len(running_node_keys),
    }


def _assignment_dispatch_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        dict(node)
        for node in list(snapshot.get("nodes") or [])
        if str(node.get("status") or "").strip().lower() == "ready"
    ]
    rows.sort(
        key=lambda item: (
            int(item.get("priority") or 0),
            str(item.get("created_at") or ""),
            str(item.get("node_id") or ""),
        )
    )
    return rows


def _prepare_assignment_execution_run(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    now_text: str,
) -> dict[str, Any]:
    _ensure_assignment_support_tables(root)
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


def _finalize_assignment_execution_run(
    root: Path,
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    exit_code: int,
    stdout_text: str,
    stderr_text: str,
    result_payload: dict[str, Any],
    failure_message: str,
) -> None:
    now_text = iso_ts(now_local())
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=True,
        reconcile_running=False,
    )
    task_record = dict(snapshot["graph_row"])
    node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
    node_record = next(
        (
            item
            for item in node_records
            if str(item.get("node_id") or "").strip() == node_id
            and str(item.get("record_state") or "active").strip().lower() != "deleted"
        ),
        {},
    )
    if not node_record:
        return
    run_record = _assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    if not run_record:
        return
    result_ref = str(run_record.get("result_ref") or "").strip()
    workspace_path_text = str(run_record.get("workspace_path") or "").strip()
    current_run_status = str(run_record.get("status") or "").strip().lower()
    if current_run_status == "cancelled":
        run_record["latest_event"] = _assignment_cancelled_run_final_message(run_record)
        run_record["latest_event_at"] = now_text
        run_record["exit_code"] = int(exit_code or 0)
        run_record["finished_at"] = now_text
        run_record["updated_at"] = now_text
        run_record["codex_failure"] = {}
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
        return
    success = int(exit_code or 0) == 0 and not str(failure_message or "").strip()
    if success:
        markdown_text = str(result_payload.get("artifact_markdown") or "").strip()
        artifact_source_paths = _resolve_assignment_artifact_source_paths(
            workspace_path_text,
            list(result_payload.get("artifact_files") or []),
        )
        delivered_graph, delivered_node, artifact_paths, _artifact_audit_id = _deliver_assignment_artifact_locked(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            operator_text="assignment-executor",
            artifact_label=str(result_payload.get("artifact_label") or "").strip() or "任务产物",
            delivery_note=str(result_payload.get("result_summary") or "").strip(),
            artifact_body=markdown_text,
            now_text=now_text,
            artifact_source_paths=artifact_source_paths,
            source_workspace_path=workspace_path_text,
        )
        task_record = dict(delivered_graph or task_record)
        node_records = _assignment_load_node_records(root, ticket_id, include_deleted=True)
        node_record = next(
            (
                item
                for item in node_records
                if str(item.get("node_id") or "").strip() == node_id
                and str(item.get("record_state") or "active").strip().lower() != "deleted"
            ),
            node_record,
        )
        node_record["status"] = "succeeded"
        node_record["status_text"] = _node_status_text("succeeded")
        node_record["completed_at"] = now_text
        node_record["success_reason"] = str(result_payload.get("result_summary") or "").strip() or "执行完成"
        node_record["result_ref"] = result_ref
        node_record["failure_reason"] = ""
        node_record["updated_at"] = now_text
        node_record["artifact_paths"] = list(delivered_node.get("artifact_paths") or artifact_paths)
        task_record["updated_at"] = now_text
        task_record, node_records, _changed = _assignment_recompute_task_state(
            root,
            task_record=task_record,
            node_records=node_records,
            reconcile_running=False,
        )
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
        _assignment_write_audit_entry(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            action="execution_succeeded",
            operator="assignment-executor",
            reason=str(result_payload.get("result_summary") or "").strip() or "assignment execution succeeded",
            target_status="succeeded",
            detail={
                "run_id": run_id,
                "result_ref": result_ref,
                "artifact_paths": list(node_record.get("artifact_paths") or []),
            },
            created_at=now_text,
        )
        run_record["status"] = "succeeded"
        run_record["latest_event"] = "执行完成并已自动回写结果。"
        run_record["latest_event_at"] = now_text
        run_record["exit_code"] = int(exit_code or 0)
        run_record["finished_at"] = now_text
        run_record["updated_at"] = now_text
        run_record["codex_failure"] = {}
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    else:
        failure_text = _normalize_text(
            failure_message or _short_assignment_text(stderr_text, 500) or "assignment execution failed",
            field="failure_reason",
            required=True,
            max_len=1000,
        )
        node_record["status"] = "failed"
        node_record["status_text"] = _node_status_text("failed")
        node_record["completed_at"] = now_text
        node_record["success_reason"] = ""
        node_record["result_ref"] = ""
        node_record["failure_reason"] = failure_text
        node_record["updated_at"] = now_text
        task_record["updated_at"] = now_text
        task_record, node_records, _changed = _assignment_recompute_task_state(
            root,
            task_record=task_record,
            node_records=node_records,
            reconcile_running=False,
        )
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
        _assignment_write_audit_entry(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            action="execution_failed",
            operator="assignment-executor",
            reason=failure_text,
            target_status="failed",
            detail={"run_id": run_id, "result_ref": result_ref},
            created_at=now_text,
        )
        run_record["status"] = "failed"
        run_record["latest_event"] = failure_text
        run_record["latest_event_at"] = now_text
        run_record["exit_code"] = int(exit_code or 0)
        run_record["finished_at"] = now_text
        run_record["updated_at"] = now_text
        run_record["codex_failure"] = _assignment_execution_codex_failure(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            run_id=run_id,
            run_record=run_record,
            exit_code=exit_code,
            stderr_text=stderr_text,
            failure_message=failure_text,
            failed_at=now_text,
        )
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    try:
        dispatch_assignment_next(
            root,
            ticket_id_text=ticket_id,
            operator="assignment-executor",
            include_test_data=True,
        )
    except Exception:
        pass


def _assignment_execution_worker(
    root: Path,
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    workspace_path: Path,
    command: list[str],
    command_summary: str,
    prompt_text: str,
) -> None:
    files = _assignment_run_file_paths(root, ticket_id, run_id)
    started_at = iso_ts(now_local())
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    agent_messages: list[str] = []
    exit_code = 1
    failure_message = ""
    observed_result_lock = threading.Lock()
    observed_result_payload: dict[str, Any] = {}
    observed_turn_completed_at = 0.0
    forced_result_short_circuit = False

    def record_observed_result(payload: dict[str, Any]) -> None:
        nonlocal observed_result_payload
        if not isinstance(payload, dict) or not payload:
            return
        with observed_result_lock:
            observed_result_payload = dict(payload)

    def mark_observed_turn_completed() -> None:
        nonlocal observed_turn_completed_at
        with observed_result_lock:
            if observed_result_payload:
                observed_turn_completed_at = time.monotonic()

    def last_observed_result_payload() -> dict[str, Any]:
        with observed_result_lock:
            return dict(observed_result_payload)

    def observed_turn_completed_at_monotonic() -> float:
        with observed_result_lock:
            return float(observed_turn_completed_at or 0.0)

    def read_stream(name: str, pipe: Any, collector: list[str]) -> None:
        if pipe is None:
            return
        try:
            for line in iter(pipe.readline, ""):
                if line == "":
                    break
                collector.append(line)
                _append_assignment_run_text(files[name], line)
                message_text = line.rstrip("\n")
                detail: dict[str, Any] = {}
                event_type = name
                if name == "stdout":
                    try:
                        event = json.loads(message_text)
                    except Exception:
                        event = None
                    if isinstance(event, dict):
                        event_type = str(event.get("type") or "stdout_event").strip() or "stdout_event"
                        agent_message_text = _assignment_extract_agent_message_text(event)
                        message_text = agent_message_text or str(event.get("message") or message_text)
                        if message_text and agent_message_text:
                            agent_messages.append(message_text)
                            payload_candidates = _assignment_extract_json_objects(message_text)
                            if payload_candidates:
                                record_observed_result(payload_candidates[-1])
                        if event_type == "turn.completed":
                            mark_observed_turn_completed()
                        detail = event
                created_at = iso_ts(now_local())
                _append_assignment_run_event(
                    files["events"],
                    event_type=event_type,
                    message=message_text or f"{name} 输出",
                    created_at=created_at,
                    detail=detail,
                )
                _assignment_touch_run_latest_event(
                    root,
                    ticket_id=ticket_id,
                    run_id=run_id,
                    latest_event=message_text or f"{name} 输出",
                    latest_event_at=created_at,
                )
        except (OSError, ValueError):
            return

    run_record = _assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    if run_record:
        run_record["status"] = "running"
        run_record["latest_event"] = "Provider 已启动，执行中。"
        run_record["latest_event_at"] = started_at
        run_record["updated_at"] = started_at
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    _append_assignment_run_event(
        files["events"],
        event_type="provider_start",
        message="Provider 已启动。",
        created_at=started_at,
        detail={"command_summary": command_summary},
    )
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            command,
            cwd=workspace_path.as_posix(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if run_record:
            run_record["provider_pid"] = max(0, int(getattr(proc, "pid", 0) or 0))
            run_record["updated_at"] = iso_ts(now_local())
            _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
        _register_assignment_run_process(run_id, proc)
        assert proc.stdin is not None
        proc.stdin.write(prompt_text)
        proc.stdin.write("\n")
        proc.stdin.close()
        t_out = threading.Thread(target=read_stream, args=("stdout", proc.stdout, stdout_chunks), daemon=True)
        t_err = threading.Thread(target=read_stream, args=("stderr", proc.stderr, stderr_chunks), daemon=True)
        t_out.start()
        t_err.start()
        started_monotonic = time.monotonic()
        execution_timeout_s = _assignment_execution_timeout_s()
        final_result_grace_s = _assignment_final_result_exit_grace_seconds()
        while True:
            try:
                exit_code = int(proc.wait(timeout=1) or 0)
                break
            except subprocess.TimeoutExpired:
                now_monotonic = time.monotonic()
                ready_at = observed_turn_completed_at_monotonic()
                if ready_at > 0 and (now_monotonic - ready_at) >= final_result_grace_s:
                    forced_result_short_circuit = True
                    _append_assignment_run_event(
                        files["events"],
                        event_type="provider_exit_forced",
                        message="已观测到最终结果，provider 超时未退出，执行强制收敛。",
                        created_at=iso_ts(now_local()),
                        detail={"grace_seconds": final_result_grace_s},
                    )
                    _terminate_assignment_process(proc)
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        pass
                    exit_code = 0
                    break
                if (now_monotonic - started_monotonic) >= execution_timeout_s:
                    failure_message = f"assignment execution timeout after {execution_timeout_s}s"
                    _append_assignment_run_event(
                        files["events"],
                        event_type="execution_timeout",
                        message="执行超时，已终止 provider。",
                        created_at=iso_ts(now_local()),
                        detail={"timeout_seconds": execution_timeout_s},
                    )
                    _terminate_assignment_process(proc)
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        pass
                    exit_code = 124
                    break
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        if exit_code != 0 and not failure_message:
            failure_message = (
                _short_assignment_text("".join(stderr_chunks), 500)
                or f"assignment execution failed with exit={exit_code}"
            )
    except Exception as exc:
        failure_message = f"assignment execution exception: {exc}"
        stderr_chunks.append(failure_message + "\n")
    finally:
        _unregister_assignment_run_process(run_id)
        if proc is not None:
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()
            except Exception:
                pass
    stdout_text = "".join(stdout_chunks)
    stderr_text = "".join(stderr_chunks)
    fallback_text = agent_messages[-1] if agent_messages else stdout_text.strip()
    parsed_candidates: list[dict[str, Any]] = []
    for message in agent_messages:
        parsed_candidates.extend(_assignment_extract_json_objects(message))
    observed_payload = last_observed_result_payload()
    if observed_payload:
        parsed_candidates.append(observed_payload)
    if not parsed_candidates:
        parsed_candidates.extend(_assignment_extract_json_objects(stdout_text))
    result_payload = _normalize_assignment_execution_result(
        parsed_candidates[-1] if parsed_candidates else {},
        fallback_text=fallback_text,
        node={"node_id": node_id},
    )
    if forced_result_short_circuit:
        result_payload["result_summary"] = (
            str(result_payload.get("result_summary") or "").strip()
            or "执行完成，provider 已被强制收敛。"
        )
    if failure_message:
        current_summary = str(result_payload.get("result_summary") or "").strip()
        if not current_summary or current_summary == "执行完成":
            result_payload["result_summary"] = failure_message
    _write_assignment_run_json(files["result"], result_payload)
    _write_assignment_run_text(files["result_markdown"], str(result_payload.get("artifact_markdown") or "").strip())
    final_result_message = str(result_payload.get("result_summary") or "").strip() or "执行结束"
    if failure_message:
        final_result_message = failure_message
    _append_assignment_run_event(
        files["events"],
        event_type="final_result",
        message=final_result_message,
        created_at=iso_ts(now_local()),
        detail={"exit_code": exit_code},
    )
    _finalize_assignment_execution_run(
        root,
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        exit_code=exit_code,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        result_payload=result_payload,
        failure_message=failure_message,
    )
