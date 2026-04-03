from __future__ import annotations

from .legacy_admin_handlers import normalize_legacy_admin_context
from .legacy_chat_handlers import handle_get_legacy as _handle_get_legacy
from .legacy_task_handlers import handle_post_legacy as _handle_post_legacy


def handle_get_legacy(self, cfg, state) -> None:
    normalize_legacy_admin_context(self, cfg, state)
    _handle_get_legacy(self, cfg, state)


def handle_post_legacy(self, cfg, state) -> None:
    normalize_legacy_admin_context(self, cfg, state)
    _handle_post_legacy(self, cfg, state)
