from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import assignment_service


_RUNTIME_SYMBOLS: dict[str, Any] = {}


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    if not isinstance(symbols, dict):
        return
    _RUNTIME_SYMBOLS.clear()
    for key, value in symbols.items():
        if str(key).startswith("__"):
            continue
        _RUNTIME_SYMBOLS[str(key)] = value


def _runtime_symbol(name: str) -> Any:
    return _RUNTIME_SYMBOLS.get(name)


def _safe_schedule_token(value: Any, *, max_len: int = 160) -> str:
    fn = _runtime_symbol("_safe_token")
    if callable(fn):
        return str(fn(value, max_len=max_len) or "")
    text = str(value or "").strip()
    if not text:
        return ""
    out: list[str] = []
    for ch in text[:max_len]:
        if ch.isalnum() or ch in {"-", "_", ".", ":"}:
            out.append(ch)
    return "".join(out)


def _schedule_error(status_code: int, message: str, code: str) -> Exception:
    error_cls = _runtime_symbol("ScheduleCenterError")
    if isinstance(error_cls, type) and issubclass(error_cls, Exception):
        return error_cls(int(status_code), str(message), str(code))
    return RuntimeError(str(message))


def _resolve_tasks_root(root: Path) -> Path:
    resolver = _runtime_symbol("resolve_artifact_root_path")
    if not callable(resolver):
        return Path("")
    try:
        artifact_root = Path(resolver(root)).resolve(strict=False)
    except Exception:
        return Path("")
    return (artifact_root / "tasks").resolve(strict=False)


def schedule_trigger_node_id(trigger_instance_id: str) -> str:
    trigger_key = _safe_schedule_token(trigger_instance_id, max_len=150)
    if not trigger_key:
        return ""
    return f"node-{trigger_key}"


