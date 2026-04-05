#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure assignment/dashboard read latency against a runtime root.")
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--agent-search-root", default="D:/code/AI/J-Agents")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.api.dashboard import _workboard_payload
    from workflow_app.server.infra.audit_runtime import dashboard as base_dashboard
    from workflow_app.server.services import assignment_service

    root = Path(args.runtime_root).resolve()
    cfg = type(
        "LatencyCfg",
        (),
        {
            "root": root,
            "agent_search_root": Path(args.agent_search_root).resolve(),
            "show_test_data": False,
        },
    )()
    results: dict[str, Any] = {"runtime_root": root.as_posix()}

    checks = [
        ("canonical_ticket", lambda: assignment_service._assignment_ensure_workflow_ui_global_graph_ticket(root)),
        ("list_assignments", lambda: assignment_service.list_assignments(root, include_test_data=False)),
        ("workboard_payload", lambda: _workboard_payload(cfg, include_test_data=False)),
        ("base_dashboard", lambda: base_dashboard(cfg, include_test_data=False)),
    ]
    for name, fn in checks:
        started = time.perf_counter()
        data = fn()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if isinstance(data, dict):
            keys = sorted(data.keys())
        else:
            keys = []
        results[name] = {
            "elapsed_ms": elapsed_ms,
            "type": type(data).__name__,
            "keys": keys[:12],
        }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
