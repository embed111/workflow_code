from __future__ import annotations

from .work_record_store import (
    create_or_load_session_record,
    get_session_record,
    list_active_session_records,
    update_session_record as update_work_record_session,
)

def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    globals().update(symbols)

def get_session(root: Path, session_id: str) -> dict[str, Any] | None:
    record = get_session_record(root, session_id)
    if not record:
        return None
    record["is_test_data"] = bool(record.get("is_test_data"))
    return record


def create_session_record(
    root: Path,
    session_id: str,
    agent_name: str,
    agents_hash: str,
    agents_loaded_at: str,
    agents_path: str,
    agents_version: str,
    agent_search_root: str,
    target_path: str,
    *,
    role_profile: str = "",
    session_goal: str = "",
    duty_constraints: str = "",
    policy_snapshot_json: str = "{}",
    is_test_data: bool = False,
) -> tuple[dict[str, Any], bool]:
    record, created = create_or_load_session_record(
        root,
        {
            "session_id": session_id,
            "agent_name": agent_name,
            "agents_hash": agents_hash,
            "agents_loaded_at": agents_loaded_at,
            "agents_path": agents_path,
            "agents_version": agents_version,
            "agent_search_root": agent_search_root,
            "target_path": target_path,
            "role_profile": role_profile,
            "session_goal": session_goal,
            "duty_constraints": duty_constraints,
            "policy_snapshot_json": policy_snapshot_json,
            "is_test_data": bool(is_test_data),
            "status": "active",
            "created_at": iso_ts(now_local()),
        },
    )
    record["is_test_data"] = bool(record.get("is_test_data"))
    return record, created


def append_session_init_event(root: Path, session: dict[str, str]) -> None:
    persist_event(
        root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(now_local()),
            "session_id": session["session_id"],
            "actor": "workflow",
            "stage": "chat",
            "action": "session_init",
            "status": "success",
            "latency_ms": 0,
            "task_id": session["session_id"],
            "reason_tags": [
                f"agent:{session['agent_name']}",
                f"agents_hash:{session['agents_hash'][:12]}",
                f"agents_version:{session.get('agents_version','')}",
                f"policy_alignment:{POLICY_ALIGNMENT_ALIGNED}",
                f"agent_search_root:{session['agent_search_root']}",
                f"is_test_data:{int(bool(session.get('is_test_data')))}",
            ],
            "ref": relative_to_root(root, event_file(root)),
        },
    )


def create_session_with_policy_snapshot(
    cfg: AppConfig,
    *,
    session_id: str,
    selected_agent: dict[str, Any],
    policy_snapshot: dict[str, Any],
    agent_search_root: str,
    requested_is_test_data: bool,
) -> tuple[dict[str, Any], bool]:
    sid = safe_token(session_id, "", 140)
    if not sid:
        sid = new_session_id()
    scope_path = str(agent_search_root or "").strip() or agent_search_root_text(cfg.agent_search_root)
    if not scope_path:
        raise SessionGateError(
            409,
            agent_search_root_block_message(AGENT_SEARCH_ROOT_NOT_SET_CODE),
            AGENT_SEARCH_ROOT_NOT_SET_CODE,
        )
    session, created = create_session_record(
        cfg.root,
        session_id=sid,
        agent_name=str(selected_agent.get("agent_name") or ""),
        agents_hash=str(selected_agent.get("agents_hash") or ""),
        agents_loaded_at=str(selected_agent.get("agents_loaded_at") or iso_ts(now_local())),
        agents_path=str(selected_agent.get("agents_md_path") or ""),
        agents_version=str(selected_agent.get("agents_version") or str(selected_agent.get("agents_hash") or "")[:12]),
        role_profile=str(policy_snapshot.get("role_profile") or ""),
        session_goal=str(policy_snapshot.get("session_goal") or ""),
        duty_constraints=str(policy_snapshot.get("duty_constraints") or ""),
        policy_snapshot_json=json.dumps(policy_snapshot, ensure_ascii=False),
        agent_search_root=scope_path,
        target_path=scope_path,
        is_test_data=requested_is_test_data,
    )
    ensure_session_policy_snapshot(cfg.root, session)
    if session["agent_name"] != str(selected_agent.get("agent_name") or ""):
        raise SessionGateError(
            409,
            f"session id already pinned to different agent={session['agent_name']}",
            "session_id_conflict",
        )
    if created:
        append_session_init_event(cfg.root, session)
        append_change_log(
            cfg.root,
            "session init",
            (
                f"session_id={session['session_id']}, agent={session['agent_name']}, "
                f"agents_hash={session['agents_hash'][:12]}, agents_version={session.get('agents_version','')}, "
                f"agent_search_root={session['agent_search_root']}, is_test_data={int(bool(session.get('is_test_data')))}"
            ),
        )
    return session, created


