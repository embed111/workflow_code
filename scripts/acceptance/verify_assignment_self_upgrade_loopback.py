#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import runtime_upgrade_service
    from workflow_app.server.services.assignment_service_parts import assignment_self_iteration_runtime as runtime

    task_record = {
        "ticket_id": "asg-20260408-upgrade",
        "is_test_data": False,
    }
    node_record = {
        "node_id": "node-self-upgrade",
        "assigned_agent_id": "workflow",
        "record_state": "active",
    }

    requested_calls: list[dict[str, object]] = []

    def request_upgrade(
        *,
        base_url: str,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout_seconds: float = 0.0,
    ) -> tuple[int, dict]:
        requested_calls.append(
            {
                "base_url": base_url,
                "method": method,
                "path": path,
                "payload": dict(payload or {}),
                "timeout_seconds": float(timeout_seconds or 0.0),
            }
        )
        if str(method or "").upper() == "GET":
            return 200, {
                "ok": True,
                "can_upgrade": True,
                "request_pending": False,
                "current_version": "20260407-200414",
                "candidate_version": "20260408-060001",
            }
        return 202, {
            "ok": True,
            "request_pending": True,
            "current_version": "20260407-200414",
            "candidate_version": "20260408-060001",
        }

    blocked_calls: list[dict[str, object]] = []

    def request_blocked(
        *,
        base_url: str,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout_seconds: float = 0.0,
    ) -> tuple[int, dict]:
        blocked_calls.append(
            {
                "base_url": base_url,
                "method": method,
                "path": path,
                "payload": dict(payload or {}),
                "timeout_seconds": float(timeout_seconds or 0.0),
            }
        )
        return 200, {
            "ok": True,
            "can_upgrade": False,
            "request_pending": False,
            "blocking_reason_code": "running_tasks_present",
            "current_version": "20260407-200414",
            "candidate_version": "20260408-060001",
        }

    pending_calls: list[dict[str, object]] = []

    def request_pending(
        *,
        base_url: str,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout_seconds: float = 0.0,
    ) -> tuple[int, dict]:
        pending_calls.append(
            {
                "base_url": base_url,
                "method": method,
                "path": path,
                "payload": dict(payload or {}),
                "timeout_seconds": float(timeout_seconds or 0.0),
            }
        )
        return 200, {
            "ok": True,
            "can_upgrade": False,
            "request_pending": True,
            "blocking_reason_code": "upgrade_switching",
            "current_version": "20260407-200414",
            "candidate_version": "20260408-060001",
        }

    common_patches = [
        patch.object(runtime_upgrade_service, "current_runtime_environment", return_value="prod"),
        patch.object(runtime_upgrade_service, "current_runtime_instance", return_value={"host": "127.0.0.1", "port": 8090}),
        patch.object(runtime_upgrade_service, "current_runtime_manifest", return_value={}),
    ]

    for ctx in common_patches:
        ctx.start()
    try:
        with patch.object(runtime, "_assignment_runtime_upgrade_json_request", side_effect=request_upgrade):
            requested = runtime._assignment_maybe_request_prod_upgrade_after_finalize(
                workspace_root,
                task_record=task_record,
                node_record=node_record,
            )
        assert bool(requested.get("requested")), requested
        assert bool(requested.get("suppress_dispatch")), requested
        assert len(requested_calls) == 2, requested_calls
        assert str(requested_calls[0].get("method") or "").upper() == "GET", requested_calls
        assert str(requested_calls[1].get("method") or "").upper() == "POST", requested_calls
        post_payload = dict(requested_calls[1].get("payload") or {})
        assert post_payload.get("operator") == runtime.ASSIGNMENT_SELF_UPGRADE_OPERATOR, post_payload
        assert post_payload.get("exclude_assignment_ticket_id") == task_record["ticket_id"], post_payload
        assert post_payload.get("exclude_assignment_node_id") == node_record["node_id"], post_payload

        with patch.object(runtime, "_assignment_runtime_upgrade_json_request", side_effect=request_blocked):
            blocked = runtime._assignment_maybe_request_prod_upgrade_after_finalize(
                workspace_root,
                task_record=task_record,
                node_record=node_record,
            )
        assert not bool(blocked.get("requested")), blocked
        assert not bool(blocked.get("suppress_dispatch")), blocked
        assert str(blocked.get("reason") or "") == "running_tasks_present", blocked
        assert len(blocked_calls) == 1, blocked_calls

        with patch.object(runtime, "_assignment_runtime_upgrade_json_request", side_effect=request_pending):
            pending = runtime._assignment_maybe_request_prod_upgrade_after_finalize(
                workspace_root,
                task_record=task_record,
                node_record=node_record,
            )
        assert not bool(pending.get("requested")), pending
        assert bool(pending.get("suppress_dispatch")), pending
        assert str(pending.get("reason") or "") == "runtime_upgrade_already_requested", pending
        assert len(pending_calls) == 1, pending_calls
    finally:
        for ctx in reversed(common_patches):
            ctx.stop()

    print(
        json.dumps(
            {
                "ok": True,
                "requested_reason": str(requested.get("reason") or ""),
                "blocked_reason": str(blocked.get("reason") or ""),
                "pending_reason": str(pending.get("reason") or ""),
                "requested_call_count": len(requested_calls),
                "blocked_call_count": len(blocked_calls),
                "pending_call_count": len(pending_calls),
                "apply_path": str(requested_calls[1].get("path") or ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
