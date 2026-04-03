

def _finalize_assignment_execution_run(
    root: Path,
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    node_snapshot: dict[str, Any],
    exit_code: int,
    stdout_text: str,
    stderr_text: str,
    result_payload: dict[str, Any],
    failure_message: str,
) -> None:
    now_text = iso_ts(now_local())
    files = _assignment_run_file_paths(root, ticket_id, run_id)
    result_ref_ui = _path_for_ui(root, files["result"])
    stdout_ref_ui = _path_for_ui(root, files["stdout"])
    stderr_ref_ui = _path_for_ui(root, files["stderr"])
    snapshot: dict[str, Any] | None = None
    success = exit_code == 0 and not failure_message
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        run_row = conn.execute(
            """
            SELECT status,latest_event
            FROM assignment_execution_runs
            WHERE run_id=?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            conn.commit()
            return
        current_run_status = _normalize_run_status(run_row["status"] or "starting")
        if current_run_status == "cancelled":
            latest_event = str(run_row["latest_event"] or "").strip()
            if not latest_event:
                latest_event = "执行已取消，后台结果不再回写节点状态。"
            elif "后台结果不再回写节点状态" not in latest_event:
                latest_event = (
                    latest_event[:-1] + "，后台结果不再回写节点状态。"
                    if latest_event.endswith("。")
                    else latest_event + "，后台结果不再回写节点状态。"
                )
            _update_assignment_execution_run(
                conn,
                run_id=run_id,
                status="cancelled",
                latest_event=latest_event,
                latest_event_at=now_text,
                exit_code=exit_code,
                stdout_ref=stdout_ref_ui,
                stderr_ref=stderr_ref_ui,
                result_ref=result_ref_ui,
                finished_at=now_text,
            )
            conn.commit()
            return
        operator_text = "assignment-executor"
        if success:
            markdown_text = str(result_payload.get("artifact_markdown") or "").strip()
            artifact_paths, _artifact_audit_id = _deliver_assignment_artifact_locked(
                root,
                conn,
                ticket_id=ticket_id,
                node_id=node_id,
                operator_text=operator_text,
                artifact_label=str(result_payload.get("artifact_label") or "").strip() or "任务产物",
                delivery_note=str(result_payload.get("result_summary") or "").strip(),
                artifact_body=markdown_text,
                now_text=now_text,
            )
            conn.execute(
                """
                UPDATE assignment_nodes
                SET status='succeeded',
                    completed_at=?,
                    success_reason=?,
                    result_ref=?,
                    failure_reason='',
                    updated_at=?
                WHERE ticket_id=? AND node_id=?
                """,
                (
                    now_text,
                    str(result_payload.get("result_summary") or "").strip() or "执行完成",
                    result_ref_ui,
                    now_text,
                    ticket_id,
                    node_id,
                ),
            )
            _recompute_graph_statuses(conn, ticket_id)
            _write_assignment_audit(
                conn,
                ticket_id=ticket_id,
                node_id=node_id,
                action="execution_succeeded",
                operator=operator_text,
                reason=str(result_payload.get("result_summary") or "").strip() or "assignment execution succeeded",
                target_status="succeeded",
                detail={
                    "run_id": run_id,
                    "result_ref": result_ref_ui,
                    "artifact_paths": artifact_paths,
                },
                created_at=now_text,
            )
            _update_assignment_execution_run(
                conn,
                run_id=run_id,
                status="succeeded",
                latest_event="执行完成并已自动回写结果。",
                latest_event_at=now_text,
                exit_code=exit_code,
                stdout_ref=stdout_ref_ui,
                stderr_ref=stderr_ref_ui,
                result_ref=result_ref_ui,
                finished_at=now_text,
            )
        else:
            failure_text = _normalize_text(
                failure_message or _short_assignment_text(stderr_text, 500) or "assignment execution failed",
                field="failure_reason",
                required=True,
                max_len=1000,
            )
            conn.execute(
                """
                UPDATE assignment_nodes
                SET status='failed',
                    completed_at=?,
                    success_reason='',
                    result_ref='',
                    failure_reason=?,
                    updated_at=?
                WHERE ticket_id=? AND node_id=?
                """,
                (now_text, failure_text, now_text, ticket_id, node_id),
            )
            _recompute_graph_statuses(conn, ticket_id)
            _write_assignment_audit(
                conn,
                ticket_id=ticket_id,
                node_id=node_id,
                action="execution_failed",
                operator=operator_text,
                reason=failure_text,
                target_status="failed",
                detail={"run_id": run_id, "result_ref": result_ref_ui},
                created_at=now_text,
            )
            _update_assignment_execution_run(
                conn,
                run_id=run_id,
                status="failed",
                latest_event=failure_text,
                latest_event_at=now_text,
                exit_code=exit_code,
                stdout_ref=stdout_ref_ui,
                stderr_ref=stderr_ref_ui,
                result_ref=result_ref_ui,
                finished_at=now_text,
            )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    if snapshot is not None:
        _sync_assignment_workspace_snapshot(root, snapshot)
    if success:
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
    node_snapshot: dict[str, Any],
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
            _touch_assignment_execution_run_latest_event(
                root,
                run_id=run_id,
                latest_event=message_text or f"{name} 输出",
                latest_event_at=created_at,
            )

    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _update_assignment_execution_run(
            conn,
            run_id=run_id,
            status="running",
            latest_event="Provider 已启动，执行中。",
            latest_event_at=started_at,
        )
        conn.commit()
    finally:
        conn.close()
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
    fallback_text = ""
    if agent_messages:
        fallback_text = agent_messages[-1]
    else:
        fallback_text = stdout_text.strip()
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
        node=node_snapshot,
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
        node_snapshot=node_snapshot,
        exit_code=exit_code,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        result_payload=result_payload,
        failure_message=failure_message,
    )


def _ready_dispatch_candidates(conn: sqlite3.Connection, *, ticket_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT node_id,node_name,assigned_agent_id,status,priority,created_at,updated_at
        FROM assignment_nodes
        WHERE ticket_id=? AND status='ready'
        ORDER BY priority ASC, created_at ASC, node_id ASC
        """,
        (ticket_id,),
    ).fetchall()
    return [_row_dict(row) for row in rows]


