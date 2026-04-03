from __future__ import annotations

# Legacy endpoint implementations moved out to reduce API routing module size.
from .legacy_route_handlers import handle_get_legacy, handle_post_legacy

__all__ = ["handle_get_legacy", "handle_post_legacy"]
