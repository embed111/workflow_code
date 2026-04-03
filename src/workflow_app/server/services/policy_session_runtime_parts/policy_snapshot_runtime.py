

def _build_policy_rescore_payload_from_fields(
    *,
    role_profile: str,
    session_goal: str,
    duty_constraints_raw: Any,
    parse_status_hint: str = "",
    parse_warnings_hint: Any = None,
    constraints_hint: dict[str, Any] | None = None,
    evidence_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    role_text = str(role_profile or "").strip()
    goal_text = str(session_goal or "").strip()
    duty_items = normalize_duty_constraints_input(duty_constraints_raw)
    duty_text = "\n".join(duty_items).strip()
    valid, invalid_reason = validate_policy_fields(role_text, goal_text, duty_text)

    parse_status = str(parse_status_hint or "").strip().lower()
    if parse_status not in {"ok", "incomplete", "failed"}:
        parse_status = "ok" if valid else "failed"

    parse_warnings = _normalize_policy_warning_codes(parse_warnings_hint)
    if not valid:
        if invalid_reason == "missing_role_profile" and "missing_role_section" not in parse_warnings:
            parse_warnings.append("missing_role_section")
        elif invalid_reason == "missing_session_goal" and "missing_goal_section" not in parse_warnings:
            parse_warnings.append("missing_goal_section")
        elif invalid_reason == "missing_duty_constraints":
            if "missing_duty_section" not in parse_warnings:
                parse_warnings.append("missing_duty_section")
            if "empty_duty_constraints" not in parse_warnings:
                parse_warnings.append("empty_duty_constraints")

    constraints = (
        constraints_hint
        if isinstance(constraints_hint, dict)
        else extract_constraints_from_policy(sections=[], duty_items=duty_items)
    )
    issues_raw = constraints.get("issues") if isinstance(constraints.get("issues"), list) else []
    for issue in issues_raw:
        if not isinstance(issue, dict):
            continue
        code = str(issue.get("code") or "").strip()
        if code and code not in parse_warnings:
            parse_warnings.append(code)

    evidence = evidence_hint if isinstance(evidence_hint, dict) else {}
    role_evidence = str(evidence.get("role") or "").strip()
    goal_evidence = str(evidence.get("goal") or "").strip()
    duty_evidence = str(evidence.get("duty") or "").strip()
    if not role_evidence:
        role_evidence = policy_text_compact(f"编辑角色\n{role_text}", max_chars=360) if role_text else ""
    if not goal_evidence:
        goal_evidence = policy_text_compact(f"编辑目标\n{goal_text}", max_chars=360) if goal_text else ""
    if not duty_evidence:
        duty_evidence = policy_text_compact(f"编辑职责\n{duty_text}", max_chars=680) if duty_text else ""
    evidence_payload = {
        "role": role_evidence,
        "goal": goal_evidence,
        "duty": duty_evidence,
    }

    clarity = compute_policy_clarity(
        role_profile=role_text,
        session_goal=goal_text,
        duty_constraints=duty_items,
        parse_status=parse_status,
        parse_warnings=parse_warnings,
        evidence_snippets=evidence_payload,
        constraints=constraints,
    )
    score_total = max(0, min(100, int(clarity.get("score_total") or clarity.get("clarity_score") or 0)))
    return {
        "role_profile": role_text,
        "session_goal": goal_text,
        "duty_constraints": duty_items,
        "duty_constraints_text": duty_text,
        "parse_status": parse_status,
        "parse_warnings": parse_warnings,
        "evidence_snippets": evidence_payload,
        "constraints": constraints if isinstance(constraints, dict) else {},
        "score_model": str(clarity.get("score_model") or POLICY_SCORE_MODEL),
        "score_total": score_total,
        "score_weights": clarity.get("score_weights")
        if isinstance(clarity.get("score_weights"), dict)
        else dict(POLICY_SCORE_WEIGHTS),
        "score_dimensions": clarity.get("score_dimensions")
        if isinstance(clarity.get("score_dimensions"), dict)
        else {},
        "clarity_score": max(0, min(100, int(clarity.get("clarity_score") or score_total))),
        "clarity_details": clarity.get("clarity_details")
        if isinstance(clarity.get("clarity_details"), dict)
        else {},
        "clarity_gate": str(clarity.get("clarity_gate") or "block"),
        "clarity_gate_reason": str(clarity.get("clarity_gate_reason") or ""),
        "risk_tips": [
            str(v).strip()
            for v in (clarity.get("risk_tips") or [])
            if str(v or "").strip()
        ],
    }


def _build_policy_rescore_payload_from_agent_item(item: dict[str, Any]) -> dict[str, Any]:
    role_profile = str(item.get("role_profile") or "").strip()
    session_goal = str(item.get("session_goal") or "").strip()
    duty_items = normalize_duty_constraints_input(
        item.get("duty_constraints")
        if isinstance(item.get("duty_constraints"), list)
        else item.get("duty_constraints_text")
    )
    base = _build_policy_rescore_payload_from_fields(
        role_profile=role_profile,
        session_goal=session_goal,
        duty_constraints_raw=duty_items,
        parse_status_hint=str(item.get("parse_status") or ""),
        parse_warnings_hint=item.get("parse_warnings"),
        constraints_hint=item.get("constraints") if isinstance(item.get("constraints"), dict) else None,
        evidence_hint=item.get("evidence_snippets") if isinstance(item.get("evidence_snippets"), dict) else None,
    )

    if isinstance(item.get("score_weights"), dict):
        base["score_weights"] = item.get("score_weights")
    if isinstance(item.get("score_dimensions"), dict) and item.get("score_dimensions"):
        base["score_dimensions"] = item.get("score_dimensions")
    if isinstance(item.get("clarity_details"), dict) and item.get("clarity_details"):
        base["clarity_details"] = item.get("clarity_details")
    if isinstance(item.get("constraints"), dict) and item.get("constraints"):
        base["constraints"] = item.get("constraints")
    if isinstance(item.get("evidence_snippets"), dict) and item.get("evidence_snippets"):
        base["evidence_snippets"] = item.get("evidence_snippets")

    try:
        base["score_total"] = max(
            0,
            min(100, int(item.get("score_total") or item.get("clarity_score") or base.get("score_total") or 0)),
        )
    except Exception:
        pass
    try:
        base["clarity_score"] = max(
            0,
            min(100, int(item.get("clarity_score") or base.get("clarity_score") or base.get("score_total") or 0)),
        )
    except Exception:
        pass
    base["score_model"] = str(item.get("score_model") or base.get("score_model") or POLICY_SCORE_MODEL)
    base["clarity_gate"] = str(item.get("clarity_gate") or base.get("clarity_gate") or "block")
    base["clarity_gate_reason"] = str(item.get("clarity_gate_reason") or base.get("clarity_gate_reason") or "")
    base["parse_status"] = str(item.get("parse_status") or base.get("parse_status") or "failed")
    base["parse_warnings"] = _normalize_policy_warning_codes(item.get("parse_warnings") or base.get("parse_warnings"))
    base["risk_tips"] = [
        str(v).strip()
        for v in (item.get("risk_tips") or base.get("risk_tips") or [])
        if str(v or "").strip()
    ]
    return base


def _policy_rescore_input_matches_agent_item(
    item: dict[str, Any],
    *,
    role_profile: str,
    session_goal: str,
    duty_constraints_raw: Any,
) -> bool:
    current_role = str(item.get("role_profile") or "").strip()
    current_goal = str(item.get("session_goal") or "").strip()
    current_duty = normalize_duty_constraints_input(
        item.get("duty_constraints")
        if isinstance(item.get("duty_constraints"), list)
        else item.get("duty_constraints_text")
    )
    edited_role = str(role_profile or "").strip()
    edited_goal = str(session_goal or "").strip()
    edited_duty = normalize_duty_constraints_input(duty_constraints_raw)
    return current_role == edited_role and current_goal == edited_goal and current_duty == edited_duty


def _build_policy_rescore_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_total = max(0, min(100, int(before.get("score_total") or before.get("clarity_score") or 0)))
    after_total = max(0, min(100, int(after.get("score_total") or after.get("clarity_score") or 0)))
    before_dims = before.get("score_dimensions") if isinstance(before.get("score_dimensions"), dict) else {}
    after_dims = after.get("score_dimensions") if isinstance(after.get("score_dimensions"), dict) else {}
    dim_rows: list[dict[str, Any]] = []
    for key, label in POLICY_SCORE_DIMENSION_META:
        before_dim = before_dims.get(key) if isinstance(before_dims.get(key), dict) else {}
        after_dim = after_dims.get(key) if isinstance(after_dims.get(key), dict) else {}
        try:
            before_score = max(0, min(100, int(before_dim.get("score") or 0)))
        except Exception:
            before_score = 0
        try:
            after_score = max(0, min(100, int(after_dim.get("score") or 0)))
        except Exception:
            after_score = 0
        dim_rows.append(
            {
                "key": key,
                "label": str(after_dim.get("label") or before_dim.get("label") or label),
                "before_score": before_score,
                "after_score": after_score,
                "delta": int(after_score - before_score),
            }
        )
    return {
        "score_total_before": before_total,
        "score_total_after": after_total,
        "score_total_delta": int(after_total - before_total),
        "clarity_gate_before": str(before.get("clarity_gate") or ""),
        "clarity_gate_after": str(after.get("clarity_gate") or ""),
        "clarity_gate_changed": str(before.get("clarity_gate") or "") != str(after.get("clarity_gate") or ""),
        "dimensions": dim_rows,
    }


def extract_policy_snapshot_from_agents_file(
    *,
    runtime_root: Path,
    workspace_root: str,
    agent_name: str,
    agents_path: str,
    agents_hash: str,
    agents_version: str,
) -> tuple[dict[str, Any] | None, str]:
    path_text = str(agents_path or "").strip()
    if not path_text:
        return None, "missing_agents_path"
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return None, "agents_md_not_found"
    workspace_root_text = str(workspace_root or "").strip()
    if not workspace_root_text:
        return None, "workspace_root_missing"
    workspace_root_path = normalize_abs_path(workspace_root_text, base=runtime_root)
    payload = build_agent_policy_payload_via_codex(
        runtime_root=runtime_root,
        workspace_root=workspace_root_path,
        agent_name=agent_name,
        agents_file=path,
        agents_hash=str(agents_hash or "").strip(),
        agents_version=str(agents_version or "").strip(),
    )
    role_profile = str(payload.get("role_profile") or "").strip()
    session_goal = str(payload.get("session_goal") or "").strip()
    duty_items = [str(v).strip() for v in (payload.get("duty_constraints") or []) if str(v or "").strip()]
    duty_constraints = str(payload.get("duty_constraints_text") or "").strip()
    if not duty_constraints and duty_items:
        duty_constraints = "\n".join(duty_items)
    parse_status = str(payload.get("parse_status") or "failed").strip().lower()
    policy_error = str(payload.get("policy_error") or "").strip()
    ok, reason = validate_policy_fields(role_profile, session_goal, duty_constraints)
    if parse_status == "failed" or not ok:
        return None, policy_error or reason or "policy_extract_failed"
    digest = str(agents_hash or "").strip()
    if not digest:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            digest = ""
    version = str(agents_version or "").strip() or digest[:12]
    return (
        build_session_policy_snapshot(
            agent_name=agent_name,
            agents_path=path.as_posix(),
            agents_hash=digest,
            agents_version=version,
            role_profile=role_profile,
            session_goal=session_goal,
            duty_constraints=duty_constraints,
        ),
        "",
    )


def save_session_policy_snapshot(root: Path, session_id: str, snapshot: dict[str, Any]) -> None:
    role_profile = str(snapshot.get("role_profile") or "")
    session_goal = str(snapshot.get("session_goal") or "")
    duty_constraints = str(snapshot.get("duty_constraints") or "")
    update_work_record_session_record(
        root,
        session_id,
        {
            "role_profile": role_profile,
            "session_goal": session_goal,
            "duty_constraints": duty_constraints,
            "policy_snapshot_json": json.dumps(snapshot, ensure_ascii=False),
        },
    )


def ensure_session_policy_snapshot(root: Path, session: dict[str, Any]) -> dict[str, Any]:
    role_profile = str(session.get("role_profile") or "").strip()
    session_goal = str(session.get("session_goal") or "").strip()
    duty_constraints = str(session.get("duty_constraints") or "").strip()
    ok, error_reason = validate_policy_fields(role_profile, session_goal, duty_constraints)
    policy_snapshot = parse_policy_snapshot_json(str(session.get("policy_snapshot_json") or ""))
    if not ok:
        snapshot, error = extract_policy_snapshot_from_agents_file(
            runtime_root=root,
            workspace_root=str(session.get("agent_search_root") or session.get("target_path") or ""),
            agent_name=str(session.get("agent_name") or ""),
            agents_path=str(session.get("agents_path") or ""),
            agents_hash=str(session.get("agents_hash") or ""),
            agents_version=str(session.get("agents_version") or ""),
        )
        if snapshot is None:
            error_code = AGENT_POLICY_OUT_OF_SCOPE_CODE if str(error or "").strip() == AGENT_POLICY_OUT_OF_SCOPE_CODE else AGENT_POLICY_ERROR_CODE
            raise SessionGateError(
                409,
                f"agent policy extract failed: {error}",
                error_code,
                extra={
                    "session_id": str(session.get("session_id") or ""),
                    "agent_name": str(session.get("agent_name") or ""),
                    "agents_path": str(session.get("agents_path") or ""),
                    "policy_error": error,
                    "missing_reason": error_reason,
                    "workspace_root": str(session.get("agent_search_root") or session.get("target_path") or ""),
                },
            )
        policy_snapshot = snapshot
        save_session_policy_snapshot(root, str(session.get("session_id") or ""), snapshot)
        role_profile = str(snapshot.get("role_profile") or "")
        session_goal = str(snapshot.get("session_goal") or "")
        duty_constraints = str(snapshot.get("duty_constraints") or "")
    elif not policy_snapshot:
        policy_snapshot = build_session_policy_snapshot(
            agent_name=str(session.get("agent_name") or ""),
            agents_path=str(session.get("agents_path") or ""),
            agents_hash=str(session.get("agents_hash") or ""),
            agents_version=str(session.get("agents_version") or ""),
            role_profile=role_profile,
            session_goal=session_goal,
            duty_constraints=duty_constraints,
        )
        save_session_policy_snapshot(root, str(session.get("session_id") or ""), policy_snapshot)
    session["role_profile"] = role_profile
    session["session_goal"] = session_goal
    session["duty_constraints"] = duty_constraints
    session["policy_snapshot_json"] = json.dumps(policy_snapshot, ensure_ascii=False)
    session["policy_summary"] = session_policy_summary(policy_snapshot)
    return policy_snapshot


def session_policy_prompt_block(snapshot: dict[str, Any]) -> str:
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    source_hash = str((source or {}).get("agents_hash") or "")
    source_version = str((source or {}).get("agents_version") or "")
    source_path = str((source or {}).get("agents_path") or "")
    source_type = session_policy_source_type(snapshot)
    role_profile = str(snapshot.get("role_profile") or "")
    session_goal = str(snapshot.get("session_goal") or "")
    duty_constraints = str(snapshot.get("duty_constraints") or "")
    return "\n".join(
        [
            "[SESSION_POLICY_FROZEN]",
            f"policy_source: hash={source_hash} version={source_version} path={source_path} type={source_type}",
            f"role_profile: {role_profile}",
            f"session_goal: {session_goal}",
            f"duty_constraints: {duty_constraints}",
            "[/SESSION_POLICY_FROZEN]",
        ]
    )


def session_policy_reason_tags(session: dict[str, Any]) -> list[str]:
    snapshot = parse_policy_snapshot_json(str(session.get("policy_snapshot_json") or ""))
    source_type = session_policy_source_type(snapshot)
    return [
        "policy_alignment:aligned",
        "policy_reason:session_policy_injected",
        f"policy_source:{source_type}",
    ]
from .work_record_store import update_session_record as update_work_record_session_record
