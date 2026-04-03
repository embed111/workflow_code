from __future__ import annotations

from ..bootstrap import web_server_runtime as ws
from ..services import developer_workspace_service as dw


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    root_ready = bool(ctx.get("root_ready"))
    root_error = str(ctx.get("root_error") or "")
    root_text = str(ctx.get("root_text") or "")

    if path == "/api/agents":
        query = ctx.get("query") or {}
        if ws.parse_query_bool(query, "force_show_test_data_read_fail", default=False):
            handler.send_json(
                500,
                {
                    "ok": False,
                    "error": "show_test_data read failed: forced by query",
                    "code": "show_test_data_read_failed",
                },
            )
            return True
        force_refresh = ws.parse_query_bool(query, "force_refresh", default=False)
        agents = ws.list_available_agents(cfg, force_refresh=force_refresh) if root_ready else []
        artifact_settings = ws.get_artifact_root_settings(cfg.root)
        execution_settings = ws.get_assignment_execution_settings(cfg.root)
        workspace_settings = dw.developer_workspace_response_payload(
            runtime_root=cfg.root,
            workspace_root=root_text or None,
        )
        policy_fields = ws.show_test_data_policy_fields(cfg, state)
        handler.send_json(
            200,
            {
                "ok": True,
                "agents_root": root_text,
                "agent_search_root": root_text,
                "workspace_root_valid": bool(root_ready),
                "workspace_root_error": root_error,
                "agent_search_root_ready": bool(root_ready),
                "features_locked": not bool(root_ready),
                **policy_fields,
                "allow_manual_policy_input": bool(ws.current_allow_manual_policy_input(cfg, state)),
                "policy_closure": ws.policy_closure_stats(cfg.root),
                "artifact_root": str(artifact_settings.get("artifact_root") or ""),
                "task_artifact_root": str(artifact_settings.get("task_artifact_root") or ""),
                "artifact_workspace_root": str(artifact_settings.get("workspace_root") or ""),
                "task_records_root": str(artifact_settings.get("task_records_root") or ""),
                "tasks_root": str(artifact_settings.get("tasks_root") or ""),
                "tasks_structure_path": str(artifact_settings.get("tasks_structure_path") or ""),
                "artifact_root_default": str(artifact_settings.get("default_artifact_root") or ""),
                "default_task_artifact_root": str(artifact_settings.get("default_task_artifact_root") or ""),
                "artifact_root_validation_status": str(artifact_settings.get("path_validation_status") or ""),
                "assignment_execution_settings": execution_settings,
                **workspace_settings,
                "agents": agents,
                "count": len(agents),
            },
        )
        return True

    if path == "/api/chat/sessions":
        query = ctx.get("query") or {}
        include_test_data = ws.resolve_include_test_data(query, cfg, state)
        policy_fields = ws.show_test_data_policy_fields(cfg, state)
        handler.send_json(
            200,
            {
                "ok": True,
                "include_test_data": include_test_data,
                **policy_fields,
                "sessions": (
                    ws.list_chat_sessions(
                        cfg.root,
                        include_test_data=include_test_data,
                    )
                    if root_ready
                    else []
                ),
                "agent_search_root": root_text,
                "agent_search_root_ready": bool(root_ready),
                "features_locked": not bool(root_ready),
            },
        )
        return True

    return False

