def get_analysis_record(root: Path, analysis_id: str) -> dict[str, Any] | None:
    ensure_store(root)
    record = _load_json_dict(analysis_record_path(root, analysis_id))
    return record or None


def list_analysis_records(root: Path) -> list[dict[str, Any]]:
    ensure_store(root)
    rows = _record_index.list_analysis_records_from_index(root)
    if rows:
        return rows
    fallback: list[dict[str, Any]] = []
    for path in sorted(analysis_root(root).glob("*/analysis.json"), key=lambda item: item.as_posix().lower()):
        record = _load_json_dict(path)
        if record:
            fallback.append(record)
    fallback.sort(key=lambda item: str(item.get("created_at") or ""))
    return fallback


def upsert_analysis_record(root: Path, analysis_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    with _STORE_LOCK:
        current = _load_json_dict(analysis_record_path(root, analysis_id))
        created_at = str((current or {}).get("created_at") or payload.get("created_at") or _now_ts())
        record = {
            "record_type": "analysis_task",
            "schema_version": _SCHEMA_VERSION,
            "analysis_id": analysis_id,
            "session_id": str(payload.get("session_id") or ((current or {}).get("session_id") if current else "") or ""),
            "source_event_id": str(payload.get("source_event_id") or (current or {}).get("source_event_id") or ""),
            "status": str(payload.get("status") or (current or {}).get("status") or "pending"),
            "decision": str(payload.get("decision") or (current or {}).get("decision") or ""),
            "decision_reason": str(payload.get("decision_reason") or (current or {}).get("decision_reason") or ""),
            "created_at": created_at,
            "updated_at": str(payload.get("updated_at") or _now_ts()),
        }
        _write_json(analysis_record_path(root, analysis_id), record)
        _sync_analysis_index(root, analysis_id)
        return record


def sync_analysis_records_from_sessions(root: Path) -> int:
    ensure_store(root)
    created = 0
    for session in list_session_records(root, include_test_data=True, limit=100000):
        session_id = str(session.get("session_id") or "")
        if not session_id or not session_has_work_records(root, session_id):
            continue
        analysis_id = f"ana-{session_id}"
        if get_analysis_record(root, analysis_id):
            continue
        messages = list_session_message_records(root, session_id)
        first = next(
            (
                item
                for item in messages
                if str(item.get("role") or "") == "user" and str(item.get("content") or "").strip()
            ),
            messages[0] if messages else None,
        )
        source_event_id = f"msg:{session_id}:{int(first.get('message_id') or 0)}" if first else f"msg:{session_id}:0"
        created_at = str((first or {}).get("created_at") or session.get("created_at") or _now_ts())
        upsert_analysis_record(
            root,
            analysis_id,
            {
                "session_id": session_id,
                "source_event_id": source_event_id,
                "status": "pending",
                "created_at": created_at,
                "updated_at": _now_ts(),
            },
        )
        created += 1
    return created


def _workflow_record_for_analysis(root: Path, analysis_id: str) -> dict[str, Any]:
    return _load_json_dict(workflow_record_path(root, analysis_id))


def list_workflow_records(root: Path) -> list[dict[str, Any]]:
    ensure_store(root)
    rows = _record_index.list_workflow_records_from_index(root)
    if rows:
        return rows
    fallback: list[dict[str, Any]] = []
    for path in sorted(analysis_root(root).glob("*/workflow.json"), key=lambda item: item.as_posix().lower()):
        record = _load_json_dict(path)
        if record:
            fallback.append(record)
    fallback.sort(key=lambda item: str(item.get("created_at") or ""))
    return fallback


def get_workflow_record(root: Path, workflow_id: str) -> dict[str, Any] | None:
    ensure_store(root)
    workflow_id_text = str(workflow_id or "").strip()
    analysis_id = _record_index.find_analysis_id_by_workflow_id(root, workflow_id_text)
    if analysis_id:
        record = _load_json_dict(workflow_record_path(root, analysis_id))
        if record:
            return record
    for record in list_workflow_records(root):
        if str(record.get("workflow_id") or "") == workflow_id_text:
            return record
    return None


def ensure_workflow_record(root: Path, workflow_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    ensure_store(root)
    analysis_id = str(payload.get("analysis_id") or "")
    if not analysis_id:
        raise RuntimeError("analysis_id required")
    with _STORE_LOCK:
        current = _workflow_record_for_analysis(root, analysis_id)
        if current and str(current.get("workflow_id") or "") == workflow_id:
            return current, False
        created_at = str((current or {}).get("created_at") or payload.get("created_at") or _now_ts())
        record = {
            "record_type": "training_workflow",
            "schema_version": _SCHEMA_VERSION,
            "workflow_id": workflow_id,
            "analysis_id": analysis_id,
            "session_id": str(payload.get("session_id") or (current or {}).get("session_id") or ""),
            "status": str(payload.get("status") or (current or {}).get("status") or "queued"),
            "assigned_analyst": str(payload.get("assigned_analyst") or (current or {}).get("assigned_analyst") or ""),
            "assignment_note": str(payload.get("assignment_note") or (current or {}).get("assignment_note") or ""),
            "analysis_summary": str(payload.get("analysis_summary") or (current or {}).get("analysis_summary") or ""),
            "analysis_recommendation": str(payload.get("analysis_recommendation") or (current or {}).get("analysis_recommendation") or ""),
            "plan_json": str(payload.get("plan_json") or (current or {}).get("plan_json") or "[]"),
            "selected_plan_json": str(payload.get("selected_plan_json") or (current or {}).get("selected_plan_json") or "[]"),
            "train_result_ref": normalize_work_record_ref(
                root,
                str(payload.get("train_result_ref") or (current or {}).get("train_result_ref") or ""),
                analysis_id=analysis_id,
            ),
            "train_result_summary": str(payload.get("train_result_summary") or (current or {}).get("train_result_summary") or ""),
            "latest_analysis_run_id": str(payload.get("latest_analysis_run_id") or (current or {}).get("latest_analysis_run_id") or ""),
            "latest_no_value_reason": str(payload.get("latest_no_value_reason") or (current or {}).get("latest_no_value_reason") or ""),
            "event_seq": int(payload.get("event_seq") or (current or {}).get("event_seq") or 0),
            "created_at": created_at,
            "updated_at": str(payload.get("updated_at") or _now_ts()),
        }
        _write_json(workflow_record_path(root, analysis_id), record)
        _sync_analysis_index(root, analysis_id)
        return record, not bool(current)


def update_workflow_record(root: Path, workflow_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    workflow = get_workflow_record(root, workflow_id)
    if not workflow:
        raise RuntimeError("workflow not found")
    analysis_id = str(workflow.get("analysis_id") or "")
    with _STORE_LOCK:
        workflow.update(dict(patch or {}))
        workflow["updated_at"] = str((patch or {}).get("updated_at") or _now_ts())
        _write_json(workflow_record_path(root, analysis_id), workflow)
        _sync_analysis_index(root, analysis_id)
        return workflow


def append_workflow_event_record(root: Path, workflow_id: str, payload: dict[str, Any]) -> int:
    ensure_store(root)
    workflow = get_workflow_record(root, workflow_id)
    if not workflow:
        raise RuntimeError("workflow not found")
    analysis_id = str(workflow.get("analysis_id") or "")
    with _STORE_LOCK:
        current = _workflow_record_for_analysis(root, analysis_id)
        next_id = int(current.get("event_seq") or 0) + 1
        row = dict(payload or {})
        row["event_id"] = next_id
        _append_jsonl(analysis_workflow_events_path(root, analysis_id), row)
        current["event_seq"] = next_id
        current["updated_at"] = str(row.get("created_at") or _now_ts())
        _write_json(workflow_record_path(root, analysis_id), current)
        _sync_analysis_index(root, analysis_id)
        return next_id


def list_workflow_event_records(root: Path, workflow_id: str, *, since_id: int = 0, limit: int = 400) -> list[dict[str, Any]]:
    workflow = get_workflow_record(root, workflow_id)
    if not workflow:
        return []
    analysis_id = str(workflow.get("analysis_id") or "")
    rows = _load_jsonl(analysis_workflow_events_path(root, analysis_id))
    rows = [row for row in rows if int(row.get("event_id") or 0) > int(since_id)]
    rows.sort(key=lambda item: int(item.get("event_id") or 0))
    return rows[: max(1, min(int(limit), 2000))]


def _analysis_id_for_run(root: Path, analysis_run_id: str) -> str:
    run_id_text = str(analysis_run_id or "").strip()
    if not run_id_text:
        return ""
    indexed = _record_index.find_analysis_id_for_run(root, run_id_text)
    if indexed:
        return indexed
    for path in analysis_root(root).glob("*/runs/*.json"):
        if path.stem == run_id_text:
            return path.parent.parent.name
    return ""


def create_analysis_run_record(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    analysis_id = str(payload.get("analysis_id") or "")
    run_id = str(payload.get("analysis_run_id") or "")
    if not analysis_id or not run_id:
        raise RuntimeError("analysis_id/analysis_run_id required")
    with _STORE_LOCK:
        record = {
            "record_type": "analysis_run",
            "schema_version": _SCHEMA_VERSION,
            "analysis_run_id": run_id,
            "workflow_id": str(payload.get("workflow_id") or ""),
            "analysis_id": analysis_id,
            "session_id": str(payload.get("session_id") or ""),
            "status": str(payload.get("status") or "running"),
            "no_value_reason": str(payload.get("no_value_reason") or ""),
            "context_message_ids_json": str(payload.get("context_message_ids_json") or "[]"),
            "target_message_ids_json": str(payload.get("target_message_ids_json") or "[]"),
            "error_text": str(payload.get("error_text") or ""),
            "plan_items": list(payload.get("plan_items") or []),
            "created_at": str(payload.get("created_at") or _now_ts()),
            "updated_at": str(payload.get("updated_at") or payload.get("created_at") or _now_ts()),
        }
        _write_json(analysis_run_record_path(root, analysis_id, run_id), record)
        _sync_analysis_index(root, analysis_id)
        return record


def get_analysis_run_record(root: Path, analysis_run_id: str) -> dict[str, Any] | None:
    ensure_store(root)
    analysis_id = _analysis_id_for_run(root, analysis_run_id)
    if not analysis_id:
        return None
    record = _load_json_dict(analysis_run_record_path(root, analysis_id, analysis_run_id))
    return record or None


def update_analysis_run_record(root: Path, analysis_run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    analysis_id = _analysis_id_for_run(root, analysis_run_id)
    if not analysis_id:
        raise RuntimeError("analysis run not found")
    with _STORE_LOCK:
        record = _load_json_dict(analysis_run_record_path(root, analysis_id, analysis_run_id))
        if not record:
            raise RuntimeError("analysis run not found")
        record.update(dict(patch or {}))
        record["updated_at"] = str((patch or {}).get("updated_at") or _now_ts())
        _write_json(analysis_run_record_path(root, analysis_id, analysis_run_id), record)
        _sync_analysis_index(root, analysis_id)
        return record


def latest_analysis_run_record(root: Path, workflow_id: str) -> dict[str, Any] | None:
    workflow = get_workflow_record(root, workflow_id)
    if not workflow:
        return None
    latest_id = str(workflow.get("latest_analysis_run_id") or "")
    if latest_id:
        latest = get_analysis_run_record(root, latest_id)
        if latest:
            return latest
    analysis_id = str(workflow.get("analysis_id") or "")
    indexed = _record_index.latest_analysis_run_record_from_index(root, analysis_id)
    if indexed:
        return indexed
    rows = [
        _load_json_dict(path)
        for path in sorted(analysis_runs_root(root, analysis_id).glob("*.json"), key=lambda item: item.as_posix().lower())
    ]
    rows = [row for row in rows if row]
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows[0] if rows else None


def replace_analysis_run_plan_items_record(root: Path, analysis_run_id: str, items: list[dict[str, Any]]) -> None:
    record = get_analysis_run_record(root, analysis_run_id)
    if not record:
        return
    update_analysis_run_record(root, analysis_run_id, {"plan_items": list(items or [])})


def get_training_task_record(root: Path, analysis_id: str) -> dict[str, Any] | None:
    ensure_store(root)
    record = _load_json_dict(training_record_path(root, analysis_id))
    return record or None


def upsert_training_task_record(root: Path, analysis_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    with _STORE_LOCK:
        current = _load_json_dict(training_record_path(root, analysis_id))
        created_at = str((current or {}).get("created_at") or payload.get("created_at") or _now_ts())
        record = {
            "record_type": "training_task",
            "schema_version": _SCHEMA_VERSION,
            "training_id": str(payload.get("training_id") or (current or {}).get("training_id") or ""),
            "analysis_id": analysis_id,
            "status": str(payload.get("status") or (current or {}).get("status") or "pending"),
            "result_summary": str(payload.get("result_summary") or (current or {}).get("result_summary") or ""),
            "trainer_run_ref": normalize_work_record_ref(
                root,
                str(payload.get("trainer_run_ref") or (current or {}).get("trainer_run_ref") or ""),
                analysis_id=analysis_id,
            ),
            "attempts": int(payload.get("attempts") or (current or {}).get("attempts") or 0),
            "last_error": str(payload.get("last_error") or (current or {}).get("last_error") or ""),
            "created_at": created_at,
            "updated_at": str(payload.get("updated_at") or _now_ts()),
        }
        _write_json(training_record_path(root, analysis_id), record)
        _sync_analysis_index(root, analysis_id)
        return record


def update_training_task_record(root: Path, analysis_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    return upsert_training_task_record(root, analysis_id, patch)


def session_training_plan_item_count_record(root: Path, session_id: str) -> int:
    count = 0
    for analysis in list_analysis_records(root):
        if str(analysis.get("session_id") or "") != str(session_id or ""):
            continue
        workflow = _workflow_record_for_analysis(root, str(analysis.get("analysis_id") or ""))
        count = max(count, len(_parse_json_list(workflow.get("plan_json"))))
        count = max(count, len(_parse_json_list(workflow.get("selected_plan_json"))))
        latest_id = str(workflow.get("latest_analysis_run_id") or "")
        run = get_analysis_run_record(root, latest_id) if latest_id else None
        count = max(count, len(list((run or {}).get("plan_items") or [])))
    return count


