from __future__ import annotations

from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

from .legacy_post_route_registry import StaticPostRoute, dispatch_post_route_registry


def _send_workflow_gate_error(handler, exc: WorkflowGateError) -> None:
    payload = {
        "ok": False,
        "error": str(exc),
        "code": exc.code,
    }
    payload.update(exc.extra)
    handler.send_json(exc.status_code, payload)


def _workflow_id_or_none(handler, body: dict[str, Any]) -> str:
    workflow_id = safe_token(str(body.get("workflow_id") or ""), "", 120)
    if workflow_id:
        return workflow_id
    handler.send_json(400, {"ok": False, "error": "workflow_id required"})
    return ""


def _handle_workflow_assign(handler, cfg, state, body: dict[str, Any], _match) -> None:
    workflow_id = _workflow_id_or_none(handler, body)
    analyst = str(body.get("analyst") or body.get("assignee") or "").strip()
    note = str(body.get("note") or "").strip()
    if not workflow_id:
        return
    if not analyst:
        handler.send_json(400, {"ok": False, "error": "analyst required"})
        return
    try:
        workflow = assign_training_workflow(cfg, state, workflow_id, analyst, note)
        handler.send_json(200, {"ok": True, "workflow": workflow})
    except WorkflowGateError as exc:
        _send_workflow_gate_error(handler, exc)


def _handle_workflow_analyze(handler, cfg, _state, body: dict[str, Any], _match) -> None:
    workflow_id = _workflow_id_or_none(handler, body)
    if not workflow_id:
        return
    try:
        result = analyze_training_workflow(cfg, workflow_id)
        handler.send_json(200, {"ok": True, **result})
    except WorkflowGateError as exc:
        _send_workflow_gate_error(handler, exc)
    except Exception as exc:
        handler.send_json(500, {"ok": False, "error": str(exc)})


def _handle_workflow_plan(handler, cfg, _state, body: dict[str, Any], _match) -> None:
    workflow_id = _workflow_id_or_none(handler, body)
    if not workflow_id:
        return
    try:
        result = generate_training_workflow_plan(cfg, workflow_id)
        handler.send_json(200, {"ok": True, **result})
    except WorkflowGateError as exc:
        _send_workflow_gate_error(handler, exc)
    except Exception as exc:
        handler.send_json(500, {"ok": False, "error": str(exc)})


def _handle_workflow_execute(handler, cfg, _state, body: dict[str, Any], _match) -> None:
    workflow_id = _workflow_id_or_none(handler, body)
    raw_items = body.get("selected_items")
    selected_items: list[str] = []
    if isinstance(raw_items, list):
        selected_items = [str(item) for item in raw_items]
    elif isinstance(raw_items, str):
        selected_items = [raw_items]
    if not workflow_id:
        return
    try:
        result = execute_training_workflow_plan(
            cfg,
            workflow_id,
            selected_items,
            max_retries=int(body.get("max_retries") or 3),
        )
        handler.send_json(200, {"ok": True, **result})
    except WorkflowGateError as exc:
        _send_workflow_gate_error(handler, exc)
    except Exception as exc:
        append_failure_case(
            cfg.root,
            "workflow_execute_failed",
            f"workflow_id={workflow_id}, err={exc}",
        )
        handler.send_json(500, {"ok": False, "error": str(exc)})


_WORKFLOW_STATIC_POST_ROUTES = (
    StaticPostRoute("/api/workflows/training/assign", _handle_workflow_assign),
    StaticPostRoute("/api/workflows/training/analyze", _handle_workflow_analyze),
    StaticPostRoute("/api/workflows/training/plan", _handle_workflow_plan),
    StaticPostRoute("/api/workflows/training/execute", _handle_workflow_execute),
)


def try_handle_legacy_post_workflow_routes(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    return dispatch_post_route_registry(
        self,
        cfg,
        state,
        path,
        body,
        static_routes=_WORKFLOW_STATIC_POST_ROUTES,
    )
