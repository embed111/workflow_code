from __future__ import annotations

from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

def handle_task_execute(self, cfg, state, body: dict[str, Any]) -> None:
    resolved = self.resolve_session(body, allow_create=True)
    if not resolved:
        return
    session, focus = resolved
    if not self.enforce_session_policy_reanalyze(session, "/api/tasks/execute"):
        return
    retry = bool(body.get("retry"))
    message = str(body.get("message") or "").strip()
    if retry and not message:
        message = last_user_message(cfg.root, session["session_id"])
    if not message:
        self.send_json(400, {"ok": False, "error": "message required"})
        return

    raw_write_targets = body.get("write_targets")
    explicit_write_targets: list[str] = []
    if isinstance(raw_write_targets, list):
        explicit_write_targets = [str(item) for item in raw_write_targets]
    elif isinstance(raw_write_targets, str):
        explicit_write_targets = [raw_write_targets]
    try:
        write_targets = normalize_write_targets(
            normalize_abs_path(session["agent_search_root"], base=cfg.root),
            collect_write_targets(message, explicit_write_targets),
        )
    except SessionGateError as exc:
        self.send_json(
            exc.status_code,
            {
                "ok": False,
                "error": str(exc),
                "code": exc.code,
                "session_id": session["session_id"],
                "agent_search_root": session["agent_search_root"],
            },
        )
        append_failure_case(
            cfg.root,
            "path_out_of_root blocked",
            f"code={exc.code}, session_id={session['session_id']}",
        )
        persist_event(
            cfg.root,
            {
                "event_id": event_id(),
                "timestamp": iso_ts(now_local()),
                "session_id": session["session_id"],
                "actor": "workflow",
                "stage": "governance",
                "action": "task_execute_blocked",
                "status": "failed",
                "latency_ms": 0,
                "task_id": "",
                "reason_tags": [exc.code],
                "ref": "",
            },
        )
        return

    task_id_text = new_task_id()
    request_id = f"req-{uuid.uuid4().hex[:10]}"
    ref = relative_to_root(cfg.root, event_file(cfg.root))
    command, command_display = build_agent_command(
        cfg,
        task_id_text,
        session=session,
        message=message,
        focus=focus,
        write_targets=write_targets,
    )
    try:
        record_ingress(cfg.root, request_id, session["session_id"], "/api/tasks/execute")
        add_message(cfg.root, session["session_id"], "user", message)
        persist_event(
            cfg.root,
            {
                "event_id": event_id(),
                "timestamp": iso_ts(now_local()),
                "session_id": session["session_id"],
                "actor": "user",
                "stage": "chat",
                "action": "send_message",
                "status": "success",
                "latency_ms": 0,
                "task_id": task_id_text,
                "reason_tags": [],
                "ref": ref,
            },
        )
        mark_ingress_logged(cfg.root, request_id)
        create_task_run(
            cfg.root,
            task_id_text=task_id_text,
            session_id=session["session_id"],
            agent_name=session["agent_name"],
            agent_search_root=session["agent_search_root"],
            message=message,
            command=command,
            command_display=command_display,
        )
        append_task_event(
            cfg.root,
            task_id_text,
            "created",
            {
                "task_id": task_id_text,
                "session_id": session["session_id"],
                "agent_name": session["agent_name"],
                "status": "pending",
            },
        )
        worker = threading.Thread(
            target=execute_task_worker,
            args=(
                cfg,
                state,
                task_id_text,
                session,
                message,
                focus,
                command,
                command_display,
            ),
            daemon=True,
            name=f"task-{task_id_text}",
        )
        worker.start()
    except Exception as exc:
        self.send_json(500, {"ok": False, "error": f"create task failed: {exc}"})
        return
    self.send_json(
        202,
        {
            "ok": True,
            "task_id": task_id_text,
            "status": "pending",
            "session_id": session["session_id"],
            "agent_name": session["agent_name"],
            "agents_hash": session["agents_hash"],
            "agents_loaded_at": session["agents_loaded_at"],
            "agents_path": session.get("agents_path", ""),
            "agents_version": session.get("agents_version", ""),
            "policy_summary": session.get("policy_summary", ""),
            "agent_search_root": session["agent_search_root"],
            "is_test_data": bool(session.get("is_test_data")),
            "command": command_display,
        },
    )

