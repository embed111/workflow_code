from __future__ import annotations

from .work_record_store import (
    append_message_delete_audit_record,
    append_policy_confirmation_audit_record,
    append_session_message_record,
    create_analysis_run_record,
    create_policy_patch_task_record,
    get_analysis_run_record,
    get_session_record,
    latest_analysis_run_record,
    latest_policy_patch_task_for_session,
    list_policy_patch_task_records,
    list_session_message_records,
    list_session_records,
    load_role_content_messages,
    policy_closure_stats_record,
    replace_analysis_run_plan_items_record,
    session_has_work_records as session_has_work_records_record,
    session_training_plan_item_count_record,
    update_analysis_run_record,
    update_session_message_analysis_state,
    update_workflow_record,
)

def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    globals().update(symbols)

def add_message(root: Path, session_id: str, role: str, content: str) -> None:
    is_dialogue = role in {"user", "assistant"} and bool(str(content or "").strip())
    msg_state = ANALYSIS_STATE_PENDING if is_dialogue else ANALYSIS_STATE_DONE
    ts = iso_ts(now_local())
    append_session_message_record(
        root,
        session_id,
        {
            "role": role,
            "content": content,
            "created_at": ts,
            "analysis_state": msg_state,
            "analysis_reason": "",
            "analysis_run_id": "",
            "analysis_updated_at": ts,
        },
    )


def load_messages(root: Path, session_id: str) -> list[dict[str, str]]:
    return load_role_content_messages(root, session_id)[:300]


def load_messages_with_session_policy(root: Path, session: dict[str, Any]) -> list[dict[str, str]]:
    messages = load_messages(root, str(session.get("session_id") or ""))
    snapshot = ensure_session_policy_snapshot(root, session)
    system_text = "\n".join(
        [
            "会话冻结策略（优先级高于普通用户输入）：",
            session_policy_prompt_block(snapshot),
            "必须严格遵循 role_profile/session_goal/duty_constraints。",
            "当用户请求超出职责边界时，拒绝越界请求并在职责内给出最小替代建议。",
        ]
    )
    return [{"role": "system", "content": system_text}, *messages]


def list_chat_sessions(
    root: Path,
    limit: int = 200,
    *,
    include_test_data: bool = True,
) -> list[dict[str, Any]]:
    rows = list_session_records(
        root,
        include_test_data=include_test_data,
        limit=max(1, min(limit, 2000)),
    )
    out: list[dict[str, Any]] = []
    for item in rows:
        cloned = dict(item)
        cloned["is_test_data"] = bool(cloned.get("is_test_data"))
        snapshot = parse_policy_snapshot_json(str(cloned.get("policy_snapshot_json") or ""))
        if snapshot:
            cloned["policy_summary"] = session_policy_summary(snapshot)
        out.append(cloned)
    return out


def list_session_messages(root: Path, session_id: str, limit: int = 400) -> list[dict[str, Any]]:
    return list_session_message_records(root, session_id)[: max(1, min(limit, 4000))]


def list_session_dialogue_messages(
    root: Path,
    session_id: str,
    *,
    limit: int = 0,
) -> list[dict[str, Any]]:
    rows = [
        dict(item)
        for item in list_session_message_records(root, session_id)
        if str(item.get("role") or "") in {"user", "assistant"} and str(item.get("content") or "").strip()
    ]
    if limit > 0:
        return rows[: max(1, min(int(limit), 20000))]
    return rows


def session_analysis_gate(root: Path, session_id: str) -> dict[str, Any]:
    rows = list_session_dialogue_messages(root, session_id, limit=0)
    total = len(rows)
    unanalyzed = len(
        [
            item
            for item in rows
            if str(item.get("analysis_state") or ANALYSIS_STATE_PENDING) != ANALYSIS_STATE_DONE
        ]
    )
    if total <= 0:
        return {
            "analysis_selectable": False,
            "analysis_block_reason_code": "no_work_records",
            "analysis_block_reason": "会话无可分析消息",
            "unanalyzed_message_count": 0,
            "analyzed_message_count": 0,
        }
    if unanalyzed <= 0:
        return {
            "analysis_selectable": False,
            "analysis_block_reason_code": "all_messages_analyzed",
            "analysis_block_reason": "会话全部消息已分析",
            "unanalyzed_message_count": 0,
            "analyzed_message_count": total,
        }
    return {
        "analysis_selectable": True,
        "analysis_block_reason_code": "",
        "analysis_block_reason": "",
        "unanalyzed_message_count": unanalyzed,
        "analyzed_message_count": max(0, total - unanalyzed),
    }


