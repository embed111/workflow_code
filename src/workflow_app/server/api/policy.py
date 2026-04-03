from __future__ import annotations

from ..bootstrap import web_server_runtime as ws


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    query = ctx.get("query") or {}

    if path == "/api/policy/closure/stats":
        handler.send_json(
            200,
            {
                "ok": True,
                "stats": ws.policy_closure_stats(cfg.root),
            },
        )
        return True

    if path == "/api/policy/patch-tasks":
        try:
            limit = int((query.get("limit") or ["200"])[0])
        except Exception:
            limit = 200
        handler.send_json(
            200,
            {
                "ok": True,
                "items": ws.list_agent_policy_patch_tasks(cfg.root, limit=limit),
            },
        )
        return True

    if path == "/api/reconcile/latest":
        handler.send_json(200, {"ok": True, "latest": ws.latest_reconcile(cfg.root)})
        return True

    return False


def try_handle_post(handler, cfg, state, ctx: dict) -> bool:
    # policy POST endpoints are still delegated to legacy router in this phase.
    _path = str(ctx.get("path") or "")
    return False