def handle_chat_non_stream(self, cfg, state, body: dict[str, Any]) -> None:
    resolved = self.resolve_session(body, allow_create=True)
    if not resolved:
        return
    session, _focus = resolved
    if not self.enforce_session_policy_reanalyze(session, "/api/chat"):
        return
    session_id = session["session_id"]
    agent_name = session["agent_name"]
    request_id = f"req-{uuid.uuid4().hex[:10]}"
    retry = bool(body.get("retry"))
    message = str(body.get("message") or "").strip()
    if retry and not message:
        message = last_user_message(cfg.root, session_id)
    if not message:
        self.send_json(400, {"ok": False, "error": "message required"})
        return

    lease: threading.Lock | None = None
    try:
        lease = acquire_generation_slot(state, session_id)
    except ConcurrencyLimitError as exc:
        self.send_json(429, {"ok": False, "error": str(exc), "code": "concurrency_limit"})
        return

    record_ingress(cfg.root, request_id, session_id, "/api/chat")
    task = task_id()
    ref = relative_to_root(cfg.root, event_file(cfg.root))
    try:
        try:
            add_message(cfg.root, session_id, "user", message)
            persist_event(cfg.root, {"event_id": event_id(), "timestamp": iso_ts(now_local()), "session_id": session_id, "actor": "user", "stage": "chat", "action": "send_message", "status": "success", "latency_ms": 0, "task_id": task, "reason_tags": [], "ref": ref})
            mark_ingress_logged(cfg.root, request_id)
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": f"event write failed: {exc}"})
            return

        started = time.perf_counter()
        first_ms: int | None = None
        status = "success"
        note = ""
        policy_tags = session_policy_reason_tags(session)
        try:
            reply = chat_once(load_messages_with_session_policy(cfg.root, session))
            total_ms = int((time.perf_counter() - started) * 1000)
            first_ms = total_ms
        except AgentConfigError as exc:
            reply = ""
            total_ms = int((time.perf_counter() - started) * 1000)
            status = "failed"
            note = str(exc)
        except AgentRuntimeError as exc:
            reply = ""
            total_ms = int((time.perf_counter() - started) * 1000)
            status = "failed"
            note = str(exc)
        except Exception as exc:
            reply = ""
            total_ms = int((time.perf_counter() - started) * 1000)
            status = "failed"
            note = str(exc)

        if reply:
            add_message(cfg.root, session_id, "assistant", reply)
        try:
            persist_event(cfg.root, {"event_id": event_id(), "timestamp": iso_ts(now_local()), "session_id": session_id, "actor": "agent", "stage": "chat", "action": "send_message", "status": status, "latency_ms": total_ms, "task_id": task, "reason_tags": (policy_tags if status == "success" else [status, *policy_tags]), "ref": ref})
            self.refresh_after_round()
            run_ref = append_web_e2e(cfg.root, request_id, "", session_id, message, reply, first_ms, total_ms, status, note)
            append_workflow_latency(cfg.root, {"timestamp": iso_ts(now_local()), "request_id": request_id, "session_id": session_id, "mode": "non_stream", "first_token_ms": first_ms, "total_ms": total_ms, "status": status, "ref": run_ref})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": f"post-processing failed: {exc}"})
            return

        if status != "success":
            self.send_json(
                502,
                {
                    "ok": False,
                    "error": note or "agent failed",
                    "session_id": session_id,
                    "agent_name": agent_name,
                    "agents_hash": session["agents_hash"],
                    "is_test_data": bool(session.get("is_test_data")),
                },
            )
            return
        self.send_json(
            200,
            {
                "ok": True,
                "session_id": session_id,
                "agent_name": agent_name,
                "agents_hash": session["agents_hash"],
                "agents_loaded_at": session["agents_loaded_at"],
                "is_test_data": bool(session.get("is_test_data")),
                "reply": reply,
                "latency_ms": total_ms,
            },
        )
    finally:
        release_generation_slot(state, lease)

