from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from . import assignments, chat, config, dashboard, defects, legacy, policy, runtime_upgrade, schedules, training


def dispatch_get(handler, cfg, state) -> None:
    parsed = urlparse(handler.path)
    path = parsed.path
    query = parse_qs(parsed.query)

    _root, root_ready, root_error, root_text = handler.root_status()
    ctx = {
        "path": path,
        "query": query,
        "root_ready": bool(root_ready),
        "root_error": root_error,
        "root_text": root_text,
    }

    if config.try_handle_get(handler, cfg, state, ctx):
        return
    if runtime_upgrade.try_handle_get(handler, cfg, state, ctx):
        return
    if dashboard.try_handle_get(handler, cfg, state, ctx):
        return
    if chat.try_handle_get(handler, cfg, state, ctx):
        return
    if training.try_handle_get(handler, cfg, state, ctx):
        return
    if assignments.try_handle_get(handler, cfg, state, ctx):
        return
    if schedules.try_handle_get(handler, cfg, state, ctx):
        return
    if defects.try_handle_get(handler, cfg, state, ctx):
        return
    if policy.try_handle_get(handler, cfg, state, ctx):
        return

    legacy.handle_get_legacy(handler, cfg, state)


def dispatch_post(handler, cfg, state) -> None:
    parsed = urlparse(handler.path)
    path = parsed.path

    try:
        body = handler.read_json()
    except Exception:
        handler.send_json(400, {"ok": False, "error": "invalid json"})
        return
    # Legacy handlers may still call `read_json()` internally.
    # Cache the already-parsed payload to avoid double-read blocking.
    try:
        setattr(handler, "_cached_request_body", body)
    except Exception:
        pass

    ctx = {
        "path": path,
        "body": body,
    }

    if config.try_handle_post(handler, cfg, state, ctx):
        return
    if runtime_upgrade.try_handle_post(handler, cfg, state, ctx):
        return
    if training.try_handle_post(handler, cfg, state, ctx):
        return
    if assignments.try_handle_post(handler, cfg, state, ctx):
        return
    if schedules.try_handle_post(handler, cfg, state, ctx):
        return
    if defects.try_handle_post(handler, cfg, state, ctx):
        return
    if policy.try_handle_post(handler, cfg, state, ctx):
        return

    legacy.handle_post_legacy(handler, cfg, state)


def dispatch_delete(handler, cfg, state) -> None:
    parsed = urlparse(handler.path)
    path = parsed.path

    try:
        body = handler.read_json()
    except Exception:
        handler.send_json(400, {"ok": False, "error": "invalid json"})
        return

    ctx = {
        "path": path,
        "body": body,
    }

    if training.try_handle_delete(handler, cfg, state, ctx):
        return
    if assignments.try_handle_delete(handler, cfg, state, ctx):
        return
    if schedules.try_handle_delete(handler, cfg, state, ctx):
        return

    handler.send_json(404, {"ok": False, "error": "not found"})
