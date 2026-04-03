from __future__ import annotations

from ..bootstrap import web_server_runtime as ws
from ..services import runtime_upgrade_service as rus


def _running_gate_payload(cfg, state) -> tuple[int, int]:
    session_running = int(ws.active_runtime_task_count(state, root=cfg.root))
    assignment_metrics = ws.get_assignment_runtime_metrics(cfg.root, include_test_data=True)
    assignment_running = int(assignment_metrics.get("running_task_count") or 0)
    assignment_calls = int(assignment_metrics.get("agent_call_count") or 0)
    running_task_count = max(0, session_running + assignment_running)
    agent_call_count = max(0, session_running + assignment_calls)
    return running_task_count, agent_call_count


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    if path != "/api/runtime-upgrade/status":
        return False
    running_task_count, agent_call_count = _running_gate_payload(cfg, state)
    payload = rus.build_runtime_upgrade_status(
        rus.runtime_snapshot(),
        running_task_count=running_task_count,
        agent_call_count=agent_call_count,
    )
    handler.send_json(200, payload)
    return True


def try_handle_post(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}
    if path != "/api/runtime-upgrade/apply":
        return False

    snapshot = rus.runtime_snapshot()
    running_task_count, agent_call_count = _running_gate_payload(cfg, state)
    status_payload = rus.build_runtime_upgrade_status(
        snapshot,
        running_task_count=running_task_count,
        agent_call_count=agent_call_count,
    )
    if str(status_payload.get("environment") or "") != "prod":
        handler.send_json(
            409,
            {
                "ok": False,
                "error": "only prod environment supports user-triggered upgrade",
                "code": "runtime_upgrade_not_prod",
                **status_payload,
            },
        )
        return True
    if str(status_payload.get("blocking_reason_code") or "") == "running_tasks_present":
        handler.send_json(
            409,
            {
                "ok": False,
                "error": str(status_payload.get("blocking_reason") or "存在运行中任务，暂不可升级"),
                "code": "prod_upgrade_blocked_running_tasks",
                **status_payload,
            },
        )
        return True
    if not bool(status_payload.get("candidate_available")):
        handler.send_json(
            409,
            {
                "ok": False,
                "error": "prod upgrade candidate incomplete or missing",
                "code": "runtime_upgrade_candidate_missing",
                **status_payload,
            },
        )
        return True
    if not bool(status_payload.get("candidate_is_newer")):
        handler.send_json(
            409,
            {
                "ok": False,
                "error": "no newer prod upgrade candidate",
                "code": "runtime_upgrade_no_newer_candidate",
                **status_payload,
            },
        )
        return True
    if bool(status_payload.get("request_pending")):
        handler.send_json(
            409,
            {
                "ok": False,
                "error": "prod upgrade already switching",
                "code": "runtime_upgrade_already_requested",
                **status_payload,
            },
        )
        return True

    operator = str(body.get("operator") or "web-user")
    request = rus.write_prod_upgrade_request(snapshot, operator=operator)
    rus.schedule_runtime_shutdown(
        state,
        exit_code=rus.PROD_UPGRADE_EXIT_CODE,
        reason="prod_upgrade_requested",
    )
    handler.send_json(
        202,
        {
            "ok": True,
            "message": "prod upgrade accepted; page may reconnect shortly",
            "requested_at": request.get("requested_at"),
            "current_version": snapshot.get("current_version"),
            "candidate_version": request.get("candidate_version"),
            "reconnect_hint": "页面会短暂刷新和重连，请等待正式环境完成切换。",
            **status_payload,
        },
    )
    return True
