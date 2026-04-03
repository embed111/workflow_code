from __future__ import annotations

import json
import re

from ..bootstrap import web_server_runtime as ws


def _parse_int_query(query: dict, key: str, default: int) -> int:
    try:
        return int((query.get(key) or [str(default)])[0])
    except Exception:
        return int(default)


def _assignment_sse_write(handler, *, event: str, payload: dict, event_id: int | str = "", retry_ms: int = 0) -> bool:
    lines: list[str] = []
    if retry_ms > 0:
        lines.append(f"retry: {max(500, int(retry_ms))}")
    if str(event_id or "").strip():
        lines.append(f"id: {str(event_id).strip()}")
    if str(event or "").strip():
        lines.append(f"event: {str(event).strip()}")
    data = json.dumps(payload, ensure_ascii=False)
    for line in (data.splitlines() or [""]):
        lines.append(f"data: {line}")
    raw = ("\n".join(lines) + "\n\n").encode("utf-8")
    try:
        handler.wfile.write(raw)
        handler.wfile.flush()
        return True
    except Exception:
        return False


def _assignment_sse_comment(handler, text: str) -> bool:
    raw = f": {str(text or '').strip()}\n\n".encode("utf-8")
    try:
        handler.wfile.write(raw)
        handler.wfile.flush()
        return True
    except Exception:
        return False


def _assignment_stream_last_seq(handler, query: dict) -> int:
    header_value = str(handler.headers.get("Last-Event-ID") or "").strip()
    query_value = str((query.get("last_seq") or [""])[0] or "").strip()
    raw = header_value or query_value
    try:
        return max(0, int(raw))
    except Exception:
        return 0