def _scan_ticket_nodes(
    nodes_dir: Path,
    *,
    schedule_key: str,
    trigger_key: str,
    ticket_id: str,
) -> dict[str, str]:
    if not nodes_dir.exists() or not nodes_dir.is_dir():
        return {}
    for path in sorted(
        nodes_dir.glob("*.json"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("source_schedule_id") or "").strip() != schedule_key:
            continue
        if str(payload.get("trigger_instance_id") or "").strip() != trigger_key:
            continue
        node_id = str(payload.get("node_id") or "").strip()
        if node_id and ticket_id:
            return {
                "assignment_ticket_id": ticket_id,
                "assignment_node_id": node_id,
            }
    return {}


def _scan_ticket_schedule_nodes(
    nodes_dir: Path,
    *,
    schedule_key: str,
    ticket_id: str,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not nodes_dir.exists() or not nodes_dir.is_dir():
        return items
    for path in sorted(
        nodes_dir.glob("*.json"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("source_schedule_id") or "").strip() != schedule_key:
            continue
        if str(payload.get("record_state") or "active").strip().lower() == "deleted":
            continue
        node_id = str(payload.get("node_id") or "").strip()
        if not node_id:
            continue
        items.append(
            {
                "assignment_ticket_id": ticket_id,
                "assignment_node_id": node_id,
                "trigger_instance_id": str(payload.get("trigger_instance_id") or "").strip(),
                "assignment_status": str(payload.get("status") or "").strip().lower(),
                "planned_trigger_at": str(payload.get("planned_trigger_at") or "").strip(),
            }
        )
    return items


def find_schedule_assignment_ref(
    root: Path,
    *,
    schedule_id: str,
    trigger_instance_id: str,
    ticket_id: str = "",
) -> dict[str, str]:
    schedule_key = _safe_schedule_token(schedule_id)
    trigger_key = _safe_schedule_token(trigger_instance_id)
    if not schedule_key or not trigger_key:
        return {}
    tasks_root = _resolve_tasks_root(root)
    if not tasks_root.exists() or not tasks_root.is_dir():
        return {}
    ticket_key = _safe_schedule_token(ticket_id)
    if ticket_key:
        recovered = _scan_ticket_nodes(
            tasks_root / ticket_key / "nodes",
            schedule_key=schedule_key,
            trigger_key=trigger_key,
            ticket_id=ticket_key,
        )
        if recovered:
            return recovered
    for task_dir in sorted(
        (item for item in tasks_root.iterdir() if item.is_dir()),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    ):
        recovered = _scan_ticket_nodes(
            task_dir / "nodes",
            schedule_key=schedule_key,
            trigger_key=trigger_key,
            ticket_id=str(task_dir.name or "").strip(),
        )
        if recovered:
            return recovered
    return {}


def find_schedule_nodes_for_triggers(
    root: Path,
    *,
    schedule_id: str,
    trigger_instance_ids: list[str] | tuple[str, ...] | set[str],
    ticket_id: str = "",
) -> list[dict[str, str]]:
    schedule_key = _safe_schedule_token(schedule_id)
    trigger_keys = {
        _safe_schedule_token(item)
        for item in list(trigger_instance_ids or [])
        if _safe_schedule_token(item)
    }
    if not schedule_key or not trigger_keys:
        return []
    tasks_root = _resolve_tasks_root(root)
    if not tasks_root.exists() or not tasks_root.is_dir():
        return []
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _append_refs(nodes_dir: Path, current_ticket_id: str) -> None:
        for item in _scan_ticket_schedule_nodes(
            nodes_dir,
            schedule_key=schedule_key,
            ticket_id=current_ticket_id,
        ):
            trigger_id = str(item.get("trigger_instance_id") or "").strip()
            if trigger_id not in trigger_keys:
                continue
            node_key = (
                str(item.get("assignment_ticket_id") or "").strip(),
                str(item.get("assignment_node_id") or "").strip(),
            )
            if not all(node_key) or node_key in seen:
                continue
            seen.add(node_key)
            refs.append(item)

    ticket_key = _safe_schedule_token(ticket_id)
    if ticket_key:
        _append_refs(tasks_root / ticket_key / "nodes", ticket_key)
    for task_dir in sorted(
        (item for item in tasks_root.iterdir() if item.is_dir()),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    ):
        current_ticket_id = str(task_dir.name or "").strip()
        if ticket_key and current_ticket_id == ticket_key:
            continue
        _append_refs(task_dir / "nodes", current_ticket_id)
    return refs


def replace_pending_schedule_nodes(
    root: Path,
    *,
    schedule_id: str,
    trigger_instance_ids: list[str] | tuple[str, ...] | set[str],
    ticket_id: str = "",
    operator: str = "schedule-worker",
) -> dict[str, Any]:
    refs = find_schedule_nodes_for_triggers(
        root,
        schedule_id=schedule_id,
        trigger_instance_ids=trigger_instance_ids,
        ticket_id=ticket_id,
    )
    deleted: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for item in refs:
        assignment_status = str(item.get("assignment_status") or "").strip().lower()
        if assignment_status in {"running", "succeeded", "failed"}:
            skipped.append(
                {
                    **item,
                    "code": "schedule_node_not_replaceable",
                    "reason": f"node status is {assignment_status or 'unknown'}",
                }
            )
            continue
        try:
            result = assignment_service.delete_assignment_node(
                root,
                ticket_id_text=str(item.get("assignment_ticket_id") or "").strip(),
                node_id_text=str(item.get("assignment_node_id") or "").strip(),
                operator=operator,
                reason="superseded by newer schedule trigger",
                include_test_data=True,
            )
            deleted.append(
                {
                    **item,
                    "audit_id": str(result.get("audit_id") or "").strip(),
                }
            )
        except Exception as exc:
            skipped.append(
                {
                    **item,
                    "code": str(getattr(exc, "code", "") or "").strip() or "delete_assignment_node_failed",
                    "reason": str(exc),
                }
            )
    return {
        "matched": refs,
        "deleted": deleted,
        "skipped": skipped,
    }


def ensure_global_assignment_graph(cfg: Any) -> str:
    canonical_ticket_fn = _runtime_symbol("_assignment_ensure_workflow_ui_global_graph_ticket")
    if callable(canonical_ticket_fn):
        try:
            canonical_ticket_id = str(canonical_ticket_fn(cfg.root) or "").strip()
        except Exception:
            canonical_ticket_id = ""
        if canonical_ticket_id:
            return canonical_ticket_id

    graph_name = str(_runtime_symbol("SCHEDULE_ASSIGNMENT_GRAPH_NAME") or "任务中心全局主图").strip() or "任务中心全局主图"
    source_workflow = str(_runtime_symbol("SCHEDULE_ASSIGNMENT_SOURCE_WORKFLOW") or "workflow-ui").strip() or "workflow-ui"
    request_id = str(_runtime_symbol("SCHEDULE_ASSIGNMENT_GRAPH_REQUEST_ID") or "workflow-ui-global-graph-v1").strip() or "workflow-ui-global-graph-v1"
    created = assignment_service.create_assignment_graph(
        cfg,
        {
            "graph_name": graph_name,
            "source_workflow": source_workflow,
            "summary": "任务中心手动创建（全局主图）",
            "review_mode": "none",
            "external_request_id": request_id,
            "operator": "schedule-worker",
        },
    )
    ticket_id = str(created.get("ticket_id") or "").strip()
    if ticket_id:
        return ticket_id
    raise _schedule_error(500, "global assignment graph missing", "schedule_assignment_graph_missing")


def build_schedule_assignment_goal(
    schedule: dict[str, Any],
    *,
    planned_trigger_at: str,
    trigger_rule_summary: str,
) -> str:
    goal = "\n".join(
        [
            f"计划名称：{str(schedule.get('schedule_name') or '').strip()}",
            f"计划时间：{planned_trigger_at}",
            f"命中规则：{trigger_rule_summary}",
            "",
            "launch_summary",
            str(schedule.get("launch_summary") or "").strip() or "-",
            "",
            "execution_checklist",
            str(schedule.get("execution_checklist") or "").strip() or "-",
            "",
            "done_definition",
            str(schedule.get("done_definition") or "").strip() or "-",
        ]
    ).strip()
    # Schedule payloads are allowed to evolve, but assignment node_goal still has a hard cap.
    # Clamp here so richer PM prompts do not turn into create_failed during trigger handling.
    return goal[:3800]


def create_schedule_node(
    cfg: Any,
    schedule: dict[str, Any],
    *,
    trigger_instance_id: str,
    planned_trigger_at: str,
    trigger_rule_summary: str,
) -> dict[str, Any]:
    ticket_id = ensure_global_assignment_graph(cfg)
    schedule_id = str(schedule.get("schedule_id") or "").strip()
    recovered = find_schedule_assignment_ref(
        cfg.root,
        schedule_id=schedule_id,
        trigger_instance_id=trigger_instance_id,
        ticket_id=ticket_id,
    )
    if recovered:
        return {
            "ticket_id": ticket_id,
            "node_id": str(recovered.get("assignment_node_id") or "").strip(),
        }
    planned_label = planned_trigger_at.replace("T", " ").replace("+08:00", "")
    payload = {
        "node_id": schedule_trigger_node_id(trigger_instance_id),
        "node_name": f"{str(schedule.get('schedule_name') or '').strip()} / {planned_label}",
        "assigned_agent_id": str(schedule.get("assigned_agent_id") or "").strip(),
        "priority": str(schedule.get("priority") or "P1"),
        "node_goal": build_schedule_assignment_goal(
            schedule,
            planned_trigger_at=planned_trigger_at,
            trigger_rule_summary=trigger_rule_summary,
        ),
        "expected_artifact": str(schedule.get("expected_artifact") or "").strip(),
        "delivery_mode": str(schedule.get("delivery_mode") or "none").strip().lower() or "none",
        "delivery_receiver_agent_id": str(schedule.get("delivery_receiver_agent_id") or "").strip(),
        "source_schedule_id": schedule_id,
        "planned_trigger_at": planned_trigger_at,
        "trigger_instance_id": trigger_instance_id,
        "trigger_rule_summary": trigger_rule_summary,
        "operator": "schedule-worker",
    }
    try:
        created = assignment_service.create_assignment_node(
            cfg,
            ticket_id,
            payload,
            include_test_data=True,
        )
    except Exception as exc:
        if str(getattr(exc, "code", "") or "").strip() == "node_id_duplicated":
            recovered = find_schedule_assignment_ref(
                cfg.root,
                schedule_id=schedule_id,
                trigger_instance_id=trigger_instance_id,
                ticket_id=ticket_id,
            )
            node_id = str(recovered.get("assignment_node_id") or "").strip()
            if node_id:
                return {"ticket_id": ticket_id, "node_id": node_id}
        raise
    node = dict(created.get("node") or {})
    node_id = str(node.get("node_id") or "").strip()
    if node_id:
        return {"ticket_id": ticket_id, "node_id": node_id}
    recovered = find_schedule_assignment_ref(
        cfg.root,
        schedule_id=schedule_id,
        trigger_instance_id=trigger_instance_id,
        ticket_id=ticket_id,
    )
    node_id = str(recovered.get("assignment_node_id") or "").strip()
    if node_id:
        return {"ticket_id": ticket_id, "node_id": node_id}
    raise _schedule_error(500, "schedule assignment node missing", "schedule_assignment_node_missing")


def request_assignment_dispatch(root: Path, ticket_id: str) -> dict[str, str]:
    def _dispatch_message(result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return ""
        skipped = list(result.get("skipped") or [])
        if skipped:
            first = dict(skipped[0] or {})
            return (
                str(first.get("message") or "").strip()
                or str(first.get("code") or "").strip()
            )
        if list(result.get("dispatched") or []):
            return "dispatch_requested"
        return str(result.get("message") or "").strip()

    dispatch_result = assignment_service.dispatch_assignment_next(
        root,
        ticket_id_text=ticket_id,
        operator="schedule-worker",
        include_test_data=True,
    )
    graph = dict(dispatch_result.get("graph_overview") or {})
    scheduler_state = str(graph.get("scheduler_state") or "").strip().lower()
    if str(dispatch_result.get("message") or "").strip().lower() == "scheduler_not_running" or scheduler_state == "idle":
        resume_result = assignment_service.resume_assignment_scheduler(
            root,
            ticket_id_text=ticket_id,
            operator="schedule-worker",
            pause_note="schedule auto resume",
            include_test_data=True,
        )
        resume_message = _dispatch_message(dict(resume_result.get("dispatch_result") or {}))
        if resume_message:
            return {"dispatch_status": "requested", "dispatch_message": resume_message}
        return {"dispatch_status": "requested", "dispatch_message": "resume_scheduler_requested"}
    return {
        "dispatch_status": "requested",
        "dispatch_message": _dispatch_message(dispatch_result) or "dispatch_requested",
    }