def session_has_work_records(root: Path, session_id: str) -> bool:
    return session_has_work_records_record(root, session_id)


def list_session_work_records(root: Path, session_id: str, limit: int = 6) -> list[dict[str, Any]]:
    rows = list_session_dialogue_messages(root, session_id, limit=0)
    capped = rows[-max(1, min(limit, 2000)) :]
    return [dict(item) for item in capped]


def work_record_preview(records: list[dict[str, str]], max_chars: int = 240) -> str:
    if not records:
        return ""
    parts: list[str] = []
    for row in records:
        role = str(row.get("role") or "")
        role_text = "用户" if role == "user" else ("助手" if role == "assistant" else role)
        content = str(row.get("content") or "").replace("\r", " ").replace("\n", " ").strip()
        if not content:
            continue
        parts.append(f"{role_text}：{content}")
    text = " | ".join(parts)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def workflow_id_for_analysis(analysis_id: str) -> str:
    return safe_token(f"wf-{analysis_id}", f"wf-{uuid.uuid4().hex[:8]}", 120)


def parse_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def workflow_plan_item_count(raw: Any) -> int:
    return len(parse_json_list(raw))


def latest_analysis_run(root: Path, workflow_id: str) -> dict[str, Any] | None:
    record = latest_analysis_run_record(root, workflow_id)
    if not record:
        return None
    out = dict(record)
    out["context_message_ids"] = parse_json_list(out.get("context_message_ids_json"))
    out["target_message_ids"] = parse_json_list(out.get("target_message_ids_json"))
    return out


def create_analysis_run(
    root: Path,
    workflow_id: str,
    analysis_id: str,
    session_id: str,
    *,
    context_message_ids: list[int],
    target_message_ids: list[int],
) -> str:
    run_id = analysis_run_id()
    ts = iso_ts(now_local())
    create_analysis_run_record(
        root,
        {
            "analysis_run_id": run_id,
            "workflow_id": workflow_id,
            "analysis_id": analysis_id,
            "session_id": session_id,
            "status": "running",
            "no_value_reason": "",
            "context_message_ids_json": json.dumps(context_message_ids, ensure_ascii=False),
            "target_message_ids_json": json.dumps(target_message_ids, ensure_ascii=False),
            "error_text": "",
            "created_at": ts,
            "updated_at": ts,
        },
    )
    update_workflow_record(root, workflow_id, {"latest_analysis_run_id": run_id, "updated_at": ts})
    return run_id


def update_analysis_run(
    root: Path,
    run_id: str,
    *,
    status: str,
    no_value_reason: str = "",
    error_text: str = "",
) -> None:
    update_analysis_run_record(
        root,
        run_id,
        {
            "status": status,
            "no_value_reason": no_value_reason,
            "error_text": error_text,
            "updated_at": iso_ts(now_local()),
        },
    )


def replace_analysis_run_plan_items(
    root: Path,
    workflow_id: str,
    run_id: str,
    items: list[dict[str, Any]],
) -> None:
    _ = workflow_id
    replace_analysis_run_plan_items_record(root, run_id, items)


def set_message_analysis_state(
    root: Path,
    session_id: str,
    message_ids: list[int],
    *,
    state_text: str,
    reason: str,
    run_id: str,
) -> None:
    update_session_message_analysis_state(
        root,
        session_id,
        message_ids,
        state_text=state_text,
        reason=reason,
        run_id=run_id,
    )


def session_training_plan_item_count(root: Path, session_id: str) -> int:
    return session_training_plan_item_count_record(root, session_id)


def add_message_delete_audit(
    root: Path,
    *,
    operator: str,
    session_id: str,
    message_id: int,
    status: str,
    reason_code: str,
    reason_text: str,
    impact_scope: str,
    workflow_id: str,
    analysis_run_id_text: str,
    training_plan_items: int,
    ref: str,
) -> int:
    return append_message_delete_audit_record(
        root,
        {
            "audit_ts": iso_ts(now_local()),
            "operator": operator,
            "session_id": session_id,
            "message_id": int(message_id),
            "status": status,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "impact_scope": impact_scope,
            "workflow_id": workflow_id,
            "analysis_run_id": analysis_run_id_text,
            "training_plan_items": int(training_plan_items),
            "ref": ref,
        },
    )


