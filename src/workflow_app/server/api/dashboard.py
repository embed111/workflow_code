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


def _running_agent_count_from_workboard(workboard: dict) -> int:
    return sum(
        1
        for item in list((workboard or {}).get("assignment_workboard_agents") or [])
        if list((item or {}).get("running") or [])
    )


def _schedule_preview_payload(cfg) -> tuple[list[dict], int]:
    db_path = (Path(cfg.root) / "state" / "workflow.db").resolve(strict=False)
    if not db_path.exists():
        return [], 0
    try:
        from ..services import schedule_service

        preview_payload = schedule_service.list_schedule_preview(Path(cfg.root), limit=8)
        return list(preview_payload.get("items") or []), int(preview_payload.get("total") or 0)
    except Exception:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            total_row = conn.execute(
                """
                SELECT COUNT(1) AS total_count
                FROM schedule_plans
                WHERE enabled=1 AND deleted_at=''
                """
            ).fetchone()
            rows = conn.execute(
                """
                SELECT schedule_id,schedule_name,enabled,next_trigger_at,last_trigger_at,last_result_status,last_result_ticket_id,last_result_node_id,updated_at
                FROM schedule_plans
                WHERE enabled=1 AND deleted_at=''
                ORDER BY updated_at DESC
                LIMIT 8
                """
            ).fetchall()
            return [dict(row) for row in rows], int((total_row or {"total_count": 0})["total_count"] or 0)
        finally:
            conn.close()


def _compact_text(raw: str, limit: int = 120) -> str:
    text = " ".join(str(raw or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _event_payload_from_message(raw: str) -> dict:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        extractor = getattr(ws, "_assignment_extract_json_objects", None)
        if not callable(extractor):
            return {}
        try:
            payloads = extractor(text)
        except Exception:
            return {}
        if not payloads:
            return {}
        payload = payloads[-1]
        return payload if isinstance(payload, dict) else {}


def _command_stage_snapshot(command_text: str) -> tuple[str, str]:
    command = str(command_text or "").strip()
    normalized = " ".join(command.lower().split())
    if not normalized:
        return "", ""
    if "docs/workflow/governance/pm版本推进计划.md" in normalized:
        return "正在对齐版本计划", "最近命令：读取 PM 版本推进计划"
    if "docs/workflow/requirements/需求详情-pm持续唤醒与清醒维持.md" in normalized:
        return "正在对齐持续唤醒需求", "最近命令：读取 pm 持续唤醒需求"
    if "runtime-upgrade/status" in normalized:
        return "正在复核升级门禁", "最近命令：读取 /api/runtime-upgrade/status"
    if any(token in normalized for token in ("/api/status", "/api/schedules", "/api/assignments/", "/healthz")):
        return "正在复核 live 运行态", "最近命令：读取 healthz / status / assignments / schedules"
    if any(
        token in normalized
        for token in (
            "agents.md",
            ".codex/soul.md",
            ".codex/user.md",
            ".codex/memory",
            ".codex/experience",
        )
    ):
        return "正在补齐读链上下文", "最近命令：读取治理、经验或记忆链文件"
    if "check_workspace_line_budget.py" in normalized:
        return "正在检查行数门禁", "最近命令：执行 workspace line budget"
    if "run_acceptance_workflow_gate.py" in normalized:
        return "正在跑 workflow gate", "最近命令：执行 workflow gate"
    if "verify_assignment_workboard_signal_cards.js" in normalized:
        return "正在验证 workboard 阶段信号", "最近命令：执行 signal cards probe"
    if "verify_assignment_" in normalized or "scripts/acceptance/" in normalized:
        return "正在跑定向验收", "最近命令：执行 assignment 定向验收"
    if "py_compile" in normalized:
        return "正在检查 Python 语法", "最近命令：执行 py_compile"
    if "check_web_client_bundle_syntax.js" in normalized:
        return "正在检查前端 bundle 语法", "最近命令：执行 web client bundle syntax probe"
    if "git -c" in normalized or "git -c " in normalized or "git -c" in normalized or "git -c ." in normalized or "git -c ." in normalized:
        return "正在检查工作区边界", "最近命令：查看 Git 状态"
    if "git -c .repository" in normalized or "git -c" in normalized or "git -c" in normalized:
        return "正在检查工作区边界", "最近命令：查看 Git 状态"
    if "git -c" in normalized or "git -c " in normalized or "git -c" in normalized:
        return "正在检查工作区边界", "最近命令：查看 Git 状态"
    if "git -c" in normalized or "git -c " in normalized or "git -c" in normalized:
        return "正在检查工作区边界", "最近命令：查看 Git 状态"
    if "git -c" in normalized or "git -c " in normalized:
        return "正在检查工作区边界", "最近命令：查看 Git 状态"
    if "git -c" in normalized or "git -c" in normalized or "git -c ." in normalized or "git -c .repository" in normalized:
        return "正在检查工作区边界", "最近命令：查看 Git 状态"
    if "git -c" in normalized or "git -c" in normalized or "git status" in normalized:
        return "正在检查工作区边界", "最近命令：查看 Git 状态"
    if "invoke-restmethod" in normalized:
        return "正在核对 live API", "最近命令：请求本地 workflow API"
    if "get-content" in normalized or "rg " in normalized or "rg.exe" in normalized:
        return "正在读取本地文件", "最近命令：读取本地文件或日志"
    if "node " in normalized:
        return "正在执行前端探针", "最近命令：执行 Node 验收脚本"
    if "python " in normalized:
        return "正在执行本地验证", "最近命令：执行 Python 脚本"
    return "正在执行命令探针", _compact_text(command, 96)


def _event_stage_snapshot(event: dict) -> dict:
    row = dict(event or {})
    created_at = str(row.get("created_at") or "").strip()
    event_type = str(row.get("event_type") or "").strip().lower()
    payload = _event_payload_from_message(row.get("message"))
    payload_type = str(payload.get("type") or "").strip().lower()
    if payload_type in {"thread.started", "turn.started"}:
        label = "正在进入执行上下文" if payload_type == "thread.started" else "正在开始本轮推理"
        return {
            "latest_run_stage_label": label,
            "latest_run_stage_detail": "",
            "latest_run_stage_at": created_at,
        }
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    item_type = str(item.get("type") or "").strip().lower()
    if item_type == "agent_message":
        message_text = str(item.get("text") or "").strip()
        if not message_text:
            return {}
        return {
            "latest_run_stage_label": "正在整理当前判断",
            "latest_run_stage_detail": _compact_text(message_text.splitlines()[0], 120),
            "latest_run_stage_at": created_at,
        }
    if item_type == "command_execution":
        label, detail = _command_stage_snapshot(str(item.get("command") or ""))
        if not label:
            return {}
        if str(item.get("status") or "").strip().lower() == "failed":
            error_line = _compact_text(str(item.get("aggregated_output") or "").splitlines()[0], 120)
            if error_line:
                detail = error_line
        return {
            "latest_run_stage_label": label,
            "latest_run_stage_detail": detail,
            "latest_run_stage_at": created_at,
        }
    message_text = str(row.get("message") or "").strip()
    if event_type == "provider_start" or "provider 已启动" in message_text.lower():
        return {
            "latest_run_stage_label": "Provider 已启动",
            "latest_run_stage_detail": "运行上下文已经拉起，正在持续推进。",
            "latest_run_stage_at": created_at,
        }
    return {}


def _latest_event_stage_snapshot(run_summary: dict) -> dict:
    latest_event = str((run_summary or {}).get("latest_event") or "").strip()
    latest_event_at = str((run_summary or {}).get("latest_event_at") or "").strip()
    payload = _event_payload_from_message(latest_event)
    if isinstance(payload, dict) and payload:
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "agent_message":
            message_text = str(item.get("text") or "").strip()
            if message_text:
                return {
                    "latest_run_stage_label": "正在整理当前判断",
                    "latest_run_stage_detail": _compact_text(message_text.splitlines()[0], 120),
                    "latest_run_stage_at": latest_event_at,
                }
        if item_type == "command_execution":
            label, detail = _command_stage_snapshot(str(item.get("command") or ""))
            if label:
                return {
                    "latest_run_stage_label": label,
                    "latest_run_stage_detail": detail,
                    "latest_run_stage_at": latest_event_at,
                }
        payload_type = str(payload.get("type") or "").strip().lower()
        if payload_type in {"thread.started", "turn.started"}:
            label = "正在进入执行上下文" if payload_type == "thread.started" else "正在开始本轮推理"
            return {
                "latest_run_stage_label": label,
                "latest_run_stage_detail": "",
                "latest_run_stage_at": latest_event_at,
            }
    lowered = latest_event.lower()
    if "provider 已启动" in lowered:
        return {
            "latest_run_stage_label": "Provider 已启动",
            "latest_run_stage_detail": "运行上下文已经拉起，正在持续推进。",
            "latest_run_stage_at": latest_event_at,
        }
    if "自动重试中" in latest_event:
        return {
            "latest_run_stage_label": "正在自动重试",
            "latest_run_stage_detail": _compact_text(latest_event, 120),
            "latest_run_stage_at": latest_event_at,
        }
    if latest_event:
        return {
            "latest_run_stage_label": "正在推进当前任务",
            "latest_run_stage_detail": _compact_text(latest_event, 120),
            "latest_run_stage_at": latest_event_at,
        }
    return {}


def _running_node_run_snapshot(root: Path, *, ticket_id: str, node_id: str) -> dict:
    load_runs = getattr(ws, "_assignment_load_runs", None)
    run_summary = getattr(ws, "_assignment_run_summary", None)
    if not callable(load_runs) or not callable(run_summary):
        return {}
    try:
        run_rows = load_runs(root, ticket_id=ticket_id, node_id=node_id, limit=1)
    except Exception:
        return {}
    if not run_rows:
        return {}
    try:
        latest_run = run_summary(root, run_rows[0], include_content=False)
    except Exception:
        return {}
    current = dict(latest_run or {})
    events = list(current.get("events") or [])
    stage_snapshot = {}
    for event in reversed(events):
        stage_snapshot = _event_stage_snapshot(event)
        if stage_snapshot:
            break
    if not stage_snapshot:
        stage_snapshot = _latest_event_stage_snapshot(current)
    return {
        "latest_run_id": str(current.get("run_id") or "").strip(),
        "latest_run_status": str(current.get("status") or "").strip(),
        "latest_run_event": str(current.get("latest_event") or "").strip(),
        "latest_run_event_at": str(current.get("latest_event_at") or "").strip(),
        **stage_snapshot,
    }


def _workboard_payload(cfg, *, include_test_data: bool) -> dict:
    resolver = getattr(ws, "resolve_artifact_root_path", None)
    if not callable(resolver):
        return {
            "assignment_workboard_agents": [],
            "assignment_workboard_summary": {
                "active_agent_count": 0,
                "running_task_count": 0,
                "queued_task_count": 0,
                "failed_task_count": 0,
                "blocked_task_count": 0,
            },
            "schedule_workboard_preview": [],
            "schedule_plan_count": 0,
            "schedule_total": 0,
            "active_agent_count": 0,
            "queued_task_count": 0,
            "failed_task_count": 0,
            "blocked_task_count": 0,
            "workflow_mainline_handoff_pending": False,
            "workflow_mainline_handoff_note": "",
        }
    artifact_root = Path(resolver(cfg.root)).resolve(strict=False)
    tasks_root = (artifact_root / "tasks").resolve(strict=False)
    groups = {}
    run_snapshot_cache: dict[str, dict] = {}
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
            raw_nodes = []
            for node_path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
                if not node_path.is_file() or node_path.suffix.lower() != ".json":
                    continue
                node = _json_load(node_path)
                if not node:
                    continue
                if str(node.get("record_state") or "active").strip().lower() == "deleted":
                    continue
                raw_nodes.append(node)
            for node in ws._assignment_project_live_run_status_for_nodes(
                cfg.root,
                ticket_id=str(target_task_dir.name or "").strip(),
                node_records=raw_nodes,
            ):
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
                run_snapshot = {}
                if status == "running" and node_id:
                    cache_key = f"{current_ticket_id}:{node_id}"
                    run_snapshot = run_snapshot_cache.get(cache_key) or {}
                    if not run_snapshot:
                        run_snapshot = _running_node_run_snapshot(
                            artifact_root,
                            ticket_id=current_ticket_id,
                            node_id=node_id,
                        )
                        run_snapshot_cache[cache_key] = run_snapshot
                item = {
                    "node_id": str(node.get("node_id") or "").strip(),
                    "node_name": ws._assignment_display_node_name(
                        node,
                        fallback=str(node.get("node_id") or "").strip(),
                    ),
                    "status": status,
                    "status_text": str(node.get("status_text") or "").strip(),
                    "priority_label": str(node.get("priority_label") or node.get("priority") or "").strip(),
                    "planned_trigger_at": str(node.get("planned_trigger_at") or "").strip(),
                    "created_at": str(node.get("created_at") or "").strip(),
                    "updated_at": str(node.get("updated_at") or "").strip(),
                    "is_workflow_mainline": bool(ws._assignment_is_workflow_mainline_node(node)),
                    "is_workflow_patrol": bool(ws._assignment_is_workflow_patrol_node(node)),
                    **run_snapshot,
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
    active_agent_count = 0
    running_task_count = 0
    queued_task_count = 0
    failed_task_count = 0
    blocked_task_count = 0
    for item in agent_items:
        running_count = len(list(item.get("running") or []))
        queued_count = len(list(item.get("queued") or []))
        failed_count = len(list(item.get("failed") or []))
        blocked_count = len(list(item.get("blocked") or []))
        running_task_count += running_count
        queued_task_count += queued_count
        failed_task_count += failed_count
        blocked_task_count += blocked_count
        if running_count or queued_count:
            active_agent_count += 1
        item["running"] = list(item.get("running") or [])[:4]
        item["queued"] = list(item.get("queued") or [])[:4]
        item["failed"] = list(item.get("failed") or [])[:4]
        item["blocked"] = list(item.get("blocked") or [])[:4]
        running_items = list(item.get("running") or [])
        queued_items = list(item.get("queued") or [])
        running_mainline = next(
            (
                row
                for row in running_items
                if bool(row.get("is_workflow_mainline"))
                or str(row.get("node_name") or "").strip().startswith("[持续迭代] workflow")
            ),
            {},
        )
        queued_mainline = next(
            (
                row
                for row in queued_items
                if bool(row.get("is_workflow_mainline"))
                or str(row.get("node_name") or "").strip().startswith("[持续迭代] workflow")
            ),
            {},
        )
        patrol_running = next(
            (
                row
                for row in running_items
                if bool(row.get("is_workflow_patrol"))
                or str(row.get("node_name") or "").strip().startswith("pm持续唤醒 - workflow 主线巡检")
            ),
            {},
        )
        handoff_pending = bool(queued_mainline) and not bool(running_mainline)
        handoff_note = ""
        if handoff_pending:
            handoff_note = (
                "保底巡检仍在运行，真正的 [持续迭代] workflow 还在待执行。"
                if patrol_running
                else "真正的 [持续迭代] workflow 还在待执行。"
            )
        item["workflow_mainline_handoff_pending"] = handoff_pending
        item["workflow_mainline_handoff_note"] = handoff_note

    schedule_preview, schedule_total = _schedule_preview_payload(cfg)
    workflow_group = next(
        (
            item
            for item in list(agent_items or [])
            if str(item.get("agent_id") or "").strip().lower() == "workflow"
        ),
        {},
    )
    return {
        "assignment_workboard_agents": agent_items,
        "assignment_workboard_summary": {
            "active_agent_count": active_agent_count,
            "running_task_count": running_task_count,
            "queued_task_count": queued_task_count,
            "failed_task_count": failed_task_count,
            "blocked_task_count": blocked_task_count,
        },
        "schedule_workboard_preview": schedule_preview,
        "schedule_plan_count": schedule_total,
        "schedule_total": schedule_total,
        "active_agent_count": active_agent_count,
        "queued_task_count": queued_task_count,
        "failed_task_count": failed_task_count,
        "blocked_task_count": blocked_task_count,
        "workflow_mainline_handoff_pending": bool(workflow_group.get("workflow_mainline_handoff_pending")),
        "workflow_mainline_handoff_note": str(workflow_group.get("workflow_mainline_handoff_note") or "").strip(),
    }


def _assignment_runtime_with_workboard_fallback(
    assignment_runtime: dict,
    workboard: dict,
) -> dict:
    runtime_payload = dict(assignment_runtime or {})
    summary = dict((workboard or {}).get("assignment_workboard_summary") or {})
    runtime_running = int(runtime_payload.get("running_task_count") or 0)
    summary_running = int(summary.get("running_task_count") or 0)
    if runtime_running <= 0 and summary_running > 0:
        runtime_payload["running_task_count"] = summary_running
        runtime_payload["running_agent_count"] = _running_agent_count_from_workboard(workboard)
        runtime_payload["active_execution_count"] = summary_running
        runtime_payload["agent_call_count"] = summary_running
    return runtime_payload


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    root_ready = bool(ctx.get("root_ready"))
    root_error = str(ctx.get("root_error") or "")
    root_text = str(ctx.get("root_text") or "")
    session_running_task_count = int(ws.active_runtime_task_count(state, root=cfg.root))
    fetched_at = datetime.now(timezone.utc).isoformat()

    if path != "/api/status" and path != "/api/dashboard":
        return False

    if path == "/api/status":
        include_test_data = ws.current_show_test_data(cfg, state)
        workboard = _workboard_payload(cfg, include_test_data=include_test_data)
        assignment_runtime = _assignment_runtime_with_workboard_fallback(
            ws.get_assignment_runtime_metrics(cfg.root, include_test_data=include_test_data),
            workboard,
        )
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
                "fetched_at": fetched_at,
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
    workboard = _workboard_payload(cfg, include_test_data=include_test_data)
    assignment_runtime = _assignment_runtime_with_workboard_fallback(
        ws.get_assignment_runtime_metrics(cfg.root, include_test_data=include_test_data),
        workboard,
    )
    assignment_running_task_count = int(assignment_runtime.get("running_task_count") or 0)
    assignment_running_agent_count = int(assignment_runtime.get("running_agent_count") or 0)
    assignment_active_execution_count = int(assignment_runtime.get("active_execution_count") or 0)
    assignment_agent_call_count = int(assignment_runtime.get("agent_call_count") or 0)
    running_task_count = max(0, session_running_task_count + assignment_running_task_count)
    agent_call_count = max(0, session_running_task_count + assignment_agent_call_count)
    policy_fields = ws.show_test_data_policy_fields(cfg, state)
    runtime_goal = _runtime_goal_payload(cfg)
    handler.send_json(
        200,
        {
            **ws.dashboard(cfg, include_test_data=include_test_data),
            **policy_fields,
            "include_test_data": bool(include_test_data),
            "fetched_at": fetched_at,
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
