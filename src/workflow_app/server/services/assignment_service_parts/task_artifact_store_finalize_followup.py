from __future__ import annotations


def _assignment_finalize_followup_dispatch(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    run_id: str,
    target_status: str,
    suppress_dispatch: bool,
) -> dict[str, Any]:
    if suppress_dispatch:
        return {
            "ok": False,
            "suppressed": True,
            "reason": "suppressed_by_caller",
        }
    now_text = iso_ts(now_local())
    target_status_text = str(target_status or "").strip().lower() or "succeeded"
    try:
        dispatch_result = dispatch_assignment_next(
            root,
            ticket_id_text=ticket_id,
            operator="assignment-executor",
            include_test_data=True,
        )
    except Exception as exc:
        detail = {
            "run_id": str(run_id or "").strip(),
            "exception_type": type(exc).__name__,
        }
        try:
            _assignment_write_audit_entry(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
                action="followup_dispatch_failed",
                operator="assignment-executor",
                reason=_short_assignment_text(str(exc), 500) or "follow-up dispatch after finalize failed",
                target_status=target_status_text,
                detail=detail,
                created_at=now_text,
            )
        except Exception:
            pass
        return {
            "ok": False,
            "suppressed": False,
            "reason": "dispatch_exception",
            "detail": detail,
        }
    payload = dict(dispatch_result or {})
    dispatched = [dict(item) for item in list(payload.get("dispatched") or []) if isinstance(item, dict)]
    dispatched_runs = [dict(item) for item in list(payload.get("dispatched_runs") or []) if isinstance(item, dict)]
    skipped = [dict(item) for item in list(payload.get("skipped") or []) if isinstance(item, dict)]
    graph_overview = dict(payload.get("graph_overview") or {})
    metrics_summary = dict(graph_overview.get("metrics_summary") or {})
    status_counts = dict(metrics_summary.get("status_counts") or {})
    try:
        ready_node_count = max(0, int(status_counts.get("ready") or 0))
    except Exception:
        ready_node_count = 0
    if dispatched:
        return {
            "ok": True,
            "suppressed": False,
            "ready_node_count": ready_node_count,
            "dispatched_node_ids": [
                str(item.get("node_id") or "").strip()
                for item in dispatched
                if str(item.get("node_id") or "").strip()
            ],
            "dispatched_run_ids": [
                str(item.get("run_id") or "").strip()
                for item in dispatched_runs
                if str(item.get("run_id") or "").strip()
            ],
        }
    if ready_node_count > 0:
        reason_text = _short_assignment_text(
            (
                str((skipped[0] or {}).get("message") or "").strip()
                if skipped
                else str(payload.get("message") or "").strip()
            ),
            500,
        ) or "ready nodes remain after finalize follow-up dispatch"
        detail = {
            "run_id": str(run_id or "").strip(),
            "ready_node_count": ready_node_count,
            "skipped": skipped[:8],
            "message": str(payload.get("message") or "").strip(),
        }
        try:
            _assignment_write_audit_entry(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
                action="followup_dispatch_blocked",
                operator="assignment-executor",
                reason=reason_text,
                target_status=target_status_text,
                detail=detail,
                created_at=now_text,
            )
        except Exception:
            pass
        return {
            "ok": False,
            "suppressed": False,
            "reason": "ready_nodes_remain",
            "detail": detail,
        }
    return {
        "ok": False,
        "suppressed": False,
        "reason": "no_ready_nodes",
        "ready_node_count": ready_node_count,
    }