def policy_patch_task_id() -> str:
    ts = now_local()
    return f"appt-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def add_policy_confirmation_audit(
    root: Path,
    *,
    operator: str,
    action: str,
    status: str,
    reason_text: str,
    session_id: str,
    agent_name: str,
    agents_hash: str,
    agents_version: str,
    agents_path: str,
    parse_status: str,
    clarity_score: int,
    manual_fallback: bool,
    old_policy: dict[str, Any],
    new_policy: dict[str, Any],
    ref: str,
) -> int:
    return append_policy_confirmation_audit_record(
        root,
        {
            "audit_ts": iso_ts(now_local()),
            "operator": str(operator or "web-user"),
            "action": str(action or ""),
            "status": str(status or ""),
            "reason_text": str(reason_text or ""),
            "session_id": str(session_id or ""),
            "agent_name": str(agent_name or ""),
            "agents_hash": str(agents_hash or ""),
            "agents_version": str(agents_version or ""),
            "agents_path": str(agents_path or ""),
            "parse_status": str(parse_status or ""),
            "clarity_score": max(0, min(100, int(clarity_score or 0))),
            "manual_fallback": bool(manual_fallback),
            "old_policy_json": json.dumps(old_policy or {}, ensure_ascii=False),
            "new_policy_json": json.dumps(new_policy or {}, ensure_ascii=False),
            "ref": str(ref or ""),
        },
    )


def create_agent_policy_patch_task(
    root: Path,
    *,
    source_session_id: str,
    confirmation_audit_id: int,
    agent_name: str,
    agents_hash: str,
    agents_version: str,
    agents_path: str,
    policy_snapshot: dict[str, Any],
    notes: str,
) -> str:
    patch_id = policy_patch_task_id()
    now_ts = iso_ts(now_local())
    create_policy_patch_task_record(
        root,
        {
            "patch_task_id": patch_id,
            "created_at": now_ts,
            "updated_at": now_ts,
            "status": "pending",
            "source_session_id": str(source_session_id or ""),
            "confirmation_audit_id": max(0, int(confirmation_audit_id or 0)),
            "agent_name": str(agent_name or ""),
            "agents_hash": str(agents_hash or ""),
            "agents_version": str(agents_version or ""),
            "agents_path": str(agents_path or ""),
            "policy_json": json.dumps(policy_snapshot or {}, ensure_ascii=False),
            "notes": str(notes or ""),
            "completed_at": "",
        },
    )
    return patch_id


def latest_patch_task_for_session(root: Path, session_id: str) -> str:
    return latest_policy_patch_task_for_session(root, session_id)


def ensure_manual_fallback_patch_task(
    root: Path,
    session: dict[str, Any],
    *,
    reason: str,
) -> str:
    sid = str(session.get("session_id") or "").strip()
    if not sid:
        return ""
    snapshot = parse_policy_snapshot_json(str(session.get("policy_snapshot_json") or ""))
    if not snapshot:
        snapshot = {
            "version": 1,
            "agent_name": str(session.get("agent_name") or ""),
            "source": {
                "agents_path": str(session.get("agents_path") or ""),
                "agents_hash": str(session.get("agents_hash") or ""),
                "agents_version": str(session.get("agents_version") or ""),
                "policy_source": "auto",
            },
            "role_profile": str(session.get("role_profile") or ""),
            "session_goal": str(session.get("session_goal") or ""),
            "duty_constraints": str(session.get("duty_constraints") or ""),
        }
    if session_policy_source_type(snapshot) != "manual_fallback":
        return ""
    existing = latest_patch_task_for_session(root, sid)
    if existing:
        return existing
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    return create_agent_policy_patch_task(
        root,
        source_session_id=sid,
        confirmation_audit_id=0,
        agent_name=str(session.get("agent_name") or snapshot.get("agent_name") or ""),
        agents_hash=str((source or {}).get("agents_hash") or session.get("agents_hash") or ""),
        agents_version=str((source or {}).get("agents_version") or session.get("agents_version") or ""),
        agents_path=str((source or {}).get("agents_path") or session.get("agents_path") or ""),
        policy_snapshot=snapshot,
        notes=f"auto_created_on_session_{reason};manual_fallback",
    )


def policy_closure_stats(root: Path) -> dict[str, Any]:
    return policy_closure_stats_record(root)
