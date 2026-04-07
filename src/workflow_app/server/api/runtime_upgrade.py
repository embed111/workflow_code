from __future__ import annotations

import json
from pathlib import Path

from ..bootstrap import web_server_runtime as ws
from ..services import runtime_upgrade_service as rus


def _assignment_runtime_with_workboard_fallback(cfg, state) -> dict:
    include_test_data = ws.current_show_test_data(cfg, state)
    assignment_metrics = ws.get_assignment_runtime_metrics(cfg.root, include_test_data=include_test_data)
    try:
        from . import dashboard as dashboard_api

        workboard = dashboard_api._workboard_payload(cfg, include_test_data=include_test_data)
        return dashboard_api._assignment_runtime_with_workboard_fallback(assignment_metrics, workboard)
    except Exception:
        return assignment_metrics


def _runtime_upgrade_query_text(query: dict | None, key: str) -> str:
    values = (query or {}).get(key)
    if isinstance(values, list):
        for value in values:
            text = str(value or "").strip()
            if text:
                return text[:160]
        return ""
    return str(values or "").strip()[:160]


def _runtime_upgrade_requested_exclusion(*, ticket_id: str, node_id: str) -> dict[str, str]:
    ticket_text = str(ticket_id or "").strip()[:160]
    node_text = str(node_id or "").strip()[:160]
    if not ticket_text or not node_text:
        return {}
    return {
        "ticket_id": ticket_text,
        "node_id": node_text,
    }


def _runtime_upgrade_exclusion_from_query(ctx: dict) -> dict[str, str]:
    query = dict(ctx.get("query") or {})
    return _runtime_upgrade_requested_exclusion(
        ticket_id=(
            _runtime_upgrade_query_text(query, "exclude_assignment_ticket_id")
            or _runtime_upgrade_query_text(query, "exclude_ticket_id")
        ),
        node_id=(
            _runtime_upgrade_query_text(query, "exclude_assignment_node_id")
            or _runtime_upgrade_query_text(query, "exclude_node_id")
        ),
    )


def _runtime_upgrade_exclusion_from_body(body: dict | None) -> dict[str, str]:
    payload = dict(body or {})
    return _runtime_upgrade_requested_exclusion(
        ticket_id=str(
            payload.get("exclude_assignment_ticket_id")
            or payload.get("exclude_ticket_id")
            or ""
        ),
        node_id=str(
            payload.get("exclude_assignment_node_id")
            or payload.get("exclude_node_id")
            or ""
        ),
    )