def ensure_session(
    cfg: AppConfig,
    state: RuntimeState,
    requested_session_id: str,
    requested_agent_name: str,
    requested_agent_search_root: str,
    requested_is_test_data: bool,
    *,
    allow_create: bool,
) -> tuple[dict[str, Any], bool]:
    session_id = safe_token(requested_session_id, "", 140)
    requested_agent = safe_token(requested_agent_name, "", 80)
    current_root = current_agent_search_root(cfg, state)
    root_ready, root_error = agent_search_root_state(current_root)
    if not root_ready or current_root is None:
        raise SessionGateError(
            409,
            agent_search_root_block_message(root_error),
            root_error or AGENT_SEARCH_ROOT_NOT_SET_CODE,
            extra={"agent_search_root": agent_search_root_text(current_root)},
        )
    if requested_agent_search_root:
        requested_root = normalize_abs_path(requested_agent_search_root, base=cfg.root)
        if requested_root != current_root:
            raise SessionGateError(
                409,
                f"agent_search_root mismatch: current={current_root.as_posix()} requested={requested_root.as_posix()}",
                "agent_search_root_mismatch",
            )
    if session_id:
        existing = get_session(cfg.root, session_id)
        if existing:
            if str(existing.get("status") or "").lower() == "closed":
                raise SessionGateError(409, "session is closed; create a new session", "session_closed")
            if not str(existing.get("agent_search_root") or "").strip():
                existing["agent_search_root"] = str(existing.get("target_path") or current_root.as_posix())
            if not str(existing.get("target_path") or "").strip():
                existing["target_path"] = existing["agent_search_root"]
            if not str(existing.get("agents_version") or "").strip():
                existing["agents_version"] = str(existing.get("agents_hash") or "")[:12]
            if not str(existing.get("agents_path") or "").strip():
                existing["agents_path"] = (
                    normalize_abs_path(existing["agent_search_root"], base=cfg.root)
                    / existing["agent_name"]
                    / "AGENTS.md"
                ).as_posix()
            ensure_session_policy_snapshot(cfg.root, existing)
            if requested_agent and requested_agent != existing["agent_name"]:
                raise SessionGateError(
                    409,
                    f"session is pinned to agent={existing['agent_name']}",
                    "session_agent_mismatch",
                )
            if existing.get("agent_search_root", "") != current_root.as_posix():
                raise SessionGateError(
                    409,
                    f"session root pinned to {existing.get('agent_search_root','')}",
                    "session_root_mismatch",
                )
            return existing, False
        if not allow_create:
            raise SessionGateError(404, "session not found", "session_not_found")

    if not allow_create:
        raise SessionGateError(400, "session_id required", "session_required")
    if not requested_agent:
        raise SessionGateError(400, "agent_name required before creating session", "agent_required")

    agents = list_available_agents(cfg, analyze_policy=False)
    if not agents:
        raise SessionGateError(
            409,
            f"no available agent found under {current_root.as_posix()}",
            "no_agent_found",
        )
    selected_brief = next((item for item in agents if item["agent_name"] == requested_agent), None)
    selected = load_agent_with_policy(cfg, requested_agent)
    if selected is None and selected_brief is not None:
        selected = dict(selected_brief)
    if not selected:
        raise SessionGateError(400, f"agent not available: {requested_agent}", "agent_not_available")
    allow_manual_input = current_allow_manual_policy_input(cfg, state)
    policy_snapshot, policy_error = extract_policy_snapshot_from_agent_item(selected)
    policy_gate_payload = agent_policy_gate_payload(
        selected,
        snapshot=policy_snapshot,
        policy_error=policy_error,
        allow_manual_policy_input=allow_manual_input,
    )
    parse_status = str(selected.get("parse_status") or "failed").strip().lower()
    clarity_score = int(selected.get("clarity_score") or 0)
    clarity_gate = str(selected.get("clarity_gate") or "").strip().lower() or "block"
    if policy_snapshot is None:
        error_code = AGENT_POLICY_OUT_OF_SCOPE_CODE if str(policy_error or "").strip() == AGENT_POLICY_OUT_OF_SCOPE_CODE else AGENT_POLICY_ERROR_CODE
        raise SessionGateError(
            409,
            f"agent policy extract failed: {policy_error}",
            error_code,
            extra={
                "agent_name": requested_agent,
                "agents_path": str(selected.get("agents_md_path") or ""),
                "policy_error": policy_error,
                "policy_confirmation": policy_gate_payload,
            },
        )
    if clarity_gate == "block":
        blocked_code = AGENT_POLICY_CLARITY_BLOCKED_CODE
        blocked_message = (
            f"agent policy clarity blocked: score={clarity_score}, gate={clarity_gate}, parse_status={parse_status}"
        )
        raise SessionGateError(
            409,
            blocked_message,
            blocked_code,
            extra={
                "agent_name": requested_agent,
                "agents_path": str(selected.get("agents_md_path") or ""),
                "clarity_score": clarity_score,
                "clarity_gate": clarity_gate,
                "parse_status": parse_status,
                "policy_confirmation": policy_gate_payload,
            },
        )
    if clarity_gate == "confirm":
        raise SessionGateError(
            409,
            f"agent policy confirmation required: score={clarity_score}, parse_status={parse_status}",
            AGENT_POLICY_CONFIRM_CODE,
            extra={
                "agent_name": requested_agent,
                "agents_path": str(selected.get("agents_md_path") or ""),
                "clarity_score": clarity_score,
                "clarity_gate": clarity_gate,
                "parse_status": parse_status,
                "policy_confirmation": policy_gate_payload,
            },
        )

    session, created = create_session_with_policy_snapshot(
        cfg,
        session_id=session_id or "",
        selected_agent=selected,
        policy_snapshot=policy_snapshot,
        agent_search_root=current_root.as_posix(),
        requested_is_test_data=requested_is_test_data,
    )
    return session, created


