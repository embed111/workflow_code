from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import re


PostRouteCommand = Callable[[Any, Any, Any, dict[str, Any], re.Match[str] | None], None]


@dataclass(frozen=True)
class StaticPostRoute:
    path: str
    command: PostRouteCommand


@dataclass(frozen=True)
class RegexPostRoute:
    pattern: re.Pattern[str]
    command: PostRouteCommand


def dispatch_post_route_registry(
    handler: Any,
    cfg: Any,
    state: Any,
    path: str,
    body: dict[str, Any],
    *,
    static_routes: Sequence[StaticPostRoute] = (),
    regex_routes: Sequence[RegexPostRoute] = (),
) -> bool:
    for route in static_routes:
        if path == route.path:
            route.command(handler, cfg, state, body, None)
            return True
    for route in regex_routes:
        matched = route.pattern.fullmatch(path)
        if matched:
            route.command(handler, cfg, state, body, matched)
            return True
    return False