def _runtime_upgrade_json_load(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_upgrade_running_assignment_nodes(cfg, *, include_test_data: bool) -> list[dict[str, str]]:
    resolver = getattr(ws, "resolve_artifact_root_path", None)
    if not callable(resolver):
        return []
    try:
        artifact_root = Path(resolver(cfg.root)).resolve(strict=False)
    except Exception:
        return []
    tasks_root = (artifact_root / "tasks").resolve(strict=False)
    if not tasks_root.exists() or not tasks_root.is_dir():
        return []
    running: list[dict[str, str]] = []
    for task_dir in sorted(tasks_root.iterdir(), key=lambda item: item.name.lower()):
        if not task_dir.is_dir():
            continue
        task_payload = _runtime_upgrade_json_load(task_dir / "task.json")
        if not task_payload:
            continue
        if str(task_payload.get("record_state") or "active").strip().lower() == "deleted":
            continue
        if not include_test_data and bool(task_payload.get("is_test_data")):
            continue
        ticket_id = str(task_payload.get("ticket_id") or task_dir.name).strip()
        if not ticket_id:
            continue
        nodes_root = task_dir / "nodes"
        if not nodes_root.exists() or not nodes_root.is_dir():
            continue
        raw_nodes: list[dict] = []
        for node_path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
            if not node_path.is_file() or node_path.suffix.lower() != ".json":
                continue
            node_payload = _runtime_upgrade_json_load(node_path)
            if not node_payload:
                continue
            if str(node_payload.get("record_state") or "active").strip().lower() == "deleted":
                continue
            raw_nodes.append(node_payload)
        try:
            live_nodes = ws._assignment_project_live_run_status_for_nodes(
                cfg.root,
                ticket_id=ticket_id,
                node_records=raw_nodes,
            )
        except Exception:
            live_nodes = raw_nodes
        for node_payload in list(live_nodes or []):
            if not isinstance(node_payload, dict):
                continue
            if str(node_payload.get("record_state") or "active").strip().lower() == "deleted":
                continue
            if str(node_payload.get("status") or "").strip().lower() != "running":
                continue
            running.append(
                {
                    "ticket_id": ticket_id,
                    "node_id": str(node_payload.get("node_id") or "").strip(),
                    "assigned_agent_id": str(node_payload.get("assigned_agent_id") or "").strip(),
                    "node_name": str(node_payload.get("node_name") or "").strip(),
                }
            )
    return [item for item in running if str(item.get("node_id") or "").strip()]


def _running_gate_payload(cfg, state, *, exclusion: dict[str, str] | None = None) -> tuple[int, int, dict[str, object]]:
    session_running = int(ws.active_runtime_task_count(state, root=cfg.root))
    include_test_data = ws.current_show_test_data(cfg, state)
    gate_meta: dict[str, object] = {
        "running_gate_exclusion_requested": bool(exclusion),
        "running_gate_exclusion_applied": False,
        "exclude_assignment_ticket_id": str((exclusion or {}).get("ticket_id") or ""),
        "exclude_assignment_node_id": str((exclusion or {}).get("node_id") or ""),
        "excluded_running_task_count": 0,
    }
    if exclusion:
        running_nodes = _runtime_upgrade_running_assignment_nodes(
            cfg,
            include_test_data=include_test_data,
        )
        if running_nodes:
            excluded_running = sum(
                1
                for item in running_nodes
                if str(item.get("ticket_id") or "").strip() == str(exclusion.get("ticket_id") or "").strip()
                and str(item.get("node_id") or "").strip() == str(exclusion.get("node_id") or "").strip()
            )
            assignment_running = max(0, len(running_nodes) - excluded_running)
            assignment_calls = assignment_running
            gate_meta["running_gate_exclusion_applied"] = excluded_running > 0
            gate_meta["excluded_running_task_count"] = max(0, int(excluded_running))
            running_task_count = max(0, session_running + assignment_running)
            agent_call_count = max(0, session_running + assignment_calls)
            return running_task_count, agent_call_count, gate_meta
    assignment_metrics = _assignment_runtime_with_workboard_fallback(cfg, state)
    assignment_running = int(assignment_metrics.get("running_task_count") or 0)
    assignment_calls = int(assignment_metrics.get("agent_call_count") or 0)
    running_task_count = max(0, session_running + assignment_running)
    agent_call_count = max(0, session_running + assignment_calls)
    return running_task_count, agent_call_count, gate_meta


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    if path != "/api/runtime-upgrade/status":
        return False
    exclusion = _runtime_upgrade_exclusion_from_query(ctx)
    running_task_count, agent_call_count, gate_meta = _running_gate_payload(
        cfg,
        state,
        exclusion=exclusion,
    )
    payload = rus.build_runtime_upgrade_status(
        rus.runtime_snapshot(),
        running_task_count=running_task_count,
        agent_call_count=agent_call_count,
    )
    payload.update(gate_meta)
    handler.send_json(200, payload)
    return True


def try_handle_post(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}
    if path != "/api/runtime-upgrade/apply":
        return False

    snapshot = rus.runtime_snapshot()
    exclusion = _runtime_upgrade_exclusion_from_body(body)
    running_task_count, agent_call_count, gate_meta = _running_gate_payload(
        cfg,
        state,
        exclusion=exclusion,
    )
    status_payload = rus.build_runtime_upgrade_status(
        snapshot,
        running_task_count=running_task_count,
        agent_call_count=agent_call_count,
    )
    status_payload.update(gate_meta)
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
