from __future__ import annotations

import json

from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

from .legacy_post_route_registry import StaticPostRoute, dispatch_post_route_registry


def _validated_agent_search_root_or_none(handler, cfg, state, body: dict[str, Any]):
    requested_agent_search_root = str(
        body.get("agent_search_root")
        or body.get("agentSearchRoot")
        or ""
    ).strip()
    current_root = current_agent_search_root(cfg, state)
    if requested_agent_search_root:
        requested_root = normalize_abs_path(requested_agent_search_root, base=cfg.root)
        if requested_root != current_root:
            handler.send_json(
                409,
                {
                    "ok": False,
                    "error": (
                        f"agent_search_root mismatch: "
                        f"current={current_root.as_posix()} requested={requested_root.as_posix()}"
                    ),
                    "code": "agent_search_root_mismatch",
                    "agent_search_root": current_root.as_posix(),
                },
            )
            return None
    return current_root


def _selected_agent_or_none(handler, cfg, agent_name: str):
    selected = load_agent_with_policy(cfg, agent_name)
    if selected:
        return selected
    handler.send_json(
        400,
        {"ok": False, "error": f"agent not available: {agent_name}", "code": "agent_not_available"},
    )
    return None


def _handle_policy_analyze(handler, cfg, state, body: dict[str, Any], _match) -> None:
    agent_name = safe_token(str(body.get("agent_name") or ""), "", 80)
    if not agent_name:
        handler.send_json(
            400,
            {"ok": False, "error": "agent_name required", "code": "agent_required"},
        )
        return
    if _validated_agent_search_root_or_none(handler, cfg, state, body) is None:
        return
    selected = _selected_agent_or_none(handler, cfg, agent_name)
    if not selected:
        return
    allow_manual_input = current_allow_manual_policy_input(cfg, state)
    policy_snapshot, policy_error = extract_policy_snapshot_from_agent_item(selected)
    gate_payload = agent_policy_gate_payload(
        selected,
        snapshot=policy_snapshot,
        policy_error=policy_error,
        allow_manual_policy_input=allow_manual_input,
    )
    agent_policy_payload = dict(selected)
    agent_policy_payload["codex_failure"] = (
        gate_payload.get("codex_failure")
        if isinstance(gate_payload.get("codex_failure"), dict)
        else {}
    )
    handler.send_json(
        200,
        {
            "ok": True,
            "agent_name": agent_name,
            "policy_confirmation": gate_payload,
            "agent_policy": agent_policy_payload,
        },
    )


def _handle_policy_cache_clear(handler, cfg, _state, body: dict[str, Any], _match) -> None:
    scope = safe_token(str(body.get("scope") or "selected"), "selected", 20).lower()
    requested_agent_name = safe_token(str(body.get("agent_name") or ""), "", 80)
    requested_agent_path = str(
        body.get("agent_path")
        or body.get("agents_path")
        or ""
    ).strip()
    clear_all = bool(scope == "all" or (not requested_agent_name and not requested_agent_path))
    resolved_agent_path = requested_agent_path
    if not clear_all and not resolved_agent_path:
        agents = list_available_agents(cfg)
        selected = next(
            (item for item in agents if item.get("agent_name") == requested_agent_name),
            None,
        )
        if not selected:
            handler.send_json(
                400,
                {
                    "ok": False,
                    "error": f"agent not available: {requested_agent_name}",
                    "code": "agent_not_available",
                },
            )
            return
        resolved_agent_path = str(selected.get("agents_md_path") or "")
    result = clear_agent_policy_cache(
        cfg.root,
        clear_all=clear_all,
        agent_path=resolved_agent_path,
    )
    invalidate_available_agents_cache(
        config_root=cfg.root,
        target_agent_name="" if clear_all else requested_agent_name,
    )
    append_change_log(
        cfg.root,
        "policy cache clear",
        (
            f"scope={result.get('scope')}, agent={requested_agent_name or '-'}, "
            f"path={resolved_agent_path or '-'}, deleted={result.get('deleted_count',0)}"
        ),
    )
    handler.send_json(
        200,
        {
            "ok": True,
            "scope": result.get("scope", "selected"),
            "agent_name": requested_agent_name,
            "agent_path": resolved_agent_path,
            "deleted_count": int(result.get("deleted_count") or 0),
            "before_count": int(result.get("before_count") or 0),
            "remaining_count": int(result.get("remaining_count") or 0),
        },
    )


