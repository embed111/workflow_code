from __future__ import annotations

from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

from .legacy_post_route_registry import StaticPostRoute, dispatch_post_route_registry


def _handle_agent_search_root(handler, cfg, state, body: dict[str, Any], _match) -> None:
    requested_root = str(
        body.get("agent_search_root")
        or body.get("agentSearchRoot")
        or ""
    ).strip()
    if not requested_root:
        handler.send_json(400, {"ok": False, "error": "agent_search_root required", "code": "agent_search_root_required"})
        return
    try:
        result = switch_agent_search_root(cfg, state, requested_root)
        handler.send_json(200, result)
    except SessionGateError as exc:
        handler.send_json(
            exc.status_code,
            {"ok": False, "error": str(exc), "code": exc.code, **exc.extra},
        )


def _handle_show_test_data(handler, cfg, state, body: dict[str, Any], _match) -> None:
    requested = parse_bool_flag(
        body.get("show_test_data", body.get("showTestData")),
        default=current_show_test_data(cfg, state),
    )
    handler.send_json(
        410,
        show_test_data_toggle_removed_payload(
            cfg,
            state,
            requested_value=requested,
        ),
    )


def _handle_manual_policy_input(handler, cfg, state, body: dict[str, Any], _match) -> None:
    requested = parse_bool_flag(
        body.get("allow_manual_policy_input", body.get("allowManualPolicyInput")),
        default=current_allow_manual_policy_input(cfg, state),
    )
    old_value, new_value = set_allow_manual_policy_input(cfg, state, requested)
    append_change_log(
        cfg.root,
        "manual policy input toggle",
        f"old={int(old_value)}, new={int(new_value)}",
    )
    handler.send_json(
        200,
        {
            "ok": True,
            "allow_manual_policy_input": bool(new_value),
            "previous_allow_manual_policy_input": bool(old_value),
        },
    )


_PRE_ROOT_CONFIG_POST_ROUTES = (
    StaticPostRoute("/api/config/agent-search-root", _handle_agent_search_root),
    StaticPostRoute("/api/config/show-test-data", _handle_show_test_data),
)

_POST_ROOT_CONFIG_POST_ROUTES = (
    StaticPostRoute("/api/config/manual-policy-input", _handle_manual_policy_input),
)


def try_handle_legacy_pre_root_post_config_routes(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    return dispatch_post_route_registry(
        self,
        cfg,
        state,
        path,
        body,
        static_routes=_PRE_ROOT_CONFIG_POST_ROUTES,
    )


def try_handle_legacy_post_root_config_routes(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    return dispatch_post_route_registry(
        self,
        cfg,
        state,
        path,
        body,
        static_routes=_POST_ROOT_CONFIG_POST_ROUTES,
    )