def confirm_session_policy_and_create(
    cfg: AppConfig,
    state: RuntimeState,
    *,
    requested_session_id: str,
    requested_agent_name: str,
    requested_agent_search_root: str,
    requested_is_test_data: bool,
    action: str,
    operator: str,
    reason_text: str,
    edited_role_profile: str,
    edited_session_goal: str,
    edited_duty_constraints: Any,
) -> dict[str, Any]:
    current_root = current_agent_search_root(cfg, state)
    root_ready, root_error = agent_search_root_state(current_root)
    if not root_ready or current_root is None:
        raise SessionGateError(
            409,
            agent_search_root_block_message(root_error),
            root_error or AGENT_SEARCH_ROOT_NOT_SET_CODE,
            extra={"agent_search_root": agent_search_root_text(current_root)},
        )
    if requested_agent_search_root:
        requested_root = normalize_abs_path(requested_agent_search_root, base=cfg.root)
        if requested_root != current_root:
            raise SessionGateError(
                409,
                f"agent_search_root mismatch: current={current_root.as_posix()} requested={requested_root.as_posix()}",
                "agent_search_root_mismatch",
            )
    agent_name = safe_token(requested_agent_name, "", 80)
    if not agent_name:
        raise SessionGateError(400, "agent_name required", "agent_required")

    act = safe_token(action, "", 16).lower()
    if act not in {"confirm", "edit", "reject"}:
        raise SessionGateError(400, "invalid policy confirmation action", "invalid_policy_confirmation_action")

    agents = list_available_agents(cfg, analyze_policy=False)
    selected = load_agent_with_policy(cfg, agent_name)
    if selected is None:
        selected = next((item for item in agents if item["agent_name"] == agent_name), None)
    if not selected:
        raise SessionGateError(400, f"agent not available: {agent_name}", "agent_not_available")

    allow_manual_input = current_allow_manual_policy_input(cfg, state)
    policy_snapshot, policy_error = extract_policy_snapshot_from_agent_item(selected)
    gate_payload = agent_policy_gate_payload(
        selected,
        snapshot=policy_snapshot,
        policy_error=policy_error,
        allow_manual_policy_input=allow_manual_input,
    )
    parse_status = str(selected.get("parse_status") or "failed").strip().lower()
    clarity_score = int(selected.get("clarity_score") or 0)
    clarity_gate = str(selected.get("clarity_gate") or "").strip().lower() or "block"
    requires_manual_fallback = bool(
        policy_snapshot is None
        or parse_status == "failed"
        or clarity_score < POLICY_CLARITY_AUTO_THRESHOLD
    )
    manual_fallback_allowed = bool(allow_manual_input)
    if act == "edit" and not manual_fallback_allowed:
        code = MANUAL_POLICY_INPUT_DISABLED_CODE if not allow_manual_input else MANUAL_POLICY_INPUT_NOT_ALLOWED_CODE
        raise SessionGateError(
            409,
            "manual policy input is disabled or not allowed for current gate",
            code,
            extra={"policy_confirmation": gate_payload},
        )
    if act == "confirm":
        if policy_snapshot is None:
            error_code = AGENT_POLICY_OUT_OF_SCOPE_CODE if str(policy_error or "").strip() == AGENT_POLICY_OUT_OF_SCOPE_CODE else AGENT_POLICY_ERROR_CODE
            raise SessionGateError(
                409,
                f"agent policy extract failed: {policy_error}",
                error_code,
                extra={"policy_confirmation": gate_payload},
            )
        if clarity_gate == "block":
            raise SessionGateError(
                409,
                f"agent policy clarity blocked: score={clarity_score}",
                AGENT_POLICY_CLARITY_BLOCKED_CODE,
                extra={"policy_confirmation": gate_payload},
            )
        if clarity_gate != "confirm":
            raise SessionGateError(
                409,
                "agent policy does not require confirmation",
                "agent_policy_confirmation_not_required",
                extra={"policy_confirmation": gate_payload},
            )
    if act == "reject":
        if not (
            clarity_gate in {"confirm", "block"}
            or parse_status == "failed"
            or requires_manual_fallback
        ):
            raise SessionGateError(
                409,
                "agent policy does not require confirmation",
                "agent_policy_confirmation_not_required",
                extra={"policy_confirmation": gate_payload},
            )

    old_policy = {
        "role_profile": str(gate_payload.get("extracted_policy", {}).get("role_profile") or ""),
        "session_goal": str(gate_payload.get("extracted_policy", {}).get("session_goal") or ""),
        "duty_constraints": normalize_duty_constraints_input(
            gate_payload.get("extracted_policy", {}).get("duty_constraints")
        ),
    }
    old_policy["duty_constraints_text"] = "\n".join(old_policy["duty_constraints"])
    new_policy = dict(old_policy)
    if act == "edit":
        role_profile = str(edited_role_profile or "").strip()
        session_goal = str(edited_session_goal or "").strip()
        duty_items = normalize_duty_constraints_input(edited_duty_constraints)
        duty_text = "\n".join(duty_items).strip()
        valid, reason_code = validate_policy_fields(role_profile, session_goal, duty_text)
        if not valid:
            raise SessionGateError(
                400,
                f"edited policy invalid: {reason_code}",
                "agent_policy_edit_invalid",
            )
        new_policy = {
            "role_profile": role_profile,
            "session_goal": session_goal,
            "duty_constraints": duty_items,
            "duty_constraints_text": duty_text,
        }

    ref = relative_to_root(cfg.root, event_file(cfg.root))
    if act == "reject":
        audit_id = add_policy_confirmation_audit(
            cfg.root,
            operator=operator,
            action=act,
            status="rejected",
            reason_text=reason_text or "user_reject",
            session_id="",
            agent_name=agent_name,
            agents_hash=str(selected.get("agents_hash") or ""),
            agents_version=str(selected.get("agents_version") or ""),
            agents_path=str(selected.get("agents_md_path") or ""),
            parse_status=parse_status,
            clarity_score=clarity_score,
            manual_fallback=False,
            old_policy=old_policy,
            new_policy=old_policy,
            ref=ref,
        )
        persist_event(
            cfg.root,
            {
                "event_id": event_id(),
                "timestamp": iso_ts(now_local()),
                "session_id": requested_session_id or "sess-gate",
                "actor": "workflow",
                "stage": "governance",
                "action": "policy_confirmation",
                "status": "failed",
                "latency_ms": 0,
                "task_id": "",
                "reason_tags": ["action:reject", f"audit_id:{audit_id}"],
                "ref": ref,
            },
        )
        return {
            "ok": True,
            "action": act,
            "terminated": True,
            "audit_id": audit_id,
            "manual_fallback": False,
            "policy_confirmation": gate_payload,
        }

    final_snapshot = build_session_policy_snapshot(
        agent_name=agent_name,
        agents_path=str(selected.get("agents_md_path") or ""),
        agents_hash=str(selected.get("agents_hash") or ""),
        agents_version=str(selected.get("agents_version") or ""),
        role_profile=str(new_policy.get("role_profile") or ""),
        session_goal=str(new_policy.get("session_goal") or ""),
        duty_constraints=str(new_policy.get("duty_constraints_text") or ""),
        policy_source="manual_fallback" if act == "edit" else "auto",
    )
    final_snapshot["confirmation"] = {
        "action": act,
        "operator": str(operator or "web-user"),
        "reason": str(reason_text or ""),
        "confirmed_at": iso_ts(now_local()),
        "manual_fallback": bool(act == "edit"),
    }
    session, _created = create_session_with_policy_snapshot(
        cfg,
        session_id=requested_session_id or "",
        selected_agent=selected,
        policy_snapshot=final_snapshot,
        agent_search_root=current_root.as_posix(),
        requested_is_test_data=requested_is_test_data,
    )
    audit_id = add_policy_confirmation_audit(
        cfg.root,
        operator=operator,
        action=act,
        status="session_created",
        reason_text=reason_text or "",
        session_id=str(session.get("session_id") or ""),
        agent_name=agent_name,
        agents_hash=str(selected.get("agents_hash") or ""),
        agents_version=str(selected.get("agents_version") or ""),
        agents_path=str(selected.get("agents_md_path") or ""),
        parse_status=parse_status,
        clarity_score=clarity_score,
        manual_fallback=bool(act == "edit"),
        old_policy=old_policy,
        new_policy=new_policy,
        ref=ref,
    )
    patch_task_id = create_agent_policy_patch_task(
        cfg.root,
        source_session_id=str(session.get("session_id") or ""),
        confirmation_audit_id=audit_id,
        agent_name=agent_name,
        agents_hash=str(selected.get("agents_hash") or ""),
        agents_version=str(selected.get("agents_version") or ""),
        agents_path=str(selected.get("agents_md_path") or ""),
        policy_snapshot=final_snapshot,
        notes=f"policy_confirmation_action={act};manual_fallback={1 if act == 'edit' else 0}",
    )
    persist_event(
        cfg.root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(now_local()),
            "session_id": str(session.get("session_id") or "sess-gate"),
            "actor": "workflow",
            "stage": "governance",
            "action": "policy_confirmation",
            "status": "success",
            "latency_ms": 0,
            "task_id": patch_task_id,
            "reason_tags": [
                f"action:{act}",
                f"audit_id:{audit_id}",
                f"patch_task:{patch_task_id}",
                f"policy_alignment:{POLICY_ALIGNMENT_ALIGNED}",
                f"policy_source:{session_policy_source_type(final_snapshot)}",
            ],
            "ref": ref,
        },
    )
    append_change_log(
        cfg.root,
        "policy confirmation",
        (
            f"session_id={session.get('session_id','')}, action={act}, audit_id={audit_id}, "
            f"patch_task_id={patch_task_id}, agent={agent_name}"
        ),
    )
    return {
        "ok": True,
        "action": act,
        "terminated": False,
        "audit_id": audit_id,
        "patch_task_id": patch_task_id,
        "manual_fallback": bool(act == "edit"),
        "policy_confirmation": gate_payload,
        "session": session,
    }


