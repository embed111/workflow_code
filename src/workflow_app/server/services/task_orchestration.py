from __future__ import annotations

from workflow_app.server.services.codex_failure_contract import (
    build_codex_failure,
    build_retry_action,
    infer_codex_failure_detail_code,
)

from .work_record_store import (
    append_task_run_event_record,
    create_task_run_record,
    get_task_run_record,
    get_training_task_record,
    list_task_run_event_records,
    list_task_run_records,
    load_task_trace_payload,
    mark_task_run_status,
    task_run_paths,
    update_task_run_record,
    update_task_run_result_files,
    write_task_run_summary,
)

def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    globals().update(symbols)


def _task_run_failure_detail_code(summary: str, stderr_text: str) -> str:
    stderr_value = str(stderr_text or "").strip()
    stderr_lower = stderr_value.lower()
    if "agent_policy_extract_failed:" in stderr_lower:
        suffix = stderr_lower.split("agent_policy_extract_failed:", 1)[1].splitlines()[0].strip()
        return suffix or "policy_extract_failed"
    if "codex command not found in path" in stderr_lower:
        return "codex_command_not_found"
    if "codex returned no agent message" in stderr_lower:
        return "codex_result_missing"
    if "invalid agent_search_root" in stderr_lower:
        return "workspace_missing"
    if "path_in_protected_root" in stderr_lower:
        return "protected_workspace_root"
    if "no conversation context" in stderr_lower:
        return "input_missing"
    return infer_codex_failure_detail_code(stderr_value or summary, fallback="execution_failed")


def _task_run_codex_failure(
    root: Path,
    *,
    task_id_text: str,
    session: dict[str, str],
    status: str,
    summary: str,
    stderr_text: str,
    failed_at: str,
) -> dict[str, Any]:
    if str(status or "").strip().lower() != "failed":
        return {}
    detail_code = _task_run_failure_detail_code(summary, stderr_text)
    row = get_task_run_record(root, task_id_text) or {}
    attempt_count = len(list_task_run_records(root, session_id=str(session.get("session_id") or ""), limit=2000))
    trace_refs = {
        "trace": str(row.get("trace_ref") or "").strip(),
        "stdout": str(row.get("stdout_ref") or "").strip(),
        "stderr": str(row.get("stderr_ref") or "").strip(),
        "summary": str(row.get("ref") or "").strip(),
    }
    return build_codex_failure(
        feature_key="session_task_execution",
        attempt_id=task_id_text,
        attempt_count=max(1, int(attempt_count or 0)),
        failure_detail_code=detail_code,
        failure_message=str(stderr_text or summary or "").strip(),
        retry_action=build_retry_action(
            "retry_session_round",
            payload={
                "session_id": str(session.get("session_id") or "").strip(),
                "agent_name": str(session.get("agent_name") or "").strip(),
            },
        ),
        trace_refs=trace_refs,
        failed_at=failed_at,
    )

def _decref_session_lock(state: RuntimeState, session_id: str, lock: threading.Lock) -> None:
    with state.session_lock_guard:
        entry = state.session_locks.get(session_id)
        if entry is None or entry.lock is not lock:
            return
        entry.ref_count = max(0, int(entry.ref_count or 0) - 1)
        if entry.ref_count <= 0 and not entry.lock.locked():
            state.session_locks.pop(session_id, None)


def session_lock_for(state: RuntimeState, session_id: str) -> SessionLockEntry:
    with state.session_lock_guard:
        entry = state.session_locks.get(session_id)
        if entry is None:
            entry = SessionLockEntry()
            state.session_locks[session_id] = entry
        entry.ref_count += 1
        return entry


def acquire_generation_slot(
    state: RuntimeState,
    session_id: str,
    *,
    blocking: bool = False,
) -> GenerationLease:
    entry = session_lock_for(state, session_id)
    lock = entry.lock
    lock.acquire()
    acquired = state.generation_semaphore.acquire(blocking=blocking)
    if not acquired:
        lock.release()
        _decref_session_lock(state, session_id, lock)
        raise ConcurrencyLimitError(
            f"generation concurrency limit reached ({MAX_GENERATION_CONCURRENCY})"
        )
    return GenerationLease(session_id=session_id, lock=lock)