def dispatch_assignment_next(
    root: Path,
    *,
    ticket_id_text: str,
    operator: str,
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator_text = _default_assignment_operator(operator)
    now_text = iso_ts(now_local())
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        graph_row = _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        _recompute_graph_statuses(conn, ticket_id)
        graph_row = _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        scheduler_state = str(graph_row["scheduler_state"] or "").strip().lower()
        if scheduler_state != "running":
            snapshot = _current_assignment_snapshot(conn, ticket_id)
            conn.commit()
            return {
                "ticket_id": ticket_id,
                "dispatched": [],
                "skipped": [],
                "message": "scheduler_not_running",
                "graph_overview": _graph_overview_payload(
                    snapshot["graph_row"],
                    metrics_summary=snapshot["metrics_summary"],
                    scheduler_state_payload=snapshot["scheduler"],
                ),
            }
        system_limit, _updated_at = _get_global_concurrency_limit(conn)
        counts = _running_counts(conn, ticket_id=ticket_id)
        graph_limit = int(graph_row["global_concurrency_limit"] or 0)
        effective_limit = _graph_effective_limit(graph_limit=graph_limit, system_limit=system_limit)
        graph_slots = max(0, effective_limit - int(counts["graph_running_node_count"]))
        system_slots = max(0, system_limit - int(counts["system_running_node_count"]))
        dispatch_slots = min(graph_slots, system_slots)
        dispatched: list[dict[str, Any]] = []
        dispatched_runs: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        pending_execution_runs: list[dict[str, Any]] = []
        running_agents = {
            str(row["assigned_agent_id"] or "").strip()
            for row in conn.execute(
                "SELECT assigned_agent_id FROM assignment_nodes WHERE status='running'"
            ).fetchall()
            if str(row["assigned_agent_id"] or "").strip()
        }
        if dispatch_slots <= 0:
            snapshot = _current_assignment_snapshot(conn, ticket_id)
            conn.commit()
            return {
                "ticket_id": ticket_id,
                "dispatched": [],
                "skipped": [
                    {
                        "code": "concurrency_limit_reached",
                        "message": "global_or_graph_concurrency_limit_reached",
                    }
                ],
                "graph_overview": _graph_overview_payload(
                    snapshot["graph_row"],
                    metrics_summary=snapshot["metrics_summary"],
                    scheduler_state_payload=snapshot["scheduler"],
                ),
            }
        candidates = _ready_dispatch_candidates(conn, ticket_id=ticket_id)
        for candidate in candidates:
            if dispatch_slots <= 0:
                break
            node_id = str(candidate.get("node_id") or "").strip()
            agent_id = str(candidate.get("assigned_agent_id") or "").strip()
            if not node_id or not agent_id:
                continue
            if agent_id in running_agents:
                skipped.append(
                    {
                        "node_id": node_id,
                        "code": "agent_busy",
                        "message": "assigned agent already has running node",
                    }
                )
                continue
            try:
                execution_run = _prepare_assignment_execution_run(
                    conn,
                    root=root,
                    ticket_id=ticket_id,
                    node_id=node_id,
                    now_text=now_text,
                )
            except AssignmentCenterError as exc:
                failure_text = _short_assignment_text(str(exc), 500) or "dispatch preparation failed"
                conn.execute(
                    """
                    UPDATE assignment_nodes
                    SET status='failed',
                        completed_at=?,
                        success_reason='',
                        result_ref='',
                        failure_reason=?,
                        updated_at=?
                    WHERE ticket_id=? AND node_id=?
                    """,
                    (now_text, failure_text, now_text, ticket_id, node_id),
                )
                _recompute_graph_statuses(conn, ticket_id)
                _write_assignment_audit(
                    conn,
                    ticket_id=ticket_id,
                    node_id=node_id,
                    action="dispatch_failed",
                    operator=operator_text,
                    reason=failure_text,
                    target_status="failed",
                    detail={"code": exc.code, **exc.extra},
                    created_at=now_text,
                )
                skipped.append(
                    {
                        "node_id": node_id,
                        "code": str(exc.code or "dispatch_prepare_failed"),
                        "message": str(exc),
                    }
                )
                continue
            conn.execute(
                """
                UPDATE assignment_nodes
                SET status='running',updated_at=?
                WHERE ticket_id=? AND node_id=? AND status='ready'
                """,
                (now_text, ticket_id, node_id),
            )
            running_agents.add(agent_id)
            dispatch_slots -= 1
            audit_id = _write_assignment_audit(
                conn,
                ticket_id=ticket_id,
                node_id=node_id,
                action="dispatch",
                operator=operator_text,
                reason="dispatch next ready node",
                target_status="running",
                detail={
                    "assigned_agent_id": agent_id,
                    "priority": int(candidate.get("priority") or 0),
                    "run_id": str(execution_run.get("run_id") or "").strip(),
                    "provider": str(execution_run.get("provider") or "").strip(),
                    "workspace_path": str((execution_run.get("workspace_path") or Path(".")).as_posix() if isinstance(execution_run.get("workspace_path"), Path) else execution_run.get("workspace_path") or ""),
                    "prompt_ref": _path_for_ui(root, execution_run.get("files", {}).get("prompt")),
                    "stdout_ref": _path_for_ui(root, execution_run.get("files", {}).get("stdout")),
                    "stderr_ref": _path_for_ui(root, execution_run.get("files", {}).get("stderr")),
                    "result_ref": _path_for_ui(root, execution_run.get("files", {}).get("result")),
                },
                created_at=now_text,
            )
            pending_execution_runs.append(execution_run)
            dispatched.append({"node_id": node_id, "audit_id": audit_id, "run_id": str(execution_run.get("run_id") or "").strip()})
            dispatched_runs.append(
                {
                    "run_id": str(execution_run.get("run_id") or "").strip(),
                    "ticket_id": ticket_id,
                    "node_id": node_id,
                    "provider": str(execution_run.get("provider") or "").strip(),
                    "workspace_path": str((execution_run.get("workspace_path") or Path(".")).as_posix() if isinstance(execution_run.get("workspace_path"), Path) else execution_run.get("workspace_path") or ""),
                    "command_summary": str(execution_run.get("command_summary") or "").strip(),
                    "prompt_ref": _path_for_ui(root, execution_run.get("files", {}).get("prompt")),
                    "stdout_ref": _path_for_ui(root, execution_run.get("files", {}).get("stdout")),
                    "stderr_ref": _path_for_ui(root, execution_run.get("files", {}).get("stderr")),
                    "result_ref": _path_for_ui(root, execution_run.get("files", {}).get("result")),
                }
            )
        _refresh_pause_state(conn, ticket_id, now_text)
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(root, snapshot)
    for execution_run in pending_execution_runs:
        try:
            thread = threading.Thread(
                target=_assignment_execution_worker,
                kwargs={
                    "root": root,
                    "run_id": str(execution_run.get("run_id") or "").strip(),
                    "ticket_id": ticket_id,
                    "node_id": str(execution_run.get("node_id") or "").strip(),
                    "node_snapshot": dict(execution_run.get("node") or {}),
                    "workspace_path": execution_run.get("workspace_path"),
                    "command": list(execution_run.get("command") or []),
                    "command_summary": str(execution_run.get("command_summary") or "").strip(),
                    "prompt_text": str(execution_run.get("prompt_text") or ""),
                },
                daemon=True,
            )
            thread.start()
        except Exception as exc:
            _append_assignment_run_event(
                execution_run.get("files", {}).get("events"),
                event_type="provider_start_failed",
                message=f"后台线程启动失败: {exc}",
                created_at=iso_ts(now_local()),
                detail={},
            )
            _finalize_assignment_execution_run(
                root,
                run_id=str(execution_run.get("run_id") or "").strip(),
                ticket_id=ticket_id,
                node_id=str(execution_run.get("node_id") or "").strip(),
                node_snapshot=dict(execution_run.get("node") or {}),
                exit_code=1,
                stdout_text="",
                stderr_text=str(exc),
                result_payload={},
                failure_message=f"assignment execution worker start failed: {exc}",
            )
    dispatched_nodes = [
        node
        for node in snapshot["serialized_nodes"]
        if str(node.get("node_id") or "").strip() in {item["node_id"] for item in dispatched}
    ]
    return {
        "ticket_id": ticket_id,
        "dispatched": dispatched_nodes,
        "dispatched_runs": dispatched_runs,
        "skipped": skipped,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }


def pause_assignment_scheduler(
    root: Path,
    *,
    ticket_id_text: str,
    operator: str,
    pause_note: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator_text = _default_assignment_operator(operator)
    note_text = _normalize_text(pause_note, field="pause_note", required=False, max_len=500)
    now_text = iso_ts(now_local())
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        _reconcile_stale_running_nodes(conn, ticket_id=ticket_id)
        running_count = int(
            (
                conn.execute(
                    """
                    SELECT COUNT(1) AS cnt
                    FROM assignment_nodes
                    WHERE ticket_id=? AND status='running'
                    """,
                    (ticket_id,),
                ).fetchone()
                or {"cnt": 0}
            )["cnt"]
        )
        next_state = "pause_pending" if running_count > 0 else "paused"
        conn.execute(
            """
            UPDATE assignment_graphs
            SET scheduler_state=?,pause_note=?,updated_at=?
            WHERE ticket_id=?
            """,
            (next_state, note_text, now_text, ticket_id),
        )
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id="",
            action="pause_scheduler",
            operator=operator_text,
            reason=note_text or "pause scheduler",
            target_status=next_state,
            detail={"running_count": running_count},
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(root, snapshot)
    return {
        "ticket_id": ticket_id,
        "state": next_state,
        "state_text": _scheduler_state_text(next_state),
        "pause_note": note_text,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }


def resume_assignment_scheduler(
    root: Path,
    *,
    ticket_id_text: str,
    operator: str,
    pause_note: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator_text = _default_assignment_operator(operator)
    note_text = _normalize_text(pause_note, field="pause_note", required=False, max_len=500)
    now_text = iso_ts(now_local())
    dispatch_result: dict[str, Any] | None = None
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        _reconcile_stale_running_nodes(conn, ticket_id=ticket_id)
        conn.execute(
            """
            UPDATE assignment_graphs
            SET scheduler_state='running',pause_note=?,updated_at=?
            WHERE ticket_id=?
            """,
            (note_text, now_text, ticket_id),
        )
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id="",
            action="resume_scheduler",
            operator=operator_text,
            reason=note_text or "resume scheduler",
            target_status="running",
            detail={},
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(root, snapshot)
    try:
        dispatch_result = dispatch_assignment_next(
            root,
            ticket_id_text=ticket_id,
            operator=operator_text,
            include_test_data=include_test_data,
        )
    except Exception:
        dispatch_result = None
    graph_overview = _graph_overview_payload(
        snapshot["graph_row"],
        metrics_summary=snapshot["metrics_summary"],
        scheduler_state_payload=snapshot["scheduler"],
    )
    if isinstance(dispatch_result, dict) and isinstance(dispatch_result.get("graph_overview"), dict):
        graph_overview = dict(dispatch_result["graph_overview"])
    return {
        "ticket_id": ticket_id,
        "state": "running",
        "state_text": _scheduler_state_text("running"),
        "pause_note": note_text,
        "audit_id": audit_id,
        "graph_overview": graph_overview,
        "dispatch_result": dispatch_result or {},
    }


def clear_assignment_graph(
    root: Path,
    *,
    ticket_id_text: str,
    operator: str,
    reason: Any = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    ticket_id = safe_token(str(ticket_id_text or ""), "", 160)
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    operator_text = _default_assignment_operator(operator)
    reason_text = _normalize_text(reason, field="reason", required=False, max_len=1000)
    now_text = iso_ts(now_local())
    removed_nodes: list[dict[str, Any]] = []
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_graph_row_visible(conn, ticket_id, include_test_data=include_test_data)
        snapshot_before = _current_assignment_snapshot(conn, ticket_id)
        removed_nodes = list(snapshot_before.get("serialized_nodes") or [])
        running_nodes = [
            node
            for node in removed_nodes
            if str(node.get("status") or "").strip().lower() == "running"
        ]
        if running_nodes:
            raise AssignmentCenterError(
                409,
                "running nodes prevent clear",
                "assignment_clear_has_running_nodes",
                {
                    "running_node_ids": [
                        str(node.get("node_id") or "").strip()
                        for node in running_nodes
                    ],
                },
            )
        removed_edge_count = int(
            conn.execute(
                "DELETE FROM assignment_edges WHERE ticket_id=?",
                (ticket_id,),
            ).rowcount
            or 0
        )
        removed_node_count = int(
            conn.execute(
                "DELETE FROM assignment_nodes WHERE ticket_id=?",
                (ticket_id,),
            ).rowcount
            or 0
        )
        conn.execute(
            """
            UPDATE assignment_graphs
            SET scheduler_state='idle',pause_note='',updated_at=?
            WHERE ticket_id=?
            """,
            (now_text, ticket_id),
        )
        audit_id = _write_assignment_audit(
            conn,
            ticket_id=ticket_id,
            node_id="",
            action="clear_graph",
            operator=operator_text,
            reason=reason_text or "clear assignment graph",
            target_status="idle",
            detail={
                "removed_node_count": removed_node_count,
                "removed_edge_count": removed_edge_count,
                "removed_node_ids": [
                    str(node.get("node_id") or "").strip()
                    for node in removed_nodes[:100]
                ],
            },
            created_at=now_text,
        )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    for node in removed_nodes:
        _persist_assignment_workspace_node(
            root,
            node=node,
            record_state="deleted",
            audit_id=audit_id,
            extra={
                "delete_action": "clear_graph",
                "deleted_at": now_text,
                "delete_reason": reason_text or "clear assignment graph",
            },
        )
    _persist_assignment_workspace_graph(
        root,
        snapshot=snapshot,
        record_state="active",
        extra={
            "last_graph_action": "clear_graph",
            "last_graph_action_at": now_text,
            "audit_ref": _db_ref(audit_id),
        },
    )
    return {
        "ticket_id": ticket_id,
        "removed_node_count": removed_node_count,
        "removed_edge_count": removed_edge_count,
        "audit_id": audit_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }
