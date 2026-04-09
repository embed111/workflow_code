from __future__ import annotations

from workflow_app.server.services.codex_failure_contract import (
    build_codex_failure,
    build_retry_action,
    infer_codex_failure_detail_code,
)


def _assignment_load_runs(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id)
    return rows[: max(1, int(limit))]


def _assignment_selected_node_codex_failure(
    *,
    ticket_id: str,
    selected_node: dict[str, Any],
    latest_run: dict[str, Any],
    run_count: int,
) -> dict[str, Any]:
    current_run = latest_run if isinstance(latest_run, dict) else {}
    stored = current_run.get("codex_failure") if isinstance(current_run.get("codex_failure"), dict) else {}
    if stored:
        return stored
    failure_text = str(selected_node.get("failure_reason") or "").strip()
    if not failure_text:
        return {}
    return build_codex_failure(
        feature_key="assignment_node_execution",
        attempt_id=str(current_run.get("run_id") or selected_node.get("node_id") or "").strip(),
        attempt_count=max(1, int(run_count or 0)),
        failure_detail_code=infer_codex_failure_detail_code(
            failure_text,
            fallback="assignment_execution_failed",
        ),
        failure_message=failure_text,
        retry_action=build_retry_action(
            "rerun_assignment_node",
            payload={
                "ticket_id": str(ticket_id or "").strip(),
                "node_id": str(selected_node.get("node_id") or "").strip(),
                "run_id": str(current_run.get("run_id") or "").strip(),
            },
        ),
        trace_refs={
            "prompt": str(current_run.get("prompt_ref") or "").strip(),
            "stdout": str(current_run.get("stdout_ref") or "").strip(),
            "stderr": str(current_run.get("stderr_ref") or "").strip(),
            "result": str(current_run.get("result_ref") or "").strip(),
        },
        failed_at=str(
            current_run.get("finished_at")
            or current_run.get("updated_at")
            or selected_node.get("completed_at")
            or ""
        ).strip(),
    )


def _assignment_run_summary(root: Path, row: dict[str, Any], *, include_content: bool) -> dict[str, Any]:
    run_id = str(row.get("run_id") or "").strip()
    ticket_id = str(row.get("ticket_id") or "").strip()
    provider_pid = max(0, int(row.get("provider_pid") or 0))
    refs = _assignment_run_file_paths(root, ticket_id, run_id) if run_id and ticket_id else {}
    events_path = refs.get("events")
    prompt_path = refs.get("prompt")
    stdout_path = refs.get("stdout")
    stderr_path = refs.get("stderr")
    result_path = refs.get("result")
    prompt_ref = str(row.get("prompt_ref") or (prompt_path.as_posix() if isinstance(prompt_path, Path) else "")).strip()
    stdout_ref = str(row.get("stdout_ref") or (stdout_path.as_posix() if isinstance(stdout_path, Path) else "")).strip()
    stderr_ref = str(row.get("stderr_ref") or (stderr_path.as_posix() if isinstance(stderr_path, Path) else "")).strip()
    result_ref = str(row.get("result_ref") or (result_path.as_posix() if isinstance(result_path, Path) else "")).strip()
    events = _tail_assignment_run_events(events_path) if isinstance(events_path, Path) else []
    codex_failure = row.get("codex_failure") if isinstance(row.get("codex_failure"), dict) else {}
    return {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "node_id": str(row.get("node_id") or "").strip(),
        "provider": str(row.get("provider") or "").strip(),
        "workspace_path": str(row.get("workspace_path") or "").strip(),
        "status": _normalize_run_status(row.get("status") or "starting"),
        "status_text": _node_status_text(
            "running" if str(row.get("status") or "").strip().lower() == "running" else row.get("status") or ""
        ),
        "command_summary": str(row.get("command_summary") or "").strip(),
        "prompt_ref": prompt_ref,
        "stdout_ref": stdout_ref,
        "stderr_ref": stderr_ref,
        "result_ref": result_ref,
        "latest_event": str(row.get("latest_event") or "").strip(),
        "latest_event_at": str(row.get("latest_event_at") or "").strip(),
        "exit_code": int(row.get("exit_code") or 0),
        "started_at": str(row.get("started_at") or "").strip(),
        "finished_at": str(row.get("finished_at") or "").strip(),
        "created_at": str(row.get("created_at") or "").strip(),
        "updated_at": str(row.get("updated_at") or "").strip(),
        "provider_pid": provider_pid or None,
        "event_count": len(events),
        "events": events,
        "codex_failure": codex_failure,
        "prompt_text": (
            _read_assignment_run_text(prompt_ref, preview_chars=_assignment_run_preview_chars(prompt_ref))
            if include_content
            else ""
        ),
        "stdout_text": (
            _read_assignment_run_text(stdout_ref, preview_chars=_assignment_run_preview_chars(stdout_ref))
            if include_content
            else ""
        ),
        "stderr_text": (
            _read_assignment_run_text(stderr_ref, preview_chars=_assignment_run_preview_chars(stderr_ref))
            if include_content
            else ""
        ),
        "result_text": (
            _read_assignment_run_text(result_ref, preview_chars=_assignment_run_preview_chars(result_ref))
            if include_content
            else ""
        ),
    }


