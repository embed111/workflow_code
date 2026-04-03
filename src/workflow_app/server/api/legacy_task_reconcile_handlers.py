from __future__ import annotations

from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

def try_handle_task_reconcile_routes(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    if path == "/api/actions/decide":
        decision = str(body.get("decision") or "train").strip()
        if decision not in {"train", "skip", "need_info"}:
            self.send_json(400, {"ok": False, "error": "invalid decision"})
            return True
        reason = str(body.get("reason") or "web-decision").strip()[:200]
        limit = int(body.get("limit") or 20)
        try:
            self.send_json(200, {"ok": True, **run_decide(cfg, decision, reason, limit)})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
        return True
    if path == "/api/actions/train":
        try:
            self.send_json(200, {"ok": True, **run_train(cfg, int(body.get("limit") or 20), int(body.get("max_retries") or 3))})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
        return True
    if path == "/api/reconcile/run":
        try:
            with state.reconcile_lock:
                self.send_json(200, {"ok": True, **run_reconcile(cfg, "manual")})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
        return True
    if path == "/api/ab/deploy":
        if not AB_FEATURE_ENABLED:
            self.send_json(410, {"ok": False, "error": "ab disabled", "code": "ab_disabled"})
            return True
        version = str(body.get("version") or "").strip()
        if not version:
            self.send_json(400, {"ok": False, "error": "version required"})
            return True
        result = deploy_and_switch(cfg, version, "web")
        self.send_json(200 if result.get("ok") else 500, {"ok": bool(result.get("ok")), **result})
        return True
    if path == "/api/ab/rollback":
        if not AB_FEATURE_ENABLED:
            self.send_json(410, {"ok": False, "error": "ab disabled", "code": "ab_disabled"})
            return True
        result = rollback_switch(cfg, "web")
        self.send_json(200 if result.get("ok") else 500, {"ok": bool(result.get("ok")), **result})
        return True
        return False

