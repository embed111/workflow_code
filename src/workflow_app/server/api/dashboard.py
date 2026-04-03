from __future__ import annotations

from ..bootstrap import web_server_runtime as ws


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    root_ready = bool(ctx.get("root_ready"))
    root_error = str(ctx.get("root_error") or "")
    root_text = str(ctx.get("root_text") or "")
    session_running_task_count = int(ws.active_runtime_task_count(state, root=cfg.root))

    if path != "/api/status" and path != "/api/dashboard":
        return False

    if path == "/api/status":
        include_test_data = ws.current_show_test_data(cfg, state)
        assignment_runtime = ws.get_assignment_runtime_metrics(cfg.root, include_test_data=include_test_data)
        assignment_running_task_count = int(assignment_runtime.get("running_task_count") or 0)
        assignment_running_agent_count = int(assignment_runtime.get("running_agent_count") or 0)
        assignment_active_execution_count = int(assignment_runtime.get("active_execution_count") or 0)
        assignment_agent_call_count = int(assignment_runtime.get("agent_call_count") or 0)
        running_task_count = max(0, session_running_task_count + assignment_running_task_count)
        agent_call_count = max(0, session_running_task_count + assignment_agent_call_count)
        pa, pt = ws.pending_counts(cfg.root, include_test_data=include_test_data)
        policy_fields = ws.show_test_data_policy_fields(cfg, state)
        if ws.AB_FEATURE_ENABLED:
            ab = ws.ab_status(cfg)
        else:
            ab = {"active_version": "disabled", "active_slot": "disabled"}
        handler.send_json(
            200,
            {
                "ok": True,
                "pending_analysis": pa,
                "pending_training": pt,
                "active_version": ab["active_version"],
                "active_slot": ab["active_slot"],
                "available_agents": len(ws.list_available_agents(cfg)) if root_ready else 0,
                **policy_fields,
                "agent_search_root": root_text,
                "agent_search_root_ready": bool(root_ready),
                "agent_search_root_error": root_error,
                "features_locked": not bool(root_ready),
                "running_task_count": running_task_count,
                "agent_call_count": agent_call_count,
                "session_running_task_count": session_running_task_count,
                "assignment_running_task_count": assignment_running_task_count,
                "assignment_running_agent_count": assignment_running_agent_count,
                "assignment_active_execution_count": assignment_active_execution_count,
            },
        )
        return True

    query = ctx.get("query") or {}
    include_test_data = ws.resolve_include_test_data(query, cfg, state)
    assignment_runtime = ws.get_assignment_runtime_metrics(cfg.root, include_test_data=include_test_data)
    assignment_running_task_count = int(assignment_runtime.get("running_task_count") or 0)
    assignment_running_agent_count = int(assignment_runtime.get("running_agent_count") or 0)
    assignment_active_execution_count = int(assignment_runtime.get("active_execution_count") or 0)
    assignment_agent_call_count = int(assignment_runtime.get("agent_call_count") or 0)
    running_task_count = max(0, session_running_task_count + assignment_running_task_count)
    agent_call_count = max(0, session_running_task_count + assignment_agent_call_count)
    policy_fields = ws.show_test_data_policy_fields(cfg, state)
    handler.send_json(
        200,
        {
            **ws.dashboard(cfg, include_test_data=include_test_data),
            **policy_fields,
            "include_test_data": bool(include_test_data),
            "running_task_count": running_task_count,
            "agent_call_count": agent_call_count,
            "session_running_task_count": session_running_task_count,
            "assignment_running_task_count": assignment_running_task_count,
            "assignment_running_agent_count": assignment_running_agent_count,
            "assignment_active_execution_count": assignment_active_execution_count,
        },
    )
    return True