def release_generation_slot(state: RuntimeState, lease: GenerationLease | None) -> None:
    if lease is None:
        return
    lock = lease.lock
    state.generation_semaphore.release()
    lock.release()
    _decref_session_lock(state, lease.session_id, lock)


def new_task_id() -> str:
    ts = now_local()
    return f"task-{date_key(ts)}-{uuid.uuid4().hex[:8]}"


def redact_command(parts: list[str]) -> list[str]:
    out: list[str] = []
    for item in parts:
        text = str(item)
        lower = text.lower()
        if any(key in lower for key in ["api_key", "token", "secret", "password"]):
            out.append("***")
            continue
        if text.startswith("sk-"):
            out.append("***")
            continue
        out.append(text)
    return out


def build_agent_command(
    cfg: AppConfig,
    task_id_text: str,
    session: dict[str, str],
    message: str,
    focus: str,
    write_targets: list[str],
) -> tuple[list[str], list[str]]:
    runner_candidates = [
        (cfg.root / "scripts" / "task_agent_runner.py").resolve(),
        (cfg.root / "scripts" / "bin" / "task_agent_runner.py").resolve(),
        (WORKFLOW_APP_ROOT.parents[1] / "scripts" / "bin" / "task_agent_runner.py").resolve(),
        (WORKFLOW_APP_ROOT / "runtime" / "task_agent_runner.py").resolve(),
    ]
    runner = next((candidate for candidate in runner_candidates if candidate.exists()), runner_candidates[-1])
    trace_file = task_trace_file(cfg.root, task_id_text)
    cmd = [
        sys.executable,
        "-u",
        str(runner),
        "--root",
        str(cfg.root),
        "--session-id",
        session["session_id"],
        "--agent",
        session["agent_name"],
        "--agent-search-root",
        session["agent_search_root"],
        "--focus",
        focus,
        "--message",
        message,
        "--trace-file",
        str(trace_file),
    ]
    for target in write_targets:
        cmd.extend(["--write-target", target])
    return cmd, redact_command(cmd)


def create_task_run(
    root: Path,
    task_id_text: str,
    session_id: str,
    agent_name: str,
    agent_search_root: str,
    message: str,
    command: list[str],
    command_display: list[str],
) -> None:
    create_task_run_record(
        root,
        {
            "task_id": task_id_text,
            "session_id": session_id,
            "agent_name": agent_name,
            "agent_search_root": agent_search_root,
            "default_agents_root": agent_search_root,
            "target_path": agent_search_root,
            "status": "pending",
            "message": message,
            "command_json": json.dumps(command, ensure_ascii=False),
            "command_display": json.dumps(command_display, ensure_ascii=False),
            "created_at": iso_ts(now_local()),
        },
    )


