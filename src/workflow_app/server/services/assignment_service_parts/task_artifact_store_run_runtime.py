from __future__ import annotations

from workflow_app.server.services.codex_failure_contract import (
    build_codex_failure,
    build_retry_action,
    infer_codex_failure_detail_code,
)


_ASSIGNMENT_FINALIZE_LOCK_GUARD = threading.Lock()
_ASSIGNMENT_FINALIZE_LOCKS: dict[str, threading.Lock] = {}


def _assignment_run_finalize_lock(ticket_id: str, node_id: str, run_id: str) -> threading.Lock:
    ticket_key = safe_token(str(ticket_id or ""), "", 160)
    node_key = safe_token(str(node_id or ""), "", 160)
    run_key = safe_token(str(run_id or ""), "", 160)
    if not ticket_key or not node_key or not run_key:
        return _ASSIGNMENT_FINALIZE_LOCK_GUARD
    lock_key = f"{ticket_key}:{node_key}:{run_key}"
    with _ASSIGNMENT_FINALIZE_LOCK_GUARD:
        existing = _ASSIGNMENT_FINALIZE_LOCKS.get(lock_key)
        if existing is not None:
            return existing
        created = threading.Lock()
        _ASSIGNMENT_FINALIZE_LOCKS[lock_key] = created
        return created


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


def _assignment_touch_run_heartbeat(
    root: Path,
    *,
    ticket_id: str,
    run_id: str,
    heartbeat_at: str,
) -> None:
    run_record = _assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    if not run_record:
        return
    current_status = str(run_record.get("status") or "").strip().lower()
    if current_status not in {"starting", "running"}:
        return
    run_record["updated_at"] = heartbeat_at
    if not str(run_record.get("latest_event_at") or "").strip():
        run_record["latest_event_at"] = heartbeat_at
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


def _assignment_stdout_events_are_startup_only(stdout_text: str) -> bool:
    lines = [str(line or "").strip() for line in str(stdout_text or "").splitlines() if str(line or "").strip()]
    if not lines:
        return False
    allowed_types = {"thread.started", "turn.started"}
    for line in lines:
        try:
            payload = json.loads(line)
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        event_type = str(payload.get("type") or "").strip().lower()
        if event_type not in allowed_types:
            return False
    return True


def _assignment_stdout_event_error_messages(stdout_text: str) -> list[str]:
    messages: list[str] = []
    lines = [str(line or "").strip() for line in str(stdout_text or "").splitlines() if str(line or "").strip()]
    for line in lines:
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type") or "").strip().lower()
        if event_type == "error":
            message_text = str(payload.get("message") or "").strip()
            if message_text:
                messages.append(message_text)
        failed_error = payload.get("error")
        if isinstance(failed_error, dict):
            failed_message = str(failed_error.get("message") or "").strip()
            if failed_message:
                messages.append(failed_message)
    return messages


def _assignment_stream_disconnect_detected(stdout_text: str, stderr_text: str) -> bool:
    candidates = _assignment_stdout_event_error_messages(stdout_text)
    stderr_value = str(stderr_text or "").strip()
    if stderr_value:
        candidates.append(stderr_value)
    for item in candidates:
        lowered = str(item or "").strip().lower()
        if (
            "stream disconnected before completion" in lowered
            or "stream closed before response.completed" in lowered
            or "连接中断" in lowered
        ):
            return True
    return False


def _assignment_should_retry_transient_stream_disconnect_failure(
    *,
    exit_code: int,
    stdout_text: str,
    stderr_text: str,
    observed_payload: dict[str, Any],
    elapsed_seconds: float,
    attempt_number: int,
) -> bool:
    retry_limit = _assignment_transient_startup_retry_limit()
    if retry_limit <= 0 or int(attempt_number or 0) > retry_limit:
        return False
    if int(exit_code or 0) == 0:
        return False
    if bool(observed_payload):
        return False
    if float(elapsed_seconds or 0.0) > float(_assignment_transient_startup_retry_max_seconds()):
        return False
    return _assignment_stream_disconnect_detected(stdout_text, stderr_text)


