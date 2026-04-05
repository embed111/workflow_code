import re

from ..bootstrap import web_server_runtime as ws


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    query = ctx.get("query") or {}

    if path.startswith("/api/schedules") and not handler.ensure_root_ready():
        return True

    if path == "/api/schedules":
        try:
            data = ws.list_schedules(cfg.root)
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/schedules/calendar":
        try:
            data = ws.get_schedule_calendar(
                cfg.root,
                month=str((query.get("month") or [""])[0] or "").strip(),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mdetail = re.fullmatch(r"/api/schedules/([0-9A-Za-z._:-]+)", path)
    if mdetail:
        try:
            data = ws.get_schedule_detail(cfg.root, ws.safe_token(mdetail.group(1), "", 160))
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False


def try_handle_post(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}

    if path.startswith("/api/schedules") and not handler.ensure_root_ready():
        return True

    if path == "/api/schedules":
        try:
            data = ws.create_schedule(cfg, body)
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/schedules/scan":
        try:
            data = ws.run_schedule_scan(
                cfg,
                operator=str(body.get("operator") or "web-user"),
                now_at=str(body.get("now_at") or "").strip(),
                schedule_id=str(body.get("schedule_id") or "").strip(),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/schedules/smoke-baseline":
        try:
            data = ws.run_schedule_smoke_baseline(cfg, body if isinstance(body, dict) else {})
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    menable = re.fullmatch(r"/api/schedules/([0-9A-Za-z._:-]+)/enable", path)
    if menable:
        try:
            data = ws.set_schedule_enabled(
                cfg,
                ws.safe_token(menable.group(1), "", 160),
                enabled=True,
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mdisable = re.fullmatch(r"/api/schedules/([0-9A-Za-z._:-]+)/disable", path)
    if mdisable:
        try:
            data = ws.set_schedule_enabled(
                cfg,
                ws.safe_token(mdisable.group(1), "", 160),
                enabled=False,
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mupdate = re.fullmatch(r"/api/schedules/([0-9A-Za-z._:-]+)", path)
    if mupdate:
        try:
            data = ws.update_schedule(cfg, ws.safe_token(mupdate.group(1), "", 160), body)
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False


def try_handle_delete(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}

    if path.startswith("/api/schedules") and not handler.ensure_root_ready():
        return True

    mdelete = re.fullmatch(r"/api/schedules/([0-9A-Za-z._:-]+)", path)
    if mdelete:
        try:
            data = ws.delete_schedule(
                cfg.root,
                ws.safe_token(mdelete.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.ScheduleCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False
