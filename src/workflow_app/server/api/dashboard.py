from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..bootstrap import web_server_runtime as ws


def _parse_iso_datetime(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _runtime_goal_payload(cfg) -> dict:
    runtime_root = Path(cfg.root).resolve(strict=False)
    control_root = runtime_root.parent.parent if runtime_root.parent.name == "runtime" else None
    instance_path = (control_root / "instances" / "prod.json").resolve(strict=False) if isinstance(control_root, Path) else None
    payload = {
        "prod_runtime_goal_hours": 24,
        "prod_runtime_status": "unknown",
        "prod_runtime_started_at": "",
        "prod_runtime_uptime_seconds": 0,
        "prod_runtime_goal_progress_pct": 0,
    }
    if not isinstance(instance_path, Path) or not instance_path.exists():
        return payload
    try:
        data = json.loads(instance_path.read_text(encoding="utf-8"))
    except Exception:
        return payload
    if not isinstance(data, dict):
        return payload
    status = str(data.get("status") or "").strip().lower() or "unknown"
    started_at = str(data.get("started_at") or "").strip()
    payload["prod_runtime_status"] = status
    payload["prod_runtime_started_at"] = started_at
    started_dt = _parse_iso_datetime(started_at)
    if status == "running" and isinstance(started_dt, datetime):
        uptime_seconds = max(0, int((datetime.now(timezone.utc) - started_dt.astimezone(timezone.utc)).total_seconds()))
        payload["prod_runtime_uptime_seconds"] = uptime_seconds
        payload["prod_runtime_goal_progress_pct"] = min(100, int((uptime_seconds / (24 * 3600)) * 100))
    return payload


def _json_load(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _workboard_payload(cfg, *, include_test_data: bool) -> dict:
    resolver = getattr(ws, "resolve_artifact_root_path", None)
    if not callable(resolver):
        return {"assignment_workboard_agents": [], "schedule_workboard_preview": [], "schedule_plan_count": 0}
    artifact_root = Path(resolver(cfg.root)).resolve(strict=False)
    tasks_root = (artifact_root / "tasks").resolve(strict=False)
    groups = {}
    target_task_dir = None
    if tasks_root.exists() and tasks_root.is_dir():
        for task_dir in sorted(tasks_root.iterdir(), key=lambda item: item.name.lower()):
            if not task_dir.is_dir():
                continue
            task_payload = _json_load(task_dir / "task.json")
            if not task_payload:
                continue
            if str(task_payload.get("record_state") or "active").strip().lower() == "deleted":
                continue
            if not include_test_data and bool(task_payload.get("is_test_data")):
                continue
            if str(task_payload.get("source_workflow") or "").strip() == "workflow-ui" and str(task_payload.get("external_request_id") or "").strip() == "workflow-ui-global-graph-v1":
                target_task_dir = task_dir
                break
    if isinstance(target_task_dir, Path):
        nodes_root = target_task_dir / "nodes"
        if nodes_root.exists() and nodes_root.is_dir():
            for node_path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
                if not node_path.is_file() or node_path.suffix.lower() != ".json":
                    continue
                node = _json_load(node_path)
                if not node:
                    continue
                if str(node.get("record_state") or "active").strip().lower() == "deleted":
                    continue
                status = str(node.get("status") or "").strip().lower()
                if status not in {"running", "ready", "pending", "failed", "blocked"}:
                    continue
                agent_id = str(node.get("assigned_agent_id") or "").strip()
                agent_name = str(node.get("assigned_agent_name") or agent_id or "未指派").strip() or "未指派"
                key = agent_id or agent_name
                if key not in groups:
                    groups[key] = {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "running": [],
                        "queued": [],
                        "failed": [],
                        "blocked": [],
                    }
                item = {
                    "node_id": str(node.get("node_id") or "").strip(),
                    "node_name": str(node.get("node_name") or node.get("node_id") or "").strip(),
                    "status": status,
                    "status_text": str(node.get("status_text") or "").strip(),
                    "priority_label": str(node.get("priority_label") or node.get("priority") or "").strip(),
                }
                if status == "running":
                    groups[key]["running"].append(item)
                elif status == "failed":
                    groups[key]["failed"].append(item)
                elif status == "blocked":
                    groups[key]["blocked"].append(item)
                else:
                    groups[key]["queued"].append(item)
    agent_items = sorted(
        groups.values(),
        key=lambda item: (
            -(len(item["running"]) * 100 + len(item["queued"]) * 10 + len(item["failed"])),
            item["agent_name"],
        ),
    )
    for item in agent_items:
        item["running"] = item["running"][:4]
        item["queued"] = item["queued"][:4]
        item["failed"] = item["failed"][:4]
        item["blocked"] = item["blocked"][:4]

    schedule_preview = []
    db_path = (Path(cfg.root) / "state" / "workflow.db").resolve(strict=False)
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT schedule_id,schedule_name,enabled,next_trigger_at,last_trigger_at,last_result_status,last_result_ticket_id,last_result_node_id,updated_at
                FROM schedule_plans
                WHERE enabled=1 AND deleted_at=''
                ORDER BY updated_at DESC
                LIMIT 8
                """
            ).fetchall()
            schedule_preview = [dict(row) for row in rows]
        finally:
            conn.close()
    return {
        "assignment_workboard_agents": agent_items,
        "schedule_workboard_preview": schedule_preview,
        "schedule_plan_count": len(schedule_preview),
    }


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
        runtime_goal = _runtime_goal_payload(cfg)
        workboard = _workboard_payload(cfg, include_test_data=include_test_data)
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
                **runtime_goal,
                **workboard,
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
    runtime_goal = _runtime_goal_payload(cfg)
    workboard = _workboard_payload(cfg, include_test_data=include_test_data)
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
            **runtime_goal,
            **workboard,
        },
    )
    return True