def _assignment_normalize_cancelled_run_summary(
    run_summary: dict[str, Any],
    *,
    selected_node: dict[str, Any],
    audit_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    current = dict(run_summary or {})
    if str(current.get("status") or "").strip().lower() != "cancelled":
        return current
    latest_event = str(current.get("latest_event") or "").strip()
    if "人工结束" not in latest_event:
        return current
    failure_reason = str(selected_node.get("failure_reason") or "").strip()
    has_stale_recovery_audit = any(
        str(item.get("action") or "").strip().lower() == "recover_stale_running"
        for item in list(audit_refs or [])
    )
    stale_failure = "运行句柄缺失" in failure_reason or "workflow 已重启" in failure_reason
    if not has_stale_recovery_audit and not stale_failure:
        return current
    current["latest_event"] = "检测到运行句柄缺失或 workflow 已重启，已自动结束当前批次，后台结果不再回写节点状态。"
    return current


def _assignment_management_actions(
    node: dict[str, Any],
    *,
    blocking_reasons: list[dict[str, Any]],
) -> list[str]:
    if not isinstance(node, dict) or not node:
        return []
    status = str(node.get("status") or "").strip().lower()
    actions: list[str] = []
    if status == "running":
        actions.extend(["mark-success", "mark-failed"])
    else:
        actions.append("override-status")
        if status == "failed":
            actions.append("rerun")
        actions.append("delete")
    actions.append("deliver-artifact")
    if list(node.get("artifact_paths") or []):
        actions.append("view-artifact")
    if status == "blocked" and not blocking_reasons and "override-status" not in actions:
        actions.append("override-status")
    seen: set[str] = set()
    ordered: list[str] = []
    for action in actions:
        key = str(action or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _assignment_status_detail_payload(
    root: Path,
    *,
    ticket_id: str,
    node_id: str = "",
    include_test_data: bool = True,
) -> dict[str, Any]:
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=include_test_data,
        reconcile_running=True,
        include_scheduler=False,
        include_serialized_nodes=False,
    )
    ticket_id = str(snapshot["graph_row"].get("ticket_id") or ticket_id).strip()
    selected_node = snapshot["node_map_by_id"].get(node_id) or _assignment_default_selected_node(snapshot["nodes"])
    selected_serialized = (
        _serialize_node(
            selected_node,
            node_map_by_id=snapshot["node_map_by_id"],
            upstream_map=snapshot["upstream_map"],
            downstream_map=snapshot["downstream_map"],
        )
        if selected_node
        else {}
    )
    blocking_reasons = list(selected_serialized.get("blocking_reasons") or [])
    management_actions = _assignment_management_actions(selected_serialized, blocking_reasons=blocking_reasons)
    if isinstance(selected_serialized, dict) and selected_serialized:
        selected_serialized["management_actions"] = list(management_actions)
    run_rows = (
        _assignment_load_runs(
            root,
            ticket_id=ticket_id,
            node_id=str(selected_serialized.get("node_id") or "").strip(),
            limit=5,
        )
        if selected_serialized
        else []
    )
    run_summaries = [
        _assignment_run_summary(root, row, include_content=index == 0)
        for index, row in enumerate(run_rows)
    ]
    audit_refs = []
    for row in _assignment_load_audit_records(
        root,
        ticket_id=ticket_id,
        node_id=str(selected_serialized.get("node_id") or "").strip(),
        limit=12,
    ):
        audit_refs.append(
            {
                "audit_id": str(row.get("audit_id") or "").strip(),
                "action": str(row.get("action") or "").strip(),
                "operator": str(row.get("operator") or "").strip(),
                "reason": str(row.get("reason") or "").strip(),
                "target_status": str(row.get("target_status") or "").strip(),
                "ref": str(row.get("ref") or "").strip(),
                "created_at": str(row.get("created_at") or "").strip(),
                "detail": dict(row.get("detail") or {}),
            }
        )
    run_summaries = [
        _assignment_normalize_cancelled_run_summary(
            run_summary,
            selected_node=selected_serialized,
            audit_refs=audit_refs,
        )
        for run_summary in run_summaries
    ]
    node_codex_failure = _assignment_selected_node_codex_failure(
        ticket_id=ticket_id,
        selected_node=selected_serialized,
        latest_run=run_summaries[0] if run_summaries else {},
        run_count=len(run_summaries),
    )
    if isinstance(selected_serialized, dict) and selected_serialized:
        selected_serialized["codex_failure"] = node_codex_failure
    return {
        "ticket_id": ticket_id,
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
        "selected_node": selected_serialized,
        "blocking_reasons": blocking_reasons,
        "available_actions": management_actions,
        "audit_refs": audit_refs,
        "codex_failure": node_codex_failure,
        "execution_chain": {
            "poll_mode": assignment_execution_refresh_mode(),
            "poll_interval_ms": DEFAULT_ASSIGNMENT_EXECUTION_POLL_INTERVAL_MS,
            "latest_run": run_summaries[0] if run_summaries else {},
            "recent_runs": run_summaries,
        },
    }


def _assignment_node_status_text(row: dict[str, Any]) -> str:
    return str(row.get("status") or "").strip().lower()


def _assignment_active_node_group(row: dict[str, Any]) -> int:
    status = _assignment_node_status_text(row)
    if status == "running":
        return 0
    if status == "ready":
        return 1
    if status == "pending":
        return 2
    if status == "blocked":
        return 3
    return 4


def _assignment_sort_active_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    items.sort(
        key=lambda row: (
            str(row.get("updated_at") or ""),
            str(row.get("created_at") or ""),
            str(row.get("node_id") or ""),
        ),
        reverse=True,
    )
    items.sort(
        key=lambda row: (
            _assignment_active_node_group(row),
            int(row.get("priority") or 0),
        )
    )
    return items


def _assignment_default_selected_node(rows: list[dict[str, Any]]) -> dict[str, Any]:
    best_row: dict[str, Any] = {}
    best_group: int | None = None
    best_recency: tuple[str, str, str, str] = ("", "", "", "")
    for row in list(rows or []):
        current = dict(row)
        status = _assignment_node_status_text(current)
        is_workflow_mainline = _assignment_is_workflow_mainline_node(current)
        if is_workflow_mainline and status == "running":
            group = 0
        elif is_workflow_mainline and status == "ready":
            group = 1
        elif is_workflow_mainline and status == "pending":
            group = 2
        elif is_workflow_mainline and status == "blocked":
            group = 3
        elif status == "running":
            group = 4
        elif status == "ready":
            group = 5
        elif status == "pending":
            group = 6
        elif status == "blocked":
            group = 7
        elif is_workflow_mainline:
            group = 8
        elif status in {"succeeded", "failed"}:
            group = 9
        else:
            group = 10
        recency = (
            str(current.get("updated_at") or ""),
            str(current.get("completed_at") or ""),
            str(current.get("created_at") or ""),
            str(current.get("node_id") or ""),
        )
        if best_group is None or group < best_group or (group == best_group and recency > best_recency):
            best_row = current
            best_group = group
            best_recency = recency
    return best_row


def _assignment_sort_completed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    items.sort(
        key=lambda row: (
            str(row.get("completed_at") or ""),
            str(row.get("created_at") or ""),
            str(row.get("node_id") or ""),
        ),
        reverse=True,
    )
    return items


def _assignment_build_node_catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": str(row.get("node_id") or "").strip(),
            "node_name": _assignment_display_node_name(row, fallback=str(row.get("node_id") or "").strip()),
            "status": _assignment_node_status_text(row),
            "priority": int(row.get("priority") or 0),
            "priority_label": assignment_priority_label(row.get("priority")),
        }
        for row in list(rows or [])
        if str(row.get("node_id") or "").strip()
    ]