def _handle_assignment_events_stream(handler, cfg, state, *, ticket_id: str, include_test_data: bool, query: dict) -> None:
    ws.get_assignment_overview(
        cfg.root,
        ticket_id,
        include_test_data=include_test_data,
    )
    retry_ms = ws.assignment_event_stream_retry_ms()
    keepalive_s = ws.assignment_event_stream_keepalive_s()
    current_seq = ws.assignment_current_event_seq()
    last_seq = max(_assignment_stream_last_seq(handler, query), current_seq)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()
    ready_payload = {
        "ok": True,
        "ticket_id": ticket_id,
        "mode": ws.assignment_execution_refresh_mode(),
        "fallback_poll_interval_ms": int(ws.DEFAULT_ASSIGNMENT_EXECUTION_POLL_INTERVAL_MS),
        "current_seq": int(current_seq),
    }
    if not _assignment_sse_write(
        handler,
        event="ready",
        payload=ready_payload,
        event_id=current_seq,
        retry_ms=retry_ms,
    ):
        return
    while not state.stop_event.is_set():
        batch = ws.assignment_wait_runtime_events(last_seq, timeout_s=keepalive_s)
        current_seq = int(batch.get("current_seq") or last_seq)
        if bool(batch.get("reset_required")):
            if not _assignment_sse_write(
                handler,
                event="reset",
                payload={
                    "ok": True,
                    "ticket_id": ticket_id,
                    "mode": ws.assignment_execution_refresh_mode(),
                    "reason": "event_history_overflow",
                    "current_seq": current_seq,
                },
                event_id=current_seq,
            ):
                return
            last_seq = current_seq
            continue
        events = [
            dict(item)
            for item in list(batch.get("events") or [])
            if str((item or {}).get("ticket_id") or "").strip() == ticket_id
        ]
        if not events:
            last_seq = current_seq
            if list(batch.get("events") or []):
                continue
            if not _assignment_sse_comment(handler, "keepalive"):
                return
            continue
        for item in events:
            seq = int(item.get("seq") or last_seq)
            event_name = "run" if str(item.get("kind") or "").strip().lower() == "run" else "snapshot"
            if not _assignment_sse_write(
                handler,
                event=event_name,
                payload={"ok": True, **item},
                event_id=seq,
            ):
                return
            last_seq = seq


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    query = ctx.get("query") or {}
    include_test_data = ws.resolve_include_test_data(query, cfg, state)
    policy_fields = ws.show_test_data_policy_fields(cfg, state)

    if path.startswith("/api/assignments") and not handler.ensure_root_ready():
        return True

    if path == "/api/assignments/settings/concurrency":
        data = ws.get_assignment_concurrency_settings(cfg.root)
        handler.send_json(200, {"ok": True, **policy_fields, **data})
        return True

    if path == "/api/assignments/settings/execution":
        data = ws.get_assignment_execution_settings(cfg.root)
        handler.send_json(200, {"ok": True, **policy_fields, **data})
        return True

    martifact_preview = re.fullmatch(
        r"/api/assignments/([0-9A-Za-z._:-]+)/nodes/([0-9A-Za-z._:-]+)/artifact-preview",
        path,
    )
    if martifact_preview:
        try:
            data = ws.read_assignment_artifact_preview(
                cfg.root,
                ticket_id_text=ws.safe_token(martifact_preview.group(1), "", 160),
                node_id_text=ws.safe_token(martifact_preview.group(2), "", 160),
                path_index=_parse_int_query(query, "path_index", 0),
                include_test_data=include_test_data,
            )
            handler.send_text(200, str(data.get("content") or ""), str(data.get("content_type") or "text/plain; charset=utf-8"))
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/assignments":
        data = ws.list_assignments(
            cfg.root,
            include_test_data=include_test_data,
            source_workflow=str((query.get("source_workflow") or [""])[0] or "").strip(),
            external_request_id=str((query.get("external_request_id") or [""])[0] or "").strip(),
            offset=_parse_int_query(query, "offset", 0),
            limit=_parse_int_query(query, "limit", 0),
        )
        handler.send_json(200, {"ok": True, "include_test_data": include_test_data, **policy_fields, **data})
        return True

    mgraph = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/graph", path)
    if mgraph:
        try:
            data = ws.get_assignment_graph(
                cfg.root,
                ws.safe_token(mgraph.group(1), "", 160),
                active_loaded=_parse_int_query(query, "active_loaded", 0),
                active_batch_size=_parse_int_query(query, "active_batch_size", 24),
                history_loaded=_parse_int_query(query, "history_loaded", 0),
                history_batch_size=_parse_int_query(query, "history_batch_size", 12),
                include_test_data=include_test_data,
            )
            handler.send_json(200, {"ok": True, "include_test_data": include_test_data, **policy_fields, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mdetail = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/status-detail", path)
    if mdetail:
        try:
            data = ws.get_assignment_status_detail(
                cfg.root,
                ws.safe_token(mdetail.group(1), "", 160),
                node_id_text=str((query.get("node_id") or [""])[0] or "").strip(),
                include_test_data=include_test_data,
            )
            handler.send_json(200, {"ok": True, "include_test_data": include_test_data, **policy_fields, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mevents = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/events", path)
    if mevents:
        try:
            _handle_assignment_events_stream(
                handler,
                cfg,
                state,
                ticket_id=ws.safe_token(mevents.group(1), "", 160),
                include_test_data=include_test_data,
                query=query,
            )
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mscheduler = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/scheduler-state", path)
    if mscheduler:
        try:
            data = ws.get_assignment_scheduler_state(
                cfg.root,
                ws.safe_token(mscheduler.group(1), "", 160),
                include_test_data=include_test_data,
            )
            handler.send_json(200, {"ok": True, "include_test_data": include_test_data, **policy_fields, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    moverview = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)", path)
    if moverview:
        try:
            data = ws.get_assignment_overview(
                cfg.root,
                ws.safe_token(moverview.group(1), "", 160),
                include_test_data=include_test_data,
            )
            handler.send_json(200, {"ok": True, "include_test_data": include_test_data, **policy_fields, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False


def try_handle_post(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}
    current_include_test_data = ws.current_show_test_data(cfg, state)
    policy_fields = ws.show_test_data_policy_fields(cfg, state)

    if path.startswith("/api/assignments") and not handler.ensure_root_ready():
        return True

    if path == "/api/assignments/settings/concurrency":
        try:
            data = ws.set_assignment_concurrency_settings(
                cfg.root,
                global_concurrency_limit=body.get("global_concurrency_limit"),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/assignments/settings/execution":
        try:
            data = ws.set_assignment_execution_settings(
                cfg.root,
                execution_provider=body.get("execution_provider"),
                codex_command_path=body.get("codex_command_path"),
                command_template=body.get("command_template"),
                global_concurrency_limit=body.get("global_concurrency_limit"),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/assignments":
        try:
            next_body = dict(body)
            if not current_include_test_data:
                next_body["is_test_data"] = False
            data = ws.create_assignment_graph(cfg, next_body)
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/assignments/test-data/bootstrap":
        try:
            if not current_include_test_data:
                raise ws.AssignmentCenterError(
                    409,
                    "assignment test data hidden by environment policy",
                    "assignment_test_data_hidden",
                    {
                        **policy_fields,
                        "read_only": True,
                    },
                )
            data = ws.bootstrap_assignment_test_graph(
                cfg,
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mnode = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/nodes", path)
    if mnode:
        try:
            data = ws.create_assignment_node(
                cfg,
                ws.safe_token(mnode.group(1), "", 160),
                body,
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mdispatch = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/dispatch-next", path)
    if mdispatch:
        try:
            data = ws.dispatch_assignment_next(
                cfg.root,
                ticket_id_text=ws.safe_token(mdispatch.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mpause = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/pause", path)
    if mpause:
        try:
            data = ws.pause_assignment_scheduler(
                cfg.root,
                ticket_id_text=ws.safe_token(mpause.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
                pause_note=body.get("pause_note") or body.get("note") or "",
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mresume = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/resume", path)
    if mresume:
        try:
            data = ws.resume_assignment_scheduler(
                cfg.root,
                ticket_id_text=ws.safe_token(mresume.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
                pause_note=body.get("pause_note") or body.get("note") or "",
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mclear = re.fullmatch(r"/api/assignments/([0-9A-Za-z._:-]+)/clear", path)
    if mclear:
        try:
            data = ws.clear_assignment_graph(
                cfg.root,
                ticket_id_text=ws.safe_token(mclear.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
                reason=body.get("reason") or "",
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    msuccess = re.fullmatch(
        r"/api/assignments/([0-9A-Za-z._:-]+)/nodes/([0-9A-Za-z._:-]+)/mark-success",
        path,
    )
    if msuccess:
        try:
            data = ws.mark_assignment_node_success(
                cfg.root,
                ticket_id_text=ws.safe_token(msuccess.group(1), "", 160),
                node_id_text=ws.safe_token(msuccess.group(2), "", 160),
                success_reason=body.get("success_reason"),
                result_ref=body.get("result_ref") or "",
                operator=str(body.get("operator") or "web-user"),
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mdeliver = re.fullmatch(
        r"/api/assignments/([0-9A-Za-z._:-]+)/nodes/([0-9A-Za-z._:-]+)/deliver-artifact",
        path,
    )
    if mdeliver:
        try:
            data = ws.deliver_assignment_artifact(
                cfg.root,
                ticket_id_text=ws.safe_token(mdeliver.group(1), "", 160),
                node_id_text=ws.safe_token(mdeliver.group(2), "", 160),
                operator=str(body.get("operator") or "web-user"),
                artifact_label=body.get("artifact_label") or body.get("artifactLabel") or "",
                delivery_note=body.get("delivery_note") or body.get("deliveryNote") or "",
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mfailed = re.fullmatch(
        r"/api/assignments/([0-9A-Za-z._:-]+)/nodes/([0-9A-Za-z._:-]+)/mark-failed",
        path,
    )
    if mfailed:
        try:
            data = ws.mark_assignment_node_failed(
                cfg.root,
                ticket_id_text=ws.safe_token(mfailed.group(1), "", 160),
                node_id_text=ws.safe_token(mfailed.group(2), "", 160),
                failure_reason=body.get("failure_reason"),
                operator=str(body.get("operator") or "web-user"),
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrerun = re.fullmatch(
        r"/api/assignments/([0-9A-Za-z._:-]+)/nodes/([0-9A-Za-z._:-]+)/rerun",
        path,
    )
    if mrerun:
        try:
            data = ws.rerun_assignment_node(
                cfg.root,
                ticket_id_text=ws.safe_token(mrerun.group(1), "", 160),
                node_id_text=ws.safe_token(mrerun.group(2), "", 160),
                operator=str(body.get("operator") or "web-user"),
                reason=body.get("reason") or "",
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    moverride = re.fullmatch(
        r"/api/assignments/([0-9A-Za-z._:-]+)/nodes/([0-9A-Za-z._:-]+)/override-status",
        path,
    )
    if moverride:
        try:
            data = ws.override_assignment_node_status(
                cfg.root,
                ticket_id_text=ws.safe_token(moverride.group(1), "", 160),
                node_id_text=ws.safe_token(moverride.group(2), "", 160),
                target_status=body.get("target_status") or body.get("status") or "",
                operator=str(body.get("operator") or "web-user"),
                reason=body.get("reason") or "",
                result_ref=body.get("result_ref") or body.get("resultRef") or "",
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False


def try_handle_delete(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}
    current_include_test_data = ws.current_show_test_data(cfg, state)

    if path.startswith("/api/assignments") and not handler.ensure_root_ready():
        return True

    mdelete_node = re.fullmatch(
        r"/api/assignments/([0-9A-Za-z._:-]+)/nodes/([0-9A-Za-z._:-]+)",
        path,
    )
    if mdelete_node:
        try:
            data = ws.delete_assignment_node(
                cfg.root,
                ticket_id_text=ws.safe_token(mdelete_node.group(1), "", 160),
                node_id_text=ws.safe_token(mdelete_node.group(2), "", 160),
                operator=str(body.get("operator") or "web-user"),
                reason=body.get("reason") or "",
                include_test_data=current_include_test_data,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.AssignmentCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False
