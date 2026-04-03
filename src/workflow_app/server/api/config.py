from __future__ import annotations

from ..bootstrap import web_server_runtime as ws
from ..services import developer_workspace_service as dw


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    workspace_root = str(ctx.get("root_text") or "").strip() or None
    if path == "/api/config/developer-workspaces":
        handler.send_json(
            200,
            {
                "ok": True,
                **dw.developer_workspace_response_payload(
                    runtime_root=cfg.root,
                    workspace_root=workspace_root,
                ),
            },
        )
        return True
    if path == "/api/config/artifact-root":
        handler.send_json(200, {"ok": True, **ws.get_artifact_root_settings(cfg.root)})
        return True
    if path != "/api/config/show-test-data":
        return False
    query = ctx.get("query") or {}
    if ws.parse_query_bool(query, "force_fail", default=False):
        handler.send_json(
            500,
            {
                "ok": False,
                "error": "show_test_data read failed: forced by query",
                "code": "show_test_data_read_failed",
            },
        )
        return True
    handler.send_json(
        200,
        {
            "ok": True,
            "deprecated": True,
            "read_only": True,
            **ws.show_test_data_policy_fields(cfg, state),
        },
    )
    return True


def try_handle_post(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}

    if path == "/api/developer-workspaces/bootstrap":
        try:
            result = dw.bootstrap_developer_workspace(
                runtime_root=cfg.root,
                workspace_root=str(body.get("workspace_root") or "").strip() or None,
                developer_id=str(body.get("developer_id") or body.get("developerId") or ""),
                workspace_path=str(body.get("workspace_path") or body.get("workspacePath") or ""),
                tracking_branch=str(body.get("tracking_branch") or body.get("trackingBranch") or ""),
            )
            handler.send_json(200, result)
        except dw.DeveloperWorkspaceError as exc:
            handler.send_json(
                exc.status_code,
                {"ok": False, "error": str(exc), "code": exc.code, **exc.extra},
            )
        return True

    if path == "/api/config/artifact-root":
        try:
            result = ws.set_artifact_root(
                cfg,
                state,
                str(body.get("artifact_root") or body.get("artifactRoot") or ""),
            )
            handler.send_json(200, result)
        except ws.SessionGateError as exc:
            handler.send_json(
                exc.status_code,
                {"ok": False, "error": str(exc), "code": exc.code, **exc.extra},
            )
        return True

    if path == "/api/config/agent-search-root":
        requested_root = str(
            body.get("agent_search_root")
            or body.get("agentSearchRoot")
            or ""
        ).strip()
        if not requested_root:
            handler.send_json(400, {"ok": False, "error": "agent_search_root required", "code": "agent_search_root_required"})
            return True
        try:
            result = ws.switch_agent_search_root(cfg, state, requested_root)
            handler.send_json(200, result)
        except ws.SessionGateError as exc:
            handler.send_json(
                exc.status_code,
                {"ok": False, "error": str(exc), "code": exc.code, **exc.extra},
            )
        return True

    if path == "/api/config/show-test-data":
        requested = ws.parse_bool_flag(
            body.get("show_test_data", body.get("showTestData")),
            default=ws.current_show_test_data(cfg, state),
        )
        handler.send_json(
            410,
            ws.show_test_data_toggle_removed_payload(
                cfg,
                state,
                requested_value=requested,
            ),
        )
        return True

    if path == "/api/config/manual-policy-input":
        if not handler.ensure_root_ready():
            return True
        requested = ws.parse_bool_flag(
            body.get("allow_manual_policy_input", body.get("allowManualPolicyInput")),
            default=ws.current_allow_manual_policy_input(cfg, state),
        )
        old_value, new_value = ws.set_allow_manual_policy_input(cfg, state, requested)
        ws.append_change_log(
            cfg.root,
            "manual policy input toggle",
            f"old={int(old_value)}, new={int(new_value)}",
        )
        handler.send_json(
            200,
            {
                "ok": True,
                "allow_manual_policy_input": bool(new_value),
                "previous_allow_manual_policy_input": bool(old_value),
            },
        )
        return True

    return False

