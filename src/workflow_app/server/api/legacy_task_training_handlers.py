from __future__ import annotations

import re

from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

from .legacy_post_route_registry import RegexPostRoute, StaticPostRoute, dispatch_post_route_registry


def _send_training_center_error(handler, exc: TrainingCenterError) -> None:
    payload = {"ok": False, "error": str(exc), "code": exc.code}
    payload.update(exc.extra)
    handler.send_json(exc.status_code, payload)


def _handle_training_plan_manual(handler, cfg, _state, body: dict[str, Any], _match) -> None:
    try:
        data = create_training_plan_and_enqueue(
            cfg,
            body,
            forced_source="manual",
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_plan_auto(handler, cfg, _state, body: dict[str, Any], _match) -> None:
    try:
        data = create_training_plan_and_enqueue(
            cfg,
            body,
            forced_source="auto_analysis",
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_agent_switch(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = switch_training_agent_release(
            cfg,
            agent_id=safe_token((matched.group(1) if matched else ""), "", 120),
            version_label=str(
                body.get("version_label")
                or body.get("target_version")
                or ""
            ).strip(),
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_agent_clone(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = clone_training_agent_from_current(
            cfg,
            agent_id=safe_token((matched.group(1) if matched else ""), "", 120),
            new_agent_name=str(
                body.get("new_agent_name")
                or body.get("agent_name")
                or body.get("clone_agent_name")
                or ""
            ).strip(),
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_pre_release_discard(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = discard_agent_pre_release(
            cfg,
            agent_id=safe_token((matched.group(1) if matched else ""), "", 120),
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_release_evaluation_manual(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = submit_manual_release_evaluation(
            cfg,
            agent_id=safe_token((matched.group(1) if matched else ""), "", 120),
            decision=str(body.get("decision") or "").strip(),
            reviewer=str(body.get("reviewer") or "").strip(),
            summary=str(body.get("summary") or "").strip(),
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_release_review_enter(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = enter_training_agent_release_review(
            cfg,
            agent_id=safe_token((matched.group(1) if matched else ""), "", 120),
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_release_review_discard(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = discard_training_agent_release_review(
            cfg,
            agent_id=safe_token((matched.group(1) if matched else ""), "", 120),
            operator=str(body.get("operator") or "web-user"),
            reason=str(body.get("reason") or body.get("review_comment") or body.get("summary") or "").strip(),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_release_review_manual(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = submit_training_agent_release_review_manual(
            cfg,
            agent_id=safe_token((matched.group(1) if matched else ""), "", 120),
            decision=str(body.get("decision") or "").strip(),
            reviewer=str(body.get("reviewer") or "").strip(),
            review_comment=str(body.get("review_comment") or body.get("summary") or "").strip(),
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_release_review_confirm(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = confirm_training_agent_release_review(
            cfg,
            agent_id=safe_token((matched.group(1) if matched else ""), "", 120),
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_queue_remove(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = remove_training_queue_item(
            cfg.root,
            queue_task_id_text=safe_token((matched.group(1) if matched else ""), "", 160),
            operator=str(body.get("operator") or "web-user"),
            reason=str(body.get("reason") or ""),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_queue_execute(handler, cfg, _state, body: dict[str, Any], matched: re.Match[str] | None) -> None:
    try:
        data = execute_training_queue_item(
            cfg.root,
            queue_task_id_text=safe_token((matched.group(1) if matched else ""), "", 160),
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


def _handle_training_queue_dispatch_next(handler, cfg, _state, body: dict[str, Any], _match) -> None:
    try:
        data = dispatch_next_training_queue_item(
            cfg.root,
            operator=str(body.get("operator") or "web-user"),
        )
        handler.send_json(200, {"ok": True, **data})
    except TrainingCenterError as exc:
        _send_training_center_error(handler, exc)


_TRAINING_STATIC_POST_ROUTES = (
    StaticPostRoute("/api/training/plans/manual", _handle_training_plan_manual),
    StaticPostRoute("/api/training/plans/auto", _handle_training_plan_auto),
    StaticPostRoute("/api/training/queue/dispatch-next", _handle_training_queue_dispatch_next),
)

_TRAINING_REGEX_POST_ROUTES = (
    RegexPostRoute(re.compile(r"/api/training/agents/([0-9A-Za-z._:-]+)/switch"), _handle_training_agent_switch),
    RegexPostRoute(re.compile(r"/api/training/agents/([0-9A-Za-z._:-]+)/clone"), _handle_training_agent_clone),
    RegexPostRoute(re.compile(r"/api/training/agents/([0-9A-Za-z._:-]+)/pre-release/discard"), _handle_training_pre_release_discard),
    RegexPostRoute(
        re.compile(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-evaluations/manual"),
        _handle_training_release_evaluation_manual,
    ),
    RegexPostRoute(re.compile(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review/enter"), _handle_training_release_review_enter),
    RegexPostRoute(re.compile(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review/discard"), _handle_training_release_review_discard),
    RegexPostRoute(re.compile(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review/manual"), _handle_training_release_review_manual),
    RegexPostRoute(re.compile(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review/confirm"), _handle_training_release_review_confirm),
    RegexPostRoute(re.compile(r"/api/training/queue/([0-9A-Za-z._:-]+)/remove"), _handle_training_queue_remove),
    RegexPostRoute(re.compile(r"/api/training/queue/([0-9A-Za-z._:-]+)/execute"), _handle_training_queue_execute),
)


def try_handle_legacy_post_training_routes(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    return dispatch_post_route_registry(
        self,
        cfg,
        state,
        path,
        body,
        static_routes=_TRAINING_STATIC_POST_ROUTES,
        regex_routes=_TRAINING_REGEX_POST_ROUTES,
    )