def _handle_policy_recommend(handler, cfg, state, body: dict[str, Any], _match) -> None:
    agent_name = safe_token(str(body.get("agent_name") or ""), "", 80)
    instruction = str(body.get("instruction") or body.get("prompt") or "").strip()
    if not agent_name:
        handler.send_json(
            400,
            {"ok": False, "error": "agent_name required", "code": "agent_required"},
        )
        return
    if not instruction:
        handler.send_json(
            400,
            {
                "ok": False,
                "error": "instruction required",
                "code": "policy_recommend_instruction_required",
            },
        )
        return
    instruction_valid, instruction_error = validate_policy_recommend_instruction(instruction)
    if not instruction_valid:
        handler.send_json(
            400,
            {
                "ok": False,
                "error": str(instruction_error or "instruction invalid"),
                "code": "policy_recommend_instruction_invalid",
            },
        )
        return
    current_root = _validated_agent_search_root_or_none(handler, cfg, state, body)
    if current_root is None:
        return
    role_profile = str(body.get("role_profile") or "").strip()
    session_goal = str(body.get("session_goal") or "").strip()
    duty_items = normalize_duty_constraints_input(
        body.get("duty_constraints", body.get("duty_constraints_text"))
    )
    if not role_profile and not session_goal and not duty_items:
        selected = load_agent_with_policy(cfg, agent_name)
        if selected:
            role_profile = str(selected.get("role_profile") or "").strip()
            session_goal = str(selected.get("session_goal") or "").strip()
            duty_items = normalize_duty_constraints_input(
                selected.get("duty_constraints")
                if isinstance(selected.get("duty_constraints"), list)
                else selected.get("duty_constraints_text")
            )
    recommendation, source, warnings = recommend_agent_policy(
        agent_name=agent_name,
        instruction=instruction,
        role_profile=role_profile,
        session_goal=session_goal,
        duty_constraints=duty_items,
        codex_workspace_root=current_root,
    )
    recommendation_payload = dict(recommendation)
    if not isinstance(recommendation_payload.get("constraints"), dict):
        recommendation_constraints = extract_constraints_from_policy(
            sections=[],
            duty_items=normalize_duty_constraints_input(
                recommendation_payload.get("duty_constraints")
                if isinstance(recommendation_payload.get("duty_constraints"), list)
                else recommendation_payload.get("duty_constraints_text")
            ),
        )
        recommendation_payload["constraints"] = recommendation_constraints
    handler.send_json(
        200,
        {
            "ok": True,
            "agent_name": agent_name,
            "instruction": instruction,
            "source": source,
            "warnings": warnings,
            "recommendation": recommendation_payload,
        },
    )


def _handle_policy_rescore(handler, cfg, state, body: dict[str, Any], _match) -> None:
    agent_name = safe_token(str(body.get("agent_name") or ""), "", 80)
    if not agent_name:
        handler.send_json(
            400,
            {"ok": False, "error": "agent_name required", "code": "agent_required"},
        )
        return
    if _validated_agent_search_root_or_none(handler, cfg, state, body) is None:
        return
    selected = _selected_agent_or_none(handler, cfg, agent_name)
    if not selected:
        return
    role_profile = str(body.get("role_profile") or "").strip()
    session_goal = str(body.get("session_goal") or "").strip()
    edited_duty_raw = body.get("duty_constraints", body.get("duty_constraints_text"))
    edited_duty_items = normalize_duty_constraints_input(edited_duty_raw)
    if not role_profile and not session_goal and not edited_duty_items:
        role_profile = str(selected.get("role_profile") or "").strip()
        session_goal = str(selected.get("session_goal") or "").strip()
        edited_duty_raw = (
            selected.get("duty_constraints")
            if isinstance(selected.get("duty_constraints"), list)
            else selected.get("duty_constraints_text")
        )
    before_preview = _build_policy_rescore_payload_from_agent_item(selected)
    unchanged_input = _policy_rescore_input_matches_agent_item(
        selected,
        role_profile=role_profile,
        session_goal=session_goal,
        duty_constraints_raw=edited_duty_raw,
    )
    if unchanged_input:
        after_preview = json.loads(json.dumps(before_preview, ensure_ascii=False))
    else:
        after_preview = _build_policy_rescore_payload_from_fields(
            role_profile=role_profile,
            session_goal=session_goal,
            duty_constraints_raw=edited_duty_raw,
        )
    diff_preview = _build_policy_rescore_diff(before_preview, after_preview)
    diff_preview["unchanged_input"] = bool(unchanged_input)
    handler.send_json(
        200,
        {
            "ok": True,
            "agent_name": agent_name,
            "allow_manual_policy_input": bool(current_allow_manual_policy_input(cfg, state)),
            "preview": {
                "before": before_preview,
                "after": after_preview,
                "diff": diff_preview,
                "unchanged_input": bool(unchanged_input),
            },
        },
    )


_POLICY_STATIC_POST_ROUTES = (
    StaticPostRoute("/api/policy/analyze", _handle_policy_analyze),
    StaticPostRoute("/api/policy/cache/clear", _handle_policy_cache_clear),
    StaticPostRoute("/api/policy/recommend", _handle_policy_recommend),
    StaticPostRoute("/api/policy/rescore", _handle_policy_rescore),
)


def try_handle_legacy_post_policy_routes(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    return dispatch_post_route_registry(
        self,
        cfg,
        state,
        path,
        body,
        static_routes=_POLICY_STATIC_POST_ROUTES,
    )
