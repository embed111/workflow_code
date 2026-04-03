from __future__ import annotations

# NOTE: legacy full-route implementation extracted from workflow_web_server.py
# Keep behavior-compatible while routing is being modularized.
from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

from .legacy_task_config_handlers import (
    try_handle_legacy_post_root_config_routes,
    try_handle_legacy_pre_root_post_config_routes,
)
from .legacy_task_crud_handlers import try_handle_task_crud_routes
from .legacy_task_policy_handlers import try_handle_legacy_post_policy_routes
from .legacy_task_queue_handlers import (
    handle_chat_non_stream,
    handle_chat_stream,
    handle_task_execute,
)
from .legacy_task_reconcile_handlers import try_handle_task_reconcile_routes
from .legacy_task_session_handlers import try_handle_legacy_post_session_routes
from .legacy_task_training_handlers import try_handle_legacy_post_training_routes
from .legacy_task_workflow_handlers import try_handle_legacy_post_workflow_routes


_POST_ROOT_HANDLER_CHAIN = (
    try_handle_legacy_post_root_config_routes,
    try_handle_legacy_post_training_routes,
    try_handle_legacy_post_policy_routes,
    try_handle_legacy_post_session_routes,
    try_handle_legacy_post_workflow_routes,
    try_handle_task_crud_routes,
    try_handle_task_reconcile_routes,
)


def _read_cached_legacy_body(self) -> dict[str, Any] | None:
    cached_body = getattr(self, "_cached_request_body", None)
    if isinstance(cached_body, dict):
        body = cached_body
    else:
        try:
            body = self.read_json()
        except Exception:
            self.send_json(400, {"ok": False, "error": "invalid json"})
            return None
    try:
        delattr(self, "_cached_request_body")
    except Exception:
        pass
    return body


def _dispatch_post_root_handler_chain(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    for handler in _POST_ROOT_HANDLER_CHAIN:
        if handler(self, cfg, state, path, body):
            return True
    return False


def handle_post_legacy(self, cfg, state) -> None:
    path = urlparse(self.path).path
    body = _read_cached_legacy_body(self)
    if body is None:
        return
    if try_handle_legacy_pre_root_post_config_routes(self, cfg, state, path, body):
        return
    if not self.ensure_root_ready():
        return
    if path == "/api/chat":
        handle_chat_non_stream(self, cfg, state, body)
        return
    if path == "/api/chat/stream":
        handle_chat_stream(self, cfg, state, body)
        return
    if path == "/api/tasks/execute":
        handle_task_execute(self, cfg, state, body)
        return
    if _dispatch_post_root_handler_chain(self, cfg, state, path, body):
        return
    self.send_json(404, {"ok": False, "error": "not found"})
