def get_session_record(root: Path, session_id: str) -> dict[str, Any] | None:
    ensure_store(root)
    record = _load_json_dict(session_record_path(root, session_id))
    return record or None


def create_or_load_session_record(root: Path, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    ensure_store(root)
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise RuntimeError("session_id required")
    with _STORE_LOCK:
        existing = _load_json_dict(session_record_path(root, session_id))
        if existing:
            return existing, False
        now_text = str(payload.get("created_at") or _now_ts())
        record = {
            "record_type": "chat_session",
            "schema_version": _SCHEMA_VERSION,
            "session_id": session_id,
            "agent_name": str(payload.get("agent_name") or ""),
            "agents_hash": str(payload.get("agents_hash") or ""),
            "agents_loaded_at": str(payload.get("agents_loaded_at") or now_text),
            "agents_path": str(payload.get("agents_path") or ""),
            "agents_version": str(payload.get("agents_version") or ""),
            "role_profile": str(payload.get("role_profile") or ""),
            "session_goal": str(payload.get("session_goal") or ""),
            "duty_constraints": str(payload.get("duty_constraints") or ""),
            "policy_snapshot_json": str(payload.get("policy_snapshot_json") or "{}"),
            "agent_search_root": str(payload.get("agent_search_root") or ""),
            "target_path": str(payload.get("target_path") or ""),
            "is_test_data": bool(payload.get("is_test_data")),
            "status": str(payload.get("status") or "active"),
            "closed_at": str(payload.get("closed_at") or ""),
            "closed_reason": str(payload.get("closed_reason") or ""),
            "created_at": now_text,
            "updated_at": now_text,
            "message_seq": 0,
            "message_count": 0,
            "work_record_count": 0,
            "last_message": "",
            "last_message_at": "",
        }
        _write_json(session_record_path(root, session_id), record)
        _sync_session_index(root, session_id)
        return record, True


def update_session_record(root: Path, session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    with _STORE_LOCK:
        record = _load_json_dict(session_record_path(root, session_id))
        if not record:
            raise RuntimeError("session not found")
        record.update(dict(patch or {}))
        record["updated_at"] = str((patch or {}).get("updated_at") or _now_ts())
        _write_json(session_record_path(root, session_id), record)
        _sync_session_index(root, session_id)
        return record


def list_session_records(root: Path, *, include_test_data: bool = True, limit: int = 200) -> list[dict[str, Any]]:
    ensure_store(root)
    items = _record_index.list_session_records_from_index(root, include_test_data=include_test_data, limit=limit)
    if items:
        return items
    fallback: list[dict[str, Any]] = []
    for path in sorted(sessions_root(root).glob("*/session.json"), key=lambda item: item.as_posix().lower()):
        record = _load_json_dict(path)
        if not record:
            continue
        if not include_test_data and _normalize_bool(record.get("is_test_data")):
            continue
        fallback.append(record)
    fallback.sort(
        key=lambda item: (
            0 if str(item.get("status") or "active") == "active" else 1,
            str(item.get("last_message_at") or item.get("created_at") or ""),
        ),
        reverse=True,
    )
    return fallback[: max(1, min(int(limit), 2000))]


def list_active_session_records(root: Path, limit: int = 500) -> list[dict[str, Any]]:
    items = [item for item in list_session_records(root, include_test_data=True, limit=max(1, limit * 4)) if str(item.get("status") or "active") == "active"]
    return items[: max(1, min(int(limit), 5000))]


def _refresh_session_counters(root: Path, session_id: str, record: dict[str, Any] | None = None) -> dict[str, Any]:
    current = dict(record or _load_json_dict(session_record_path(root, session_id)))
    messages = list_session_message_records(root, session_id)
    current["message_seq"] = max([int(item.get("message_id") or 0) for item in messages] or [0])
    current["message_count"] = len(messages)
    current["work_record_count"] = len(
        [
            item
            for item in messages
            if str(item.get("role") or "") in _USER_MESSAGE_ROLES
            and str(item.get("content") or "").strip()
        ]
    )
    if messages:
        latest = messages[-1]
        current["last_message"] = str(latest.get("content") or "")
        current["last_message_at"] = str(latest.get("created_at") or "")
    else:
        current["last_message"] = ""
        current["last_message_at"] = ""
    current["updated_at"] = _now_ts()
    _write_json(session_record_path(root, session_id), current)
    _sync_session_index(root, session_id)
    return current


def append_session_message_record(root: Path, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    with _STORE_LOCK:
        record = _load_json_dict(session_record_path(root, session_id))
        if not record:
            raise RuntimeError("session not found")
        rows = _load_jsonl(session_messages_path(root, session_id))
        next_id = max([int(item.get("message_id") or 0) for item in rows] or [0]) + 1
        row = {
            "record_type": "conversation_message",
            "schema_version": _SCHEMA_VERSION,
            "message_id": next_id,
            "session_id": session_id,
            "role": str(payload.get("role") or ""),
            "content": str(payload.get("content") or ""),
            "created_at": str(payload.get("created_at") or _now_ts()),
            "analysis_state": str(payload.get("analysis_state") or ""),
            "analysis_reason": str(payload.get("analysis_reason") or ""),
            "analysis_run_id": str(payload.get("analysis_run_id") or ""),
            "analysis_updated_at": str(payload.get("analysis_updated_at") or payload.get("created_at") or _now_ts()),
        }
        rows.append(row)
        _write_jsonl(session_messages_path(root, session_id), rows)
        _refresh_session_counters(root, session_id, record)
        return row


def list_session_message_records(root: Path, session_id: str) -> list[dict[str, Any]]:
    ensure_store(root)
    rows = _load_jsonl(session_messages_path(root, session_id))
    rows.sort(key=lambda item: int(item.get("message_id") or 0))
    return rows


def load_role_content_messages(root: Path, session_id: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in list_session_message_records(root, session_id):
        role = str(item.get("role") or "")
        if role in {"system", "user", "assistant"}:
            out.append({"role": role, "content": str(item.get("content") or "")})
    return out


def update_session_message_analysis_state(
    root: Path,
    session_id: str,
    message_ids: list[int],
    *,
    state_text: str,
    reason: str,
    run_id: str,
) -> None:
    ensure_store(root)
    lookup = {int(item) for item in message_ids if int(item) > 0}
    if not lookup:
        return
    with _STORE_LOCK:
        rows = _load_jsonl(session_messages_path(root, session_id))
        now_text = _now_ts()
        changed = False
        for row in rows:
            if int(row.get("message_id") or 0) not in lookup:
                continue
            row["analysis_state"] = state_text
            row["analysis_reason"] = reason
            row["analysis_run_id"] = run_id
            row["analysis_updated_at"] = now_text
            changed = True
        if changed:
            _write_jsonl(session_messages_path(root, session_id), rows)
            _refresh_session_counters(root, session_id)


def delete_session_message_record(root: Path, session_id: str, message_id: int) -> bool:
    ensure_store(root)
    with _STORE_LOCK:
        rows = _load_jsonl(session_messages_path(root, session_id))
        filtered = [row for row in rows if int(row.get("message_id") or 0) != int(message_id)]
        if len(filtered) == len(rows):
            return False
        _write_jsonl(session_messages_path(root, session_id), filtered)
        _refresh_session_counters(root, session_id)
        return True


def session_has_work_records(root: Path, session_id: str) -> bool:
    return any(
        str(item.get("role") or "") in _USER_MESSAGE_ROLES and str(item.get("content") or "").strip()
        for item in list_session_message_records(root, session_id)
    )


def session_work_record_count(root: Path, session_id: str) -> int:
    return len(
        [
            item
            for item in list_session_message_records(root, session_id)
            if str(item.get("role") or "") in _USER_MESSAGE_ROLES
            and str(item.get("content") or "").strip()
        ]
    )


def last_user_message_text(root: Path, session_id: str) -> str:
    for item in reversed(list_session_message_records(root, session_id)):
        if str(item.get("role") or "") == "user":
            return str(item.get("content") or "")
    return ""