def append_task_event(
    root: Path,
    task_id_text: str,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    return append_task_run_event_record(
        root,
        task_id_text,
        {
            "timestamp": iso_ts(now_local()),
            "event_type": event_type,
            "payload": dict(payload or {}),
        },
    )


def get_task_run(root: Path, task_id_text: str) -> dict[str, Any] | None:
    out = get_task_run_record(root, task_id_text)
    if not out:
        return None
    try:
        out["command"] = json.loads(str(out.get("command_display") or "[]"))
    except Exception:
        out["command"] = []
    return out


def list_session_task_runs(root: Path, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = list_task_run_records(root, session_id=session_id, limit=max(1, min(limit, 2000)))
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["command"] = json.loads(str(item.get("command_display") or "[]"))
        except Exception:
            item["command"] = []
        task_id_value = str(item.get("task_id") or "")
        item["trace_available"] = bool(task_id_value and task_trace_file(root, task_id_value).exists())
        out.append(item)
    return out


def list_task_events(root: Path, task_id_text: str, since_id: int, limit: int = 400) -> list[dict[str, Any]]:
    return list_task_run_event_records(
        root,
        task_id_text,
        since_id=max(0, since_id),
        limit=max(1, min(limit, 1000)),
    )


def update_task_run_result(
    root: Path,
    task_id_text: str,
    *,
    status: str,
    start_at: str | None,
    end_at: str | None,
    duration_ms: int | None,
    stdout_text: str,
    stderr_text: str,
    summary: str,
    ref: str,
    trace_payload: dict[str, Any] | None = None,
    codex_failure: dict[str, Any] | None = None,
) -> None:
    next_trace_payload = dict(trace_payload or load_task_trace(root, task_id_text) or {})
    failure_payload = codex_failure if isinstance(codex_failure, dict) else {}
    if failure_payload:
        next_trace_payload["codex_failure"] = failure_payload
    else:
        next_trace_payload.pop("codex_failure", None)
    update_task_run_result_files(
        root,
        task_id_text,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        trace_payload=next_trace_payload,
    )
    update_task_run_record(
        root,
        task_id_text,
        {
            "status": status,
            "start_at": start_at or "",
            "end_at": end_at or "",
            "duration_ms": duration_ms,
            "summary": summary,
            "ref": ref,
            "codex_failure": failure_payload,
            "updated_at": iso_ts(now_local()),
        },
    )


def mark_task_status(root: Path, task_id_text: str, status: str, *, started_at: str | None = None) -> None:
    mark_task_run_status(root, task_id_text, status, started_at=started_at)


def task_run_file(root: Path, task_id_text: str) -> Path:
    return task_run_paths(root, task_id_text)["summary"]


def task_trace_file(root: Path, task_id_text: str) -> Path:
    return task_run_paths(root, task_id_text)["trace"]


def load_task_trace(root: Path, task_id_text: str) -> dict[str, Any]:
    return load_task_trace_payload(root, task_id_text)


def write_task_run_file(
    root: Path,
    task_id_text: str,
    *,
    session_id: str,
    agent_name: str,
    agent_search_root: str,
    status: str,
    start_at: str,
    end_at: str,
    duration_ms: int,
    command_display: list[str],
    stdout_text: str,
    stderr_text: str,
    summary: str,
) -> str:
    summary_ref = write_task_run_summary(
        root,
        task_id_text,
        session_id=session_id,
        agent_name=agent_name,
        agent_search_root=agent_search_root,
        status=status,
        start_at=start_at,
        end_at=end_at,
        duration_ms=duration_ms,
        command_display=command_display,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        summary=summary,
    )
    return relative_to_root(root, Path(summary_ref))


def set_runtime_task(state: RuntimeState, runtime: TaskRuntime | None, task_id_text: str) -> None:
    with state.task_runtime_lock:
        if runtime is None:
            state.active_tasks.pop(task_id_text, None)
        else:
            state.active_tasks[task_id_text] = runtime


def _task_run_record_is_active(row: dict[str, Any] | None) -> bool:
    status = str((row or {}).get("status") or "").strip().lower()
    return status in {"pending", "queued", "running"}


def reconcile_active_runtime_tasks(root: Path, state: RuntimeState) -> int:
    with state.task_runtime_lock:
        items = list(state.active_tasks.items())
    if not items:
        return 0

    stale_task_ids: list[str] = []
    for task_id_text, runtime in items:
        process = runtime.process
        if process is not None:
            try:
                if process.poll() is None:
                    continue
            except Exception:
                continue
            stale_task_ids.append(task_id_text)
            continue
        row = get_task_run_record(root, task_id_text)
        if _task_run_record_is_active(row):
            continue
        stale_task_ids.append(task_id_text)

    if stale_task_ids:
        with state.task_runtime_lock:
            for task_id_text in stale_task_ids:
                runtime = state.active_tasks.get(task_id_text)
                if runtime is None:
                    continue
                process = runtime.process
                if process is not None:
                    try:
                        if process.poll() is None:
                            continue
                    except Exception:
                        continue
                else:
                    row = get_task_run_record(root, task_id_text)
                    if _task_run_record_is_active(row):
                        continue
                state.active_tasks.pop(task_id_text, None)
            return len(state.active_tasks)

    with state.task_runtime_lock:
        return len(state.active_tasks)


def get_runtime_task(
    state: RuntimeState,
    task_id_text: str,
    *,
    root: Path | None = None,
) -> TaskRuntime | None:
    if root is not None:
        reconcile_active_runtime_tasks(root, state)
    with state.task_runtime_lock:
        return state.active_tasks.get(task_id_text)


def active_runtime_task_count(
    state: RuntimeState,
    *,
    root: Path | None = None,
) -> int:
    if root is not None:
        return reconcile_active_runtime_tasks(root, state)
    with state.task_runtime_lock:
        return len(state.active_tasks)


def has_session_runtime_task(
    state: RuntimeState,
    session_id: str,
    *,
    root: Path | None = None,
) -> bool:
    if root is not None:
        reconcile_active_runtime_tasks(root, state)
    with state.task_runtime_lock:
        return any(rt.session_id == session_id for rt in state.active_tasks.values())


def training_workflow_has_running_task(root: Path, state: RuntimeState, workflow_id: str) -> bool:
    workflow = get_training_workflow(root, workflow_id)
    if not workflow:
        return False
    session_id = str(workflow.get("session_id") or "")
    if session_id and has_session_runtime_task(state, session_id, root=root):
        return True
    analysis_id = str(workflow.get("analysis_id") or "")
    if not analysis_id:
        return False
    task_record = get_training_task_record(root, analysis_id)
    return str((task_record or {}).get("status") or "") == "running"


def append_admin_event(
    root: Path,
    *,
    session_id: str,
    action: str,
    status: str,
    reason_tags: list[str],
    ref: str,
) -> None:
    persist_event(
        root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(now_local()),
            "session_id": session_id,
            "actor": "workflow",
            "stage": "governance",
            "action": action,
            "status": status,
            "latency_ms": 0,
            "task_id": "",
            "reason_tags": reason_tags,
            "ref": ref,
        },
    )


def execute_task_worker(
    cfg: AppConfig,
    state: RuntimeState,
    task_id_text: str,
    session: dict[str, str],
    message: str,
    focus: str,
    command: list[str],
    command_display: list[str],
) -> None:
    runtime = TaskRuntime(
        task_id=task_id_text,
        session_id=session["session_id"],
        agent_name=session["agent_name"],
    )
    set_runtime_task(state, runtime, task_id_text)
    append_task_event(
        cfg.root,
        task_id_text,
        "queued",
        {
            "task_id": task_id_text,
            "session_id": session["session_id"],
            "agent_name": session["agent_name"],
        },
    )
    lease: GenerationLease | None = None
    start_ts = now_local()
    start_at = iso_ts(start_ts)
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    status = "failed"
    summary = ""
    ref = ""
    try:
        mark_task_status(cfg.root, task_id_text, "queued")
        lease = acquire_generation_slot(state, session["session_id"], blocking=True)
        if runtime.stop_event.is_set():
            status = "interrupted"
            summary = "interrupted before command start"
            append_task_event(cfg.root, task_id_text, "interrupted", {"reason": summary})
            return

        mark_task_status(cfg.root, task_id_text, "running", started_at=start_at)
        append_task_event(
            cfg.root,
            task_id_text,
            "running",
            {"task_id": task_id_text, "command": command_display},
        )
        runtime.process = subprocess.Popen(
            command,
            cwd=str(cfg.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        append_task_event(
            cfg.root,
            task_id_text,
            "process_started",
            {"pid": int(runtime.process.pid)},
        )

        def read_stream(name: str, pipe: Any, collector: list[str]) -> None:
            if pipe is None:
                return
            pending: list[str] = []
            while True:
                chunk = pipe.read(1)
                if chunk == "":
                    break
                collector.append(chunk)
                pending.append(chunk)
                if chunk == "\n" or len(pending) >= 64:
                    text = "".join(pending)
                    pending.clear()
                    append_task_event(
                        cfg.root,
                        task_id_text,
                        f"{name}_chunk",
                        {"chunk": text},
                    )
                if runtime.stop_event.is_set() and runtime.process and runtime.process.poll() is not None:
                    break
            if pending:
                append_task_event(
                    cfg.root,
                    task_id_text,
                    f"{name}_chunk",
                    {"chunk": "".join(pending)},
                )

        t_out = threading.Thread(
            target=read_stream,
            args=("stdout", runtime.process.stdout, stdout_chunks),
            daemon=True,
        )
        t_err = threading.Thread(
            target=read_stream,
            args=("stderr", runtime.process.stderr, stderr_chunks),
            daemon=True,
        )
        t_out.start()
        t_err.start()
        rc = runtime.process.wait()
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        if runtime.stop_event.is_set():
            status = "interrupted"
            summary = "process interrupted by user"
        elif rc == 0:
            status = "success"
            summary = "command completed successfully"
        else:
            status = "failed"
            summary = f"command exit code={rc}"
    except Exception as exc:
        status = "failed"
        summary = f"{exc.__class__.__name__}: {exc}"
        stderr_chunks.append(summary + "\n")
        append_task_event(
            cfg.root,
            task_id_text,
            "error",
            {"error": summary},
        )
    finally:
        end_ts = now_local()
        end_at = iso_ts(end_ts)
        duration_ms = max(0, int((end_ts - start_ts).total_seconds() * 1000))
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        if not summary:
            summary = "no summary"
        assistant_reply = stdout_text.rstrip("\n")
        if status == "success" and assistant_reply:
            try:
                add_message(cfg.root, session["session_id"], "assistant", assistant_reply)
            except Exception:
                pass
        ref = write_task_run_file(
            cfg.root,
            task_id_text,
            session_id=session["session_id"],
            agent_name=session["agent_name"],
            agent_search_root=session["agent_search_root"],
            status=status,
            start_at=start_at,
            end_at=end_at,
            duration_ms=duration_ms,
            command_display=command_display,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            summary=summary,
        )
        codex_failure = _task_run_codex_failure(
            cfg.root,
            task_id_text=task_id_text,
            session=session,
            status=status,
            summary=summary,
            stderr_text=stderr_text,
            failed_at=end_at,
        )
        trace_payload = dict(load_task_trace(cfg.root, task_id_text) or {})
        if codex_failure:
            trace_payload["codex_failure"] = codex_failure
        update_task_run_result(
            cfg.root,
            task_id_text,
            status=status,
            start_at=start_at,
            end_at=end_at,
            duration_ms=duration_ms,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            summary=summary,
            ref=ref,
            trace_payload=trace_payload,
            codex_failure=codex_failure,
        )
        append_task_event(
            cfg.root,
            task_id_text,
            "done",
            {
                "task_id": task_id_text,
                "status": status,
                "summary": summary,
                "duration_ms": duration_ms,
                "ref": ref,
                "codex_failure": codex_failure,
            },
        )
        persist_event(
            cfg.root,
            {
                "event_id": event_id(),
                "timestamp": iso_ts(now_local()),
                "session_id": session["session_id"],
                "actor": "agent",
                "stage": "chat",
                "action": "send_message",
                "status": "success" if status == "success" else "failed",
                "latency_ms": duration_ms,
                "task_id": task_id_text,
                "reason_tags": (
                    session_policy_reason_tags(session)
                    if status == "success"
                    else [status, *session_policy_reason_tags(session)]
                ),
                "ref": ref,
            },
        )
        persist_event(
            cfg.root,
            {
                "event_id": event_id(),
                "timestamp": iso_ts(now_local()),
                "session_id": session["session_id"],
                "actor": "workflow",
                "stage": "chat",
                "action": "task_execute",
                "status": "success" if status == "success" else "failed",
                "latency_ms": duration_ms,
                "task_id": task_id_text,
                "reason_tags": (
                    session_policy_reason_tags(session)
                    if status == "success"
                    else [status, *session_policy_reason_tags(session)]
                ),
                "ref": ref,
            },
        )
        try:
            refresh_status(cfg)
            sync_analysis_tasks(cfg.root)
            sync_training_workflows(cfg.root)
        except Exception:
            pass
        release_generation_slot(state, lease)
        set_runtime_task(state, None, task_id_text)


def request_task_interrupt(cfg: AppConfig, state: RuntimeState, task_id_text: str) -> tuple[bool, str]:
    runtime = get_runtime_task(state, task_id_text, root=cfg.root)
    if runtime is None:
        row = get_task_run(cfg.root, task_id_text)
        if not row:
            return False, "task not found"
        status = str(row.get("status") or "")
        if status in {"pending", "queued"}:
            mark_task_status(cfg.root, task_id_text, "interrupted")
            append_task_event(cfg.root, task_id_text, "interrupted", {"reason": "cancelled before start"})
            return True, "interrupted"
        return False, f"task not running (status={status})"
    runtime.stop_event.set()
    runtime.interrupted = True
    append_task_event(cfg.root, task_id_text, "interrupt_requested", {"task_id": task_id_text})
    proc = runtime.process
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass
    return True, "interrupt requested"


