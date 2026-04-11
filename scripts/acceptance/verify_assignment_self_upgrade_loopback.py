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
        "ticket_id": "asg-20260411-upgrade-delegated",
        "is_test_data": False,
    }
    node_record = {
        "node_id": "node-running-mainline",
        "assigned_agent_id": "workflow",
        "record_state": "active",
    }

    disabled_node_record = {
        "node_id": "node-non-mainline",
        "assigned_agent_id": "workflow_bugmate",
        "record_state": "active",
    }

    with (
        patch.object(runtime_upgrade_service, "current_runtime_environment", return_value="prod"),
        patch.object(runtime_upgrade_service, "current_runtime_instance", return_value={"host": "127.0.0.1", "port": 8090}),
        patch.object(runtime_upgrade_service, "current_runtime_manifest", return_value={}),
    ):
        delegated = runtime._assignment_maybe_request_prod_upgrade_after_finalize(
            workspace_root,
            task_record=task_record,
            node_record=node_record,
        )

    assert not bool(delegated.get("requested")), delegated
    assert not bool(delegated.get("suppress_dispatch")), delegated
    assert str(delegated.get("reason") or "") == "runtime_upgrade_delegated_to_watchdog", delegated
    assert str(delegated.get("ticket_id") or "") == task_record["ticket_id"], delegated
    assert str(delegated.get("node_id") or "") == node_record["node_id"], delegated
    assert str(delegated.get("base_url") or "") == "http://127.0.0.1:8090", delegated

    not_enabled = runtime._assignment_maybe_request_prod_upgrade_after_finalize(
        workspace_root,
        task_record=task_record,
        node_record=disabled_node_record,
    )
    assert not bool(not_enabled.get("requested")), not_enabled
    assert str(not_enabled.get("reason") or "") == "agent_not_enabled", not_enabled

    print(
        json.dumps(
            {
                "ok": True,
                "delegated_reason": str(delegated.get("reason") or ""),
                "delegated_base_url": str(delegated.get("base_url") or ""),
                "ticket_id": str(delegated.get("ticket_id") or ""),
                "node_id": str(delegated.get("node_id") or ""),
                "not_enabled_reason": str(not_enabled.get("reason") or ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
