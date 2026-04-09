#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    import workflow_app.server.services.assignment_service_parts.task_artifact_store_runtime_metrics as metrics

    fallback_node_metrics = {
        "running_task_count": 1,
        "running_agent_count": 1,
        "active_execution_count": 1,
        "agent_call_count": 1,
    }
    with patch.object(metrics, "_active_assignment_run_ids", return_value=["ghost-run"], create=True), patch.object(
        metrics,
        "_get_assignment_runtime_metrics_from_files",
        return_value={
            "running_task_count": 0,
            "running_agent_count": 0,
            "active_execution_count": 0,
            "agent_call_count": 0,
        },
    ) as file_metrics_mock, patch.object(
        metrics,
        "_get_assignment_runtime_metrics_from_node_files",
        return_value=fallback_node_metrics,
    ) as node_metrics_mock:
        fallback_payload = metrics.get_assignment_runtime_metrics(
            Path("C:/runtime-root"),
            include_test_data=False,
        )

    assert fallback_payload == fallback_node_metrics, fallback_payload
    assert file_metrics_mock.called, "file metrics probe not invoked"
    assert node_metrics_mock.called, "node metrics fallback not invoked"

    preferred_file_metrics = {
        "running_task_count": 2,
        "running_agent_count": 1,
        "active_execution_count": 2,
        "agent_call_count": 2,
    }
    with patch.object(metrics, "_active_assignment_run_ids", return_value=["live-run"], create=True), patch.object(
        metrics,
        "_get_assignment_runtime_metrics_from_files",
        return_value=preferred_file_metrics,
    ) as live_file_metrics_mock, patch.object(
        metrics,
        "_get_assignment_runtime_metrics_from_node_files",
        return_value=fallback_node_metrics,
    ) as live_node_metrics_mock:
        preferred_payload = metrics.get_assignment_runtime_metrics(
            Path("C:/runtime-root"),
            include_test_data=False,
        )

    assert preferred_payload == preferred_file_metrics, preferred_payload
    assert live_file_metrics_mock.called, "file metrics fast path not invoked"
    assert not live_node_metrics_mock.called, "node metrics fallback should stay unused when file truth is live"

    print(
        json.dumps(
            {
                "ok": True,
                "fallback_payload": fallback_payload,
                "preferred_payload": preferred_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