def handle_chat_stream(self, cfg, state, body: dict[str, Any]) -> None:
    resolved = self.resolve_session(body, allow_create=True)
    if not resolved:
        return
    session, _focus = resolved
    if not self.enforce_session_policy_reanalyze(session, "/api/chat/stream"):
        return
    session_id = session["session_id"]
    agent_name = session["agent_name"]
    request_id = f"req-{uuid.uuid4().hex[:10]}"
    retry = bool(body.get("retry"))
    message = str(body.get("message") or "").strip()
    if retry and not message:
        message = last_user_message(cfg.root, session_id)
    if not message:
        self.send_json(400, {"ok": False, "error": "message required"})
        return

    lease: threading.Lock | None = None
    try:
        lease = acquire_generation_slot(state, session_id)
    except ConcurrencyLimitError as exc:
        self.send_json(429, {"ok": False, "error": str(exc), "code": "concurrency_limit"})
        return

    stream_id = f"stream-{uuid.uuid4().hex[:10]}"
    stop_evt = threading.Event()
    with state.stream_lock:
        state.active_streams[stream_id] = stop_evt
    record_ingress(cfg.root, request_id, session_id, "/api/chat/stream")
    task = task_id()
    ref = relative_to_root(cfg.root, event_file(cfg.root))

    try:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(obj: dict[str, Any]) -> bool:
            try:
                self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
                return True
            except Exception:
                return False

        if not emit(
            {
                "type": "start",
                "stream_id": stream_id,
                "session_id": session_id,
                "agent_name": agent_name,
                "agents_hash": session["agents_hash"],
                "agents_loaded_at": session["agents_loaded_at"],
            }
        ):
            return

        try:
            add_message(cfg.root, session_id, "user", message)
            persist_event(cfg.root, {"event_id": event_id(), "timestamp": iso_ts(now_local()), "session_id": session_id, "actor": "user", "stage": "chat", "action": "send_message", "status": "success", "latency_ms": 0, "task_id": task, "reason_tags": [], "ref": ref})
            mark_ingress_logged(cfg.root, request_id)
        except Exception as exc:
            emit({"type": "error", "error": f"event write failed: {exc}"})
            return

        started = time.perf_counter()
        first_ms: int | None = None
        chunks: list[str] = []
        status = "success"
        note = ""
        policy_tags = session_policy_reason_tags(session)

        def on_delta(delta: str) -> None:
            nonlocal first_ms
            if first_ms is None:
                first_ms = int((time.perf_counter() - started) * 1000)
            chunks.append(delta)
            if not emit({"type": "delta", "delta": delta}):
                stop_evt.set()

        try:
            reply = stream_chat(load_messages_with_session_policy(cfg.root, session), on_delta=on_delta, should_stop=lambda: stop_evt.is_set())
        except AgentConfigError as exc:
            reply = "".join(chunks)
            status = "failed"
            note = str(exc)
        except AgentRuntimeError as exc:
            reply = "".join(chunks)
            status = "failed"
            note = str(exc)
        except Exception as exc:
            reply = "".join(chunks)
            status = "failed"
            note = str(exc)
        interrupted = stop_evt.is_set()
        if interrupted and status == "success":
            status = "failed"
            note = "interrupted"
        total_ms = int((time.perf_counter() - started) * 1000)

        if reply:
            add_message(cfg.root, session_id, "assistant", reply)
        try:
            tags = []
            if interrupted:
                tags.append("interrupted")
            if status != "success":
                tags.append("agent_failed")
            tags.extend(policy_tags)
            persist_event(cfg.root, {"event_id": event_id(), "timestamp": iso_ts(now_local()), "session_id": session_id, "actor": "agent", "stage": "chat", "action": "send_message", "status": status, "latency_ms": total_ms, "task_id": task, "reason_tags": tags, "ref": ref})
            self.refresh_after_round()
            run_ref = append_web_e2e(cfg.root, request_id, stream_id, session_id, message, reply, first_ms, total_ms, status, note)
            append_workflow_latency(cfg.root, {"timestamp": iso_ts(now_local()), "request_id": request_id, "session_id": session_id, "mode": "stream", "first_token_ms": first_ms, "total_ms": total_ms, "status": status, "interrupted": interrupted, "ref": run_ref})
        except Exception as exc:
            emit({"type": "error", "error": f"post-processing failed: {exc}"})
            return

        emit({"type": "done", "session_id": session_id, "stream_id": stream_id, "agent_name": agent_name, "agents_hash": session["agents_hash"], "interrupted": interrupted, "status": status, "latency_ms": total_ms, "error": note})
    finally:
        with state.stream_lock:
            state.active_streams.pop(stream_id, None)
        release_generation_slot(state, lease)

