def task_run_paths(root: Path, task_id: str) -> dict[str, Path]:
    return {
        "run_dir": run_dir(root, task_id),
        "run": run_record_path(root, task_id),
        "trace": run_trace_path(root, task_id),
        "stdout": run_stdout_path(root, task_id),
        "stderr": run_stderr_path(root, task_id),
        "events": run_events_path(root, task_id),
        "summary": run_summary_path(root, task_id),
    }


def create_task_run_record(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError("task_id required")
    paths = task_run_paths(root, task_id)
    with _STORE_LOCK:
        record = {
            "record_type": "task_run",
            "schema_version": _SCHEMA_VERSION,
            "task_id": task_id,
            "session_id": str(payload.get("session_id") or ""),
            "agent_name": str(payload.get("agent_name") or ""),
            "agent_search_root": str(payload.get("agent_search_root") or ""),
            "default_agents_root": str(payload.get("default_agents_root") or ""),
            "target_path": str(payload.get("target_path") or ""),
            "status": str(payload.get("status") or "pending"),
            "message": str(payload.get("message") or ""),
            "command_json": str(payload.get("command_json") or "[]"),
            "command_display": str(payload.get("command_display") or "[]"),
            "start_at": str(payload.get("start_at") or ""),
            "end_at": str(payload.get("end_at") or ""),
            "duration_ms": payload.get("duration_ms"),
            "stdout_ref": paths["stdout"].as_posix(),
            "stderr_ref": paths["stderr"].as_posix(),
            "trace_ref": paths["trace"].as_posix(),
            "events_ref": paths["events"].as_posix(),
            "summary": str(payload.get("summary") or ""),
            "ref": normalize_work_record_ref(
                root,
                str(payload.get("ref") or paths["summary"].as_posix()),
                task_id=task_id,
            ),
            "created_at": str(payload.get("created_at") or _now_ts()),
            "updated_at": str(payload.get("updated_at") or payload.get("created_at") or _now_ts()),
            "event_seq": 0,
        }
        _write_json(paths["run"], record)
        for file_path in (paths["stdout"], paths["stderr"], paths["events"]):
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if not file_path.exists():
                file_path.write_text("", encoding="utf-8")
        _sync_task_run_index(root, task_id)
        return record


def get_task_run_record(root: Path, task_id: str) -> dict[str, Any] | None:
    ensure_store(root)
    record = _load_json_dict(run_record_path(root, task_id))
    if not record:
        return None
    stdout_ref = str(record.get("stdout_ref") or "")
    stderr_ref = str(record.get("stderr_ref") or "")
    record["stdout"] = Path(stdout_ref).read_text(encoding="utf-8") if stdout_ref and Path(stdout_ref).exists() else ""
    record["stderr"] = Path(stderr_ref).read_text(encoding="utf-8") if stderr_ref and Path(stderr_ref).exists() else ""
    return record


def list_task_run_records(root: Path, *, session_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
    ensure_store(root)
    rows = _record_index.list_task_run_records_from_index(root, session_id=session_id, limit=limit)
    if rows:
        return rows
    fallback: list[dict[str, Any]] = []
    for path in sorted(runs_root(root).glob("*/run.json"), key=lambda item: item.as_posix().lower()):
        record = _load_json_dict(path)
        if not record:
            continue
        if session_id and str(record.get("session_id") or "") != str(session_id or ""):
            continue
        fallback.append(record)
    fallback.sort(key=lambda item: str(item.get("created_at") or ""))
    return fallback[: max(1, min(int(limit), 2000))]


def update_task_run_record(root: Path, task_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    with _STORE_LOCK:
        record = _load_json_dict(run_record_path(root, task_id))
        if not record:
            raise RuntimeError("task run not found")
        record.update(dict(patch or {}))
        record["updated_at"] = str((patch or {}).get("updated_at") or _now_ts())
        _write_json(run_record_path(root, task_id), record)
        _sync_task_run_index(root, task_id)
        return record


def mark_task_run_status(root: Path, task_id: str, status: str, *, started_at: str | None = None) -> None:
    patch: dict[str, Any] = {"status": status}
    if started_at:
        current = _load_json_dict(run_record_path(root, task_id))
        if not str(current.get("start_at") or ""):
            patch["start_at"] = started_at
    update_task_run_record(root, task_id, patch)


def write_task_run_summary(
    root: Path,
    task_id: str,
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
    path = run_summary_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"# Task Run - {task_id}",
                "",
                f"- task_id: {task_id}",
                f"- session_id: {session_id}",
                f"- agent_name: {agent_name}",
                f"- agent_search_root: {agent_search_root}",
                f"- status: {status}",
                f"- start_at: {start_at}",
                f"- end_at: {end_at}",
                f"- duration_ms: {duration_ms}",
                f"- command: {' '.join(command_display)}",
                "",
                "## Summary",
                summary or "none",
                "",
                "## STDOUT",
                stdout_text or "",
                "",
                "## STDERR",
                stderr_text or "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path.as_posix()


def update_task_run_result_files(
    root: Path,
    task_id: str,
    *,
    stdout_text: str,
    stderr_text: str,
    trace_payload: dict[str, Any] | None = None,
) -> None:
    paths = task_run_paths(root, task_id)
    paths["stdout"].write_text(stdout_text or "", encoding="utf-8")
    paths["stderr"].write_text(stderr_text or "", encoding="utf-8")
    if isinstance(trace_payload, dict) and trace_payload:
        _write_json(paths["trace"], trace_payload)


def load_task_trace_payload(root: Path, task_id: str) -> dict[str, Any]:
    return _load_json_dict(run_trace_path(root, task_id))


def append_task_run_event_record(root: Path, task_id: str, payload: dict[str, Any]) -> int:
    ensure_store(root)
    with _STORE_LOCK:
        record = _load_json_dict(run_record_path(root, task_id))
        if not record:
            raise RuntimeError("task run not found")
        next_id = int(record.get("event_seq") or 0) + 1
        row_payload = dict(payload.get("payload") or {})
        if row_payload.get("ref"):
            row_payload["ref"] = normalize_work_record_ref(
                root,
                str(row_payload.get("ref") or ""),
                task_id=task_id,
            )
        row = {
            "event_id": next_id,
            "timestamp": str(payload.get("timestamp") or _now_ts()),
            "event_type": str(payload.get("event_type") or ""),
            "payload": row_payload,
        }
        _append_jsonl(run_events_path(root, task_id), row)
        record["event_seq"] = next_id
        record["updated_at"] = row["timestamp"]
        _write_json(run_record_path(root, task_id), record)
        _sync_task_run_index(root, task_id)
        return next_id


def list_task_run_event_records(root: Path, task_id: str, *, since_id: int = 0, limit: int = 400) -> list[dict[str, Any]]:
    rows = _load_jsonl(run_events_path(root, task_id))
    rows = [row for row in rows if int(row.get("event_id") or 0) > int(since_id)]
    rows.sort(key=lambda item: int(item.get("event_id") or 0))
    return rows[: max(1, min(int(limit), 1000))]


def _append_markdown(path: Path, header: str | None, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() and header:
        path.write_text(header + "\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
        handle.write("\n")


from .work_record_store_system import (
    append_change_log_record,
    append_failure_case_record,
    append_message_delete_audit_record,
    append_policy_confirmation_audit_record,
    append_reconcile_run_record,
    append_web_e2e_record,
    append_workflow_event_log_record,
    create_policy_patch_task_record,
    latest_results_indexed,
    latest_policy_patch_task_for_session,
    latest_reconcile_run_record,
    list_ingress_request_records,
    list_policy_patch_task_records,
    list_workflow_event_log_records,
    mark_ingress_request_logged,
    new_sessions_24h_indexed,
    pending_counts_indexed,
    policy_closure_stats_record,
    record_ingress_request,
    unique_system_run_path,
)
from .work_record_store_migration import (
    migrate_legacy_local_work_records,
    normalize_external_work_record_refs,
)