def _assignment_should_retry_transient_startup_failure(
    *,
    exit_code: int,
    stdout_text: str,
    stderr_text: str,
    agent_message_count: int,
    observed_payload: dict[str, Any],
    elapsed_seconds: float,
    attempt_number: int,
) -> bool:
    retry_limit = _assignment_transient_startup_retry_limit()
    if retry_limit <= 0 or int(attempt_number or 0) > retry_limit:
        return False
    if int(exit_code or 0) == 0:
        return False
    if int(agent_message_count or 0) > 0 or bool(observed_payload):
        return False
    if float(elapsed_seconds or 0.0) > float(_assignment_transient_startup_retry_max_seconds()):
        return False
    stderr_value = str(stderr_text or "").strip()
    if stderr_value and stderr_value != "^C":
        return False
    stdout_value = str(stdout_text or "").strip()
    if not stdout_value:
        return stderr_value in {"", "^C"}
    return _assignment_stdout_events_are_startup_only(stdout_value)


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
        _kill_assignment_run_process(run_id, provider_pid=int(run.get("provider_pid") or 0))
        cancelled.append(run_id)
    return cancelled


def _assignment_system_running_state(root: Path, *, include_test_data: bool) -> dict[str, Any]:
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
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
    suppress_followup_dispatch: bool = False,
) -> None:
    with _assignment_run_finalize_lock(ticket_id, node_id, run_id):
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
        current_node_status = str(node_record.get("status") or "").strip().lower()
        if current_run_status in {"succeeded", "failed"} and current_node_status == current_run_status:
            return
        if current_run_status == "cancelled":
            _kill_assignment_run_process(run_id, provider_pid=run_record.get("provider_pid"))
            run_record["latest_event"] = _assignment_cancelled_run_final_message(run_record)
            run_record["latest_event_at"] = now_text
            run_record["exit_code"] = int(exit_code or 0)
            run_record["finished_at"] = now_text
            run_record["updated_at"] = now_text
            run_record["codex_failure"] = {}
            _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
            _assignment_append_workspace_memory_with_audit(
                root,
                ticket_id=ticket_id,
                node_record=node_record,
                run_id=run_id,
                workspace_path_text=workspace_path_text,
                exit_code=exit_code,
                result_ref=result_ref,
                summary_text=str(run_record.get("latest_event") or "").strip() or "执行已取消",
                artifact_paths=list(node_record.get("artifact_paths") or []),
                warnings=[],
                appended_at=now_text,
                target_status="cancelled",
            )
            return
        success = int(exit_code or 0) == 0 and not str(failure_message or "").strip()
        upgrade_request_result: dict[str, Any] = {}
        memory_summary_text = ""
        memory_artifact_paths: list[str] = []
        memory_warning_items: list[Any] = []
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
            memory_summary_text = str(result_payload.get("result_summary") or "").strip() or "执行完成"
            memory_artifact_paths = list(node_record.get("artifact_paths") or [])
            memory_warning_items = list(result_payload.get("warnings") or [])
            try:
                schedule_result = _assignment_queue_self_iteration_schedule(
                    root,
                    task_record=task_record,
                    node_record=node_record,
                    result_summary=str(result_payload.get("result_summary") or "").strip() or "执行完成",
                    success=True,
                )
                if bool(schedule_result.get("queued")):
                    _assignment_write_audit_entry(
                        root,
                        ticket_id=ticket_id,
                        node_id=node_id,
                        action="schedule_self_iteration",
                        operator="assignment-executor",
                        reason="queued next self-iteration schedule",
                        target_status="succeeded",
                        detail=schedule_result,
                        created_at=now_text,
                    )
            except Exception:
                pass
        else:
            failure_base_text = str(
                failure_message or _short_assignment_text(stderr_text, 500) or "assignment execution failed"
            ).strip()
            result_summary_text = str(result_payload.get("result_summary") or "").strip()
            result_markdown_text = str(result_payload.get("artifact_markdown") or "").strip()
            preserve_result_ref = _assignment_result_payload_has_meaningful_content(result_payload) and (
                result_summary_text != failure_base_text
                or bool(result_markdown_text)
                or bool(list(result_payload.get("artifact_files") or []))
                or bool(list(result_payload.get("warnings") or []))
            )
            failure_text = _normalize_text(
                (
                    _assignment_failure_message_with_result_context(
                        failure_base_text,
                        result_payload=result_payload,
                    )
                    if preserve_result_ref
                    else failure_base_text
                ),
                field="failure_reason",
                required=True,
                max_len=1000,
            )
            node_record["status"] = "failed"
            node_record["status_text"] = _node_status_text("failed")
            node_record["completed_at"] = now_text
            node_record["success_reason"] = ""
            node_record["result_ref"] = result_ref if preserve_result_ref else ""
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
            memory_summary_text = failure_text
            memory_artifact_paths = list(node_record.get("artifact_paths") or [])
            memory_warning_items = list(result_payload.get("warnings") or []) if preserve_result_ref else []
            try:
                schedule_result = _assignment_queue_self_iteration_schedule(
                    root,
                    task_record=task_record,
                    node_record=node_record,
                    result_summary=failure_text,
                    success=False,
                )
                if bool(schedule_result.get("queued")):
                    _assignment_write_audit_entry(
                        root,
                        ticket_id=ticket_id,
                        node_id=node_id,
                        action="schedule_self_iteration",
                        operator="assignment-executor",
                        reason="queued next self-iteration schedule after failure",
                        target_status="failed",
                        detail=schedule_result,
                        created_at=now_text,
                    )
            except Exception:
                pass
        _assignment_append_workspace_memory_with_audit(
            root,
            ticket_id=ticket_id,
            node_record=node_record,
            run_id=run_id,
            workspace_path_text=workspace_path_text,
            exit_code=exit_code,
            result_ref=result_ref,
            summary_text=memory_summary_text,
            artifact_paths=memory_artifact_paths,
            warnings=memory_warning_items,
            appended_at=now_text,
            target_status=str(node_record.get("status") or "").strip().lower() or ("succeeded" if success else "failed"),
        )
        try:
            upgrade_request_result = _assignment_maybe_request_prod_upgrade_after_finalize(
                root,
                task_record=task_record,
                node_record=node_record,
            )
            if bool(upgrade_request_result.get("requested")):
                _assignment_write_audit_entry(
                    root,
                    ticket_id=ticket_id,
                    node_id=node_id,
                    action="request_prod_upgrade",
                    operator="assignment-executor",
                    reason="queued prod upgrade after self-iteration finalize",
                    target_status=str(node_record.get("status") or "").strip().lower() or "succeeded",
                    detail=upgrade_request_result,
                    created_at=now_text,
                )
        except Exception:
            upgrade_request_result = {}
        _assignment_finalize_followup_dispatch(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            run_id=run_id,
            target_status=str(node_record.get("status") or "").strip().lower() or ("succeeded" if success else "failed"),
            suppress_dispatch=bool(upgrade_request_result.get("suppress_dispatch")) or bool(suppress_followup_dispatch),
        )


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
    activity_lock = threading.Lock()
    last_activity_monotonic = 0.0

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

    def mark_activity(activity_monotonic: float | None = None) -> None:
        nonlocal last_activity_monotonic
        stamp = float(activity_monotonic or time.monotonic())
        with activity_lock:
            last_activity_monotonic = stamp

    def last_activity_monotonic_value() -> float:
        with activity_lock:
            return float(last_activity_monotonic or 0.0)

    def read_stream(name: str, pipe: Any, collector: list[str]) -> None:
        if pipe is None:
            return
        try:
            for line in iter(pipe.readline, ""):
                if line == "":
                    break
                mark_activity()
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
    attempt_number = 0
    while True:
        attempt_number += 1
        exit_code = 1
        failure_message = ""
        forced_result_short_circuit = False
        with observed_result_lock:
            observed_result_payload = {}
            observed_turn_completed_at = 0.0
        attempt_started_at = iso_ts(now_local())
        attempt_started_monotonic = time.monotonic()
        mark_activity(attempt_started_monotonic)
        last_heartbeat_monotonic = attempt_started_monotonic
        attempt_stdout_index = len(stdout_chunks)
        attempt_stderr_index = len(stderr_chunks)
        attempt_agent_message_index = len(agent_messages)
        if run_record:
            run_record["status"] = "running"
            run_record["latest_event"] = "Provider 已启动，执行中。"
            run_record["latest_event_at"] = attempt_started_at
            run_record["updated_at"] = attempt_started_at
            _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)
        _append_assignment_run_event(
            files["events"],
            event_type="provider_start",
            message="Provider 已启动。",
            created_at=attempt_started_at,
            detail={
                "command_summary": command_summary,
                "attempt": attempt_number,
            },
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
                _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)
            _register_assignment_run_process(run_id, proc)
            assert proc.stdin is not None
            proc.stdin.write(prompt_text)
            proc.stdin.write("\n")
            proc.stdin.close()
            t_out = threading.Thread(target=read_stream, args=("stdout", proc.stdout, stdout_chunks), daemon=True)
            t_err = threading.Thread(target=read_stream, args=("stderr", proc.stderr, stderr_chunks), daemon=True)
            t_out.start()
            t_err.start()
            execution_timeout_s = _assignment_execution_activity_timeout_s()
            final_result_grace_s = _assignment_final_result_exit_grace_seconds()
            while True:
                try:
                    exit_code = int(proc.wait(timeout=1) or 0)
                    break
                except subprocess.TimeoutExpired:
                    now_monotonic = time.monotonic()
                    if (now_monotonic - last_heartbeat_monotonic) >= float(DEFAULT_ASSIGNMENT_EVENT_STREAM_KEEPALIVE_S):
                        heartbeat_at = iso_ts(now_local())
                        _assignment_touch_run_heartbeat(
                            root,
                            ticket_id=ticket_id,
                            run_id=run_id,
                            heartbeat_at=heartbeat_at,
                        )
                        last_heartbeat_monotonic = now_monotonic
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
                    last_activity_at = last_activity_monotonic_value()
                    inactivity_age_s = _assignment_execution_activity_age_seconds(
                        last_activity_monotonic=last_activity_at,
                        now_monotonic=now_monotonic,
                    )
                    if _assignment_execution_activity_timed_out(
                        last_activity_monotonic=last_activity_at,
                        now_monotonic=now_monotonic,
                        timeout_s=execution_timeout_s,
                    ):
                        failure_message = _assignment_execution_timeout_message(execution_timeout_s)
                        _append_assignment_run_event(
                            files["events"],
                            event_type="execution_timeout",
                            message="执行超时，已终止 provider。",
                            created_at=iso_ts(now_local()),
                            detail={
                                "timeout_seconds": execution_timeout_s,
                                "inactivity_seconds": round(inactivity_age_s, 3),
                            },
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
        attempt_stdout_text = "".join(stdout_chunks[attempt_stdout_index:])
        attempt_stderr_text = "".join(stderr_chunks[attempt_stderr_index:])
        observed_payload = last_observed_result_payload()
        attempt_elapsed_seconds = time.monotonic() - attempt_started_monotonic
        stream_disconnected = _assignment_stream_disconnect_detected(
            attempt_stdout_text,
            attempt_stderr_text,
        )
        if exit_code != 0 and not failure_message:
            if stream_disconnected:
                failure_message = "Codex 连接中断。"
            else:
                failure_message = (
                    _short_assignment_text(attempt_stderr_text, 500)
                    or f"assignment execution failed with exit={exit_code}"
                )
        current_run_status = str(
            (_assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id) or {}).get("status") or ""
        ).strip().lower()
        if current_run_status == "cancelled":
            break
        if _assignment_should_retry_transient_stream_disconnect_failure(
            exit_code=exit_code,
            stdout_text=attempt_stdout_text,
            stderr_text=attempt_stderr_text,
            observed_payload=observed_payload,
            elapsed_seconds=attempt_elapsed_seconds,
            attempt_number=attempt_number,
        ):
            _append_assignment_run_event(
                files["events"],
                event_type="provider_retry",
                message="Provider 连接中断，已自动重试。",
                created_at=iso_ts(now_local()),
                detail={
                    "attempt": attempt_number,
                    "next_attempt": attempt_number + 1,
                    "exit_code": int(exit_code or 0),
                    "reason_code": "codex_stream_disconnected",
                },
            )
            _assignment_touch_run_latest_event(
                root,
                ticket_id=ticket_id,
                run_id=run_id,
                latest_event="Provider 连接中断，自动重试中。",
                latest_event_at=iso_ts(now_local()),
            )
            continue
        if _assignment_should_retry_transient_startup_failure(
            exit_code=exit_code,
            stdout_text=attempt_stdout_text,
            stderr_text=attempt_stderr_text,
            agent_message_count=len(agent_messages) - attempt_agent_message_index,
            observed_payload=observed_payload,
            elapsed_seconds=attempt_elapsed_seconds,
            attempt_number=attempt_number,
        ):
            _append_assignment_run_event(
                files["events"],
                event_type="provider_retry",
                message="Provider 启动后瞬时失败，已自动重试。",
                created_at=iso_ts(now_local()),
                detail={
                    "attempt": attempt_number,
                    "next_attempt": attempt_number + 1,
                    "exit_code": int(exit_code or 0),
                    "stderr": _short_assignment_text(attempt_stderr_text, 300),
                },
            )
            _assignment_touch_run_latest_event(
                root,
                ticket_id=ticket_id,
                run_id=run_id,
                latest_event="Provider 启动后瞬时失败，自动重试中。",
                latest_event_at=iso_ts(now_local()),
            )
            continue
        break
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
        has_meaningful_result = _assignment_result_payload_has_meaningful_content(result_payload)
        if has_meaningful_result:
            failure_message = _assignment_failure_message_with_result_context(
                failure_message,
                result_payload=result_payload,
            )
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