def close_all_active_sessions(root: Path, reason: str) -> int:
    closed_at = iso_ts(now_local())
    rows = list_active_session_records(root, limit=5000)
    for row in rows:
        update_work_record_session(
            root,
            str(row.get("session_id") or ""),
            {
                "status": "closed",
                "closed_at": closed_at,
                "closed_reason": reason,
                "updated_at": closed_at,
            },
        )
        try:
            ensure_manual_fallback_patch_task(root, dict(row), reason=reason)
        except Exception:
            continue
    return len(rows)


def list_active_sessions(root: Path, limit: int = 500) -> list[dict[str, Any]]:
    rows = list_active_session_records(root, limit=max(1, min(limit, 5000)))
    return [
        {
            "session_id": str(row.get("session_id") or ""),
            "agent_name": str(row.get("agent_name") or ""),
            "status": str(row.get("status") or ""),
            "created_at": str(row.get("created_at") or ""),
            "is_test_data": bool(row.get("is_test_data")),
        }
        for row in rows
    ]


def reopen_closed_session(cfg: AppConfig, state: RuntimeState, session_id: str) -> dict[str, str]:
    session = get_session(cfg.root, session_id)
    if not session:
        raise SessionGateError(404, "session not found", "session_not_found")
    current_root_path = current_agent_search_root(cfg, state)
    root_ready, root_error = agent_search_root_state(current_root_path)
    if not root_ready or current_root_path is None:
        raise SessionGateError(
            409,
            agent_search_root_block_message(root_error),
            root_error or AGENT_SEARCH_ROOT_NOT_SET_CODE,
            extra={"agent_search_root": agent_search_root_text(current_root_path)},
        )
    current_root = current_root_path.as_posix()
    session_root = str(session.get("agent_search_root") or session.get("target_path") or "").strip()
    if not session_root:
        session_root = current_root
    if session_root != current_root:
        raise SessionGateError(
            409,
            f"session root pinned to {session_root}",
            "session_root_mismatch",
            extra={"session_id": session_id, "session_root": session_root, "current_root": current_root},
        )
    if str(session.get("status") or "").lower() == "active":
        ensure_session_policy_snapshot(cfg.root, session)
        return session
    update_work_record_session(
        cfg.root,
        session_id,
        {
            "status": "active",
            "closed_at": "",
            "closed_reason": "",
            "updated_at": iso_ts(now_local()),
        },
    )
    reopened = get_session(cfg.root, session_id)
    if not reopened:
        raise SessionGateError(404, "session not found", "session_not_found")
    ensure_session_policy_snapshot(cfg.root, reopened)
    append_change_log(
        cfg.root,
        "session reopened",
        f"session_id={session_id}, agent={reopened.get('agent_name','')}, agent_search_root={reopened.get('agent_search_root','')}",
    )
    persist_event(
        cfg.root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(now_local()),
            "session_id": session_id,
            "actor": "workflow",
            "stage": "governance",
            "action": "session_reopened",
            "status": "success",
            "latency_ms": 0,
            "task_id": "",
            "reason_tags": ["reopen"],
            "ref": "",
        },
    )
    return reopened


