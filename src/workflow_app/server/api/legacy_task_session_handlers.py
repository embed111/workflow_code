from __future__ import annotations

import re

from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

from .legacy_post_route_registry import RegexPostRoute, StaticPostRoute, dispatch_post_route_registry


def _send_session_gate_error(handler, cfg, state, exc: SessionGateError) -> None:
    handler.send_json(
        exc.status_code,
        {
            "ok": False,
            "error": str(exc),
            "code": exc.code,
            "agent_search_root": current_agent_search_root_text(cfg, state),
            **exc.extra,
        },
    )


def _handle_session_policy_confirm(handler, cfg, state, body: dict[str, Any], _match) -> None:
    (
        requested_agent,
        requested_session_id,
        _focus,
        requested_agent_search_root,
        requested_is_test_data,
    ) = handler.payload_common(body)
    action = str(body.get("action") or "").strip().lower()
    operator = safe_token(str(body.get("operator") or "web-user"), "web-user", 80)
    reason_text = str(body.get("reason") or "").strip()
    edited_role_profile = str(body.get("role_profile") or "").strip()
    edited_session_goal = str(body.get("session_goal") or "").strip()
    edited_duty_constraints = body.get("duty_constraints", body.get("duty_constraints_text"))
    try:
        result = confirm_session_policy_and_create(
            cfg,
            state,
            requested_session_id=requested_session_id,
            requested_agent_name=requested_agent,
            requested_agent_search_root=requested_agent_search_root,
            requested_is_test_data=requested_is_test_data,
            action=action,
            operator=operator,
            reason_text=reason_text,
            edited_role_profile=edited_role_profile,
            edited_session_goal=edited_session_goal,
            edited_duty_constraints=edited_duty_constraints,
        )
    except SessionGateError as exc:
        _send_session_gate_error(handler, cfg, state, exc)
        return
    if bool(result.get("terminated")):
        handler.send_json(
            200,
            {
                "ok": True,
                "terminated": True,
                "action": result.get("action"),
                "audit_id": result.get("audit_id"),
                "manual_fallback": bool(result.get("manual_fallback")),
                "policy_confirmation": result.get("policy_confirmation") or {},
            },
        )
        return
    session = result.get("session") if isinstance(result.get("session"), dict) else {}
    handler.send_json(
        200,
        {
            "ok": True,
            "session_id": session.get("session_id", ""),
            "agent_name": session.get("agent_name", ""),
            "agents_hash": session.get("agents_hash", ""),
            "agents_loaded_at": session.get("agents_loaded_at", ""),
            "agents_path": session.get("agents_path", ""),
            "agents_version": session.get("agents_version", ""),
            "role_profile": session.get("role_profile", ""),
            "session_goal": session.get("session_goal", ""),
            "duty_constraints": session.get("duty_constraints", ""),
            "policy_snapshot_json": session.get("policy_snapshot_json", "{}"),
            "policy_summary": session.get("policy_summary", ""),
            "agent_search_root": session.get("agent_search_root", ""),
            "is_test_data": bool(session.get("is_test_data")),
            "created_at": session.get("created_at", ""),
            "audit_id": result.get("audit_id"),
            "patch_task_id": result.get("patch_task_id"),
            "manual_fallback": bool(result.get("manual_fallback")),
            "policy_confirmation": result.get("policy_confirmation") or {},
        },
    )


def _handle_session_create_or_get(handler, cfg, _state, body: dict[str, Any], _match) -> None:
    resolved = handler.resolve_session(body, allow_create=True)
    if not resolved:
        return
    session, _focus = resolved
    handler.send_json(
        200,
        {
            "ok": True,
            "session_id": session["session_id"],
            "agent_name": session["agent_name"],
            "agents_hash": session["agents_hash"],
            "agents_loaded_at": session["agents_loaded_at"],
            "agents_path": session.get("agents_path", ""),
            "agents_version": session.get("agents_version", ""),
            "role_profile": session.get("role_profile", ""),
            "session_goal": session.get("session_goal", ""),
            "duty_constraints": session.get("duty_constraints", ""),
            "policy_snapshot_json": session.get("policy_snapshot_json", "{}"),
            "policy_summary": session.get("policy_summary", ""),
            "agent_search_root": session["agent_search_root"],
            "is_test_data": bool(session.get("is_test_data")),
            "created_at": session["created_at"],
        },
    )


def _handle_chat_session_reopen(handler, cfg, state, _body: dict[str, Any], matched: re.Match[str] | None) -> None:
    session_id = safe_token((matched.group(1) if matched else ""), "", 140)
    if not session_id:
        handler.send_json(400, {"ok": False, "error": "session_id required", "code": "session_required"})
        return
    try:
        session = reopen_closed_session(cfg, state, session_id)
        handler.send_json(200, {"ok": True, **session})
    except SessionGateError as exc:
        _send_session_gate_error(handler, cfg, state, exc)


def _handle_chat_interrupt(handler, _cfg, state, body: dict[str, Any], _match) -> None:
    stream_id = str(body.get("stream_id") or "")
    if not stream_id:
        handler.send_json(400, {"ok": False, "error": "stream_id required"})
        return
    with state.stream_lock:
        stop_evt = state.active_streams.get(stream_id)
    if not stop_evt:
        handler.send_json(404, {"ok": False, "error": "stream not found"})
        return
    stop_evt.set()
    handler.send_json(200, {"ok": True, "stream_id": stream_id, "interrupted": True})


def _handle_task_interrupt(handler, cfg, state, _body: dict[str, Any], matched: re.Match[str] | None) -> None:
    task_id_text = safe_token((matched.group(1) if matched else ""), "", 140)
    ok, msg = request_task_interrupt(cfg, state, task_id_text)
    handler.send_json(
        200 if ok else 409,
        {
            "ok": ok,
            "task_id": task_id_text,
            "message": msg,
        },
    )


_SESSION_STATIC_POST_ROUTES = (
    StaticPostRoute("/api/sessions/policy-confirm", _handle_session_policy_confirm),
    StaticPostRoute("/api/sessions", _handle_session_create_or_get),
    StaticPostRoute("/api/chat/interrupt", _handle_chat_interrupt),
)

_SESSION_REGEX_POST_ROUTES = (
    RegexPostRoute(re.compile(r"/api/chat/sessions/([0-9A-Za-z._:-]+)/reopen"), _handle_chat_session_reopen),
    RegexPostRoute(re.compile(r"/api/tasks/([0-9A-Za-z._:-]+)/interrupt"), _handle_task_interrupt),
)


def try_handle_legacy_post_session_routes(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    return dispatch_post_route_registry(
        self,
        cfg,
        state,
        path,
        body,
        static_routes=_SESSION_STATIC_POST_ROUTES,
        regex_routes=_SESSION_REGEX_POST_ROUTES,
    )