def switch_agent_search_root(cfg: AppConfig, state: RuntimeState, requested_root: str) -> dict[str, Any]:
    new_root = normalize_abs_path(requested_root, base=cfg.root)
    if not new_root.exists() or not new_root.is_dir():
        raise SessionGateError(400, f"agent_search_root is not a directory: {new_root}", "invalid_agent_search_root")
    workspace_ok, workspace_error = validate_workspace_root_semantics(new_root)
    if not workspace_ok:
        raise SessionGateError(
            400,
            (
                f"agent_search_root must be workspace root and contain workflow/ subdir: "
                f"{new_root.as_posix()}"
            ),
            workspace_error or "workspace_root_invalid",
            extra={
                "agent_search_root": new_root.as_posix(),
                "required_subdir": "workflow",
            },
        )
    current_root = current_agent_search_root(cfg, state)
    if current_root is not None and new_root == current_root:
        save_runtime_config(cfg.root, {"agent_search_root": current_root.as_posix()})
        closed_count = close_all_active_sessions(cfg.root, "agent_search_root_refresh")
        agents = discover_agents(current_root, cache_root=cfg.root, analyze_policy=False)
        append_change_log(
            cfg.root,
            "agent_search_root_refreshed",
            f"from={current_root.as_posix()}, to={current_root.as_posix()}, closed_sessions={closed_count}",
        )
        persist_event(
            cfg.root,
            {
                "event_id": event_id(),
                "timestamp": iso_ts(now_local()),
                "session_id": "sess-governance",
                "actor": "workflow",
                "stage": "governance",
                "action": "agent_search_root_changed",
                "status": "success",
                "latency_ms": 0,
                "task_id": "",
                "reason_tags": [
                    f"from:{current_root.as_posix()}",
                    f"to:{current_root.as_posix()}",
                    f"closed_sessions:{closed_count}",
                    "refresh",
                ],
                "ref": "",
            },
        )
        return {
            "ok": True,
            "agent_search_root": current_root.as_posix(),
            "previous_agent_search_root": current_root.as_posix(),
            "closed_sessions": closed_count,
            "agents": agents,
            "count": len(agents),
            "agent_search_root_ready": True,
            "features_locked": False,
        }
    active_sessions = list_active_sessions(cfg.root) if current_root is not None else []
    if current_root is not None and active_sessions:
        blocked_code = "active_sessions_open"
        test_data_active_count = sum(
            1 for item in active_sessions if bool(item.get("is_test_data"))
        )
        append_failure_case(
            cfg.root,
            "agent_search_root_change_blocked",
            f"code={blocked_code}, active_count={len(active_sessions)}",
        )
        persist_event(
            cfg.root,
            {
                "event_id": event_id(),
                "timestamp": iso_ts(now_local()),
                "session_id": "sess-governance",
                "actor": "workflow",
                "stage": "governance",
                "action": "agent_search_root_change_blocked",
                "status": "failed",
                "latency_ms": 0,
                "task_id": "",
                "reason_tags": [blocked_code, f"active_count:{len(active_sessions)}"],
                "ref": "",
            },
        )
        raise SessionGateError(
            409,
            f"active sessions must be closed before switching root: {len(active_sessions)}",
            blocked_code,
            extra={
                "active_count": len(active_sessions),
                "active_sessions": active_sessions,
                "test_data_active_count": test_data_active_count,
            },
        )
    closed_count = 0
    if current_root is None:
        closed_count = close_all_active_sessions(cfg.root, "agent_search_root_set")
    old_root, current_root = set_agent_search_root(cfg, state, new_root)
    agents = discover_agents(current_root, cache_root=cfg.root, analyze_policy=False)
    old_root_text = agent_search_root_text(old_root)
    current_root_text = current_root.as_posix()
    append_change_log(
        cfg.root,
        "agent_search_root_changed",
        f"from={old_root_text}, to={current_root_text}, closed_sessions={closed_count}",
    )
    persist_event(
        cfg.root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(now_local()),
            "session_id": "sess-governance",
            "actor": "workflow",
            "stage": "governance",
            "action": "agent_search_root_changed",
            "status": "success",
            "latency_ms": 0,
            "task_id": "",
            "reason_tags": [
                f"from:{old_root_text or '<empty>'}",
                f"to:{current_root_text}",
                f"closed_sessions:{closed_count}",
            ],
            "ref": "",
        },
    )
    return {
        "ok": True,
        "agent_search_root": current_root_text,
        "previous_agent_search_root": old_root_text,
        "closed_sessions": closed_count,
        "agents": agents,
        "count": len(agents),
        "agent_search_root_ready": True,
        "features_locked": False,
    }


